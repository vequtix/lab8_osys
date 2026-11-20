from __future__ import annotations

import posixpath
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Tuple

CHUNK_SIZE = 4096


def normalize_path(path: str) -> str:
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    normalized = posixpath.normpath(path)
    while normalized.startswith("//"):
        normalized = normalized[1:]
    return normalized or "/"


def parent_path(path: str) -> str:
    norm = normalize_path(path)
    if norm == "/":
        return "/"
    parent = posixpath.dirname(norm)
    return parent if parent else "/"


def _prefix_bounds(dir_path: str) -> Tuple[str, str, int]:
    if dir_path == "/":
        return "/", "0", 2
    prefix = f"{dir_path}/"
    upper = f"{dir_path}0"
    return prefix, upper, len(prefix) + 1


class Database:
    def __init__(self, db_path: str, chunk_size: int = CHUNK_SIZE) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.db_path = db_path
        self.chunk_size = chunk_size
        self.lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.lock:
            with self._transaction() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        path TEXT UNIQUE NOT NULL,
                        mode INTEGER NOT NULL,
                        uid INTEGER NOT NULL,
                        gid INTEGER NOT NULL,
                        size INTEGER DEFAULT 0,
                        atime REAL NOT NULL,
                        mtime REAL NOT NULL,
                        ctime REAL NOT NULL,
                        nlink INTEGER DEFAULT 1
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_id INTEGER NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        data BLOB,
                        FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                        UNIQUE(file_id, chunk_index)
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_file_data_file_id ON file_data(file_id);"
                )

    def get_entry(self, path: str) -> Optional[Dict]:
        norm = normalize_path(path)
        with self.lock:
            with self._transaction() as conn:
                row = conn.execute(
                    "SELECT * FROM files WHERE path = ?;", (norm,)
                ).fetchone()
                return dict(row) if row is not None else None

    def create_entry(
        self,
        path: str,
        mode: int,
        uid: int,
        gid: int,
        size: int = 0,
        nlink: Optional[int] = None,
        now: Optional[float] = None,
    ) -> int:
        norm = normalize_path(path)
        ts = time.time() if now is None else float(now)
        is_dir = stat.S_ISDIR(mode)
        link_count = (2 if is_dir else 1) if nlink is None else nlink

        with self.lock:
            with self._transaction() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO files (path, mode, uid, gid, size, atime, mtime, ctime, nlink)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (norm, mode, uid, gid, size, ts, ts, ts, link_count),
                )
                entry_id = int(cur.lastrowid)

                if norm != "/":
                    p_path = parent_path(norm)
                    if is_dir:
                        conn.execute(
                            """
                            UPDATE files
                            SET mtime = ?, ctime = ?, nlink = nlink + 1
                            WHERE path = ?;
                            """,
                            (ts, ts, p_path),
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE files
                            SET mtime = ?, ctime = ?
                            WHERE path = ?;
                            """,
                            (ts, ts, p_path),
                        )
                return entry_id

    def list_children(self, dir_path: str) -> List[str]:
        norm = normalize_path(dir_path)
        lower, upper, start = _prefix_bounds(norm)
        op = ">" if norm == "/" else ">="
        with self.lock:
            with self._transaction() as conn:
                rows = conn.execute(
                    f"""
                    SELECT substr(path, ?) AS name
                    FROM files
                    WHERE path {op} ?
                      AND path < ?
                      AND instr(substr(path, ?), '/') = 0
                    ORDER BY name ASC;
                    """,
                    (start, lower, upper, start),
                ).fetchall()
                return [row["name"] for row in rows]

    def has_children(self, dir_path: str) -> bool:
        norm = normalize_path(dir_path)
        lower, upper, _ = _prefix_bounds(norm)
        op = ">" if norm == "/" else ">="
        with self.lock:
            with self._transaction() as conn:
                row = conn.execute(
                    f"""
                    SELECT 1 FROM files
                    WHERE path {op} ? AND path < ?
                    LIMIT 1;
                    """,
                    (lower, upper),
                ).fetchone()
                return row is not None

    def read_data(self, path: str, size: int, offset: int) -> bytes:
        norm = normalize_path(path)
        if size <= 0 or offset < 0:
            return b""

        with self.lock:
            with self._transaction() as conn:
                meta = conn.execute(
                    "SELECT id, size FROM files WHERE path = ?;", (norm,)
                ).fetchone()
                if meta is None:
                    raise FileNotFoundError(norm)

                file_id = int(meta["id"])
                file_size = int(meta["size"])
                if offset >= file_size:
                    return b""

                end = min(offset + size, file_size)
                cs = self.chunk_size
                start_chunk = offset // cs
                end_chunk = (end - 1) // cs

                rows = conn.execute(
                    """
                    SELECT chunk_index, data
                    FROM file_data
                    WHERE file_id = ? AND chunk_index BETWEEN ? AND ?;
                    """,
                    (file_id, start_chunk, end_chunk),
                ).fetchall()
                chunks = {
                    int(r["chunk_index"]): bytes(r["data"]) if r["data"] is not None else b""
                    for r in rows
                }

                parts: List[bytes] = []
                for idx in range(start_chunk, end_chunk + 1):
                    chunk_base = idx * cs
                    c_start = max(0, offset - chunk_base)
                    c_end = min(cs, end - chunk_base)
                    needed = c_end - c_start

                    blob = chunks.get(idx, b"")
                    segment = blob[c_start:c_end]
                    if len(segment) < needed:
                        segment += b"\x00" * (needed - len(segment))
                    parts.append(segment)

                return b"".join(parts)

    def write_data(
        self, path: str, data: bytes, offset: int, now: Optional[float] = None
    ) -> int:
        norm = normalize_path(path)
        ts = time.time() if now is None else float(now)
        payload = bytes(data)

        with self.lock:
            with self._transaction() as conn:
                meta = conn.execute(
                    "SELECT id, size FROM files WHERE path = ?;", (norm,)
                ).fetchone()
                if meta is None:
                    raise FileNotFoundError(norm)

                if not payload:
                    return 0

                file_id = int(meta["id"])
                old_size = int(meta["size"])
                write_end = offset + len(payload)
                cs = self.chunk_size
                start_chunk = offset // cs
                end_chunk = (write_end - 1) // cs

                rows = conn.execute(
                    """
                    SELECT chunk_index, data
                    FROM file_data
                    WHERE file_id = ? AND chunk_index IN (?, ?);
                    """,
                    (file_id, start_chunk, end_chunk),
                ).fetchall()
                existing_chunks = {
                    int(r["chunk_index"]): bytes(r["data"]) if r["data"] is not None else b""
                    for r in rows
                }

                for idx in range(start_chunk, end_chunk + 1):
                    chunk_base = idx * cs
                    c_start = max(0, offset - chunk_base)
                    c_end = min(cs, write_end - chunk_base)
                    data_start = chunk_base + c_start - offset
                    data_end = chunk_base + c_end - offset
                    piece = payload[data_start:data_end]

                    if c_start == 0 and c_end == cs:
                        new_blob = piece
                    else:
                        buf = bytearray(existing_chunks.get(idx, b""))
                        if len(buf) < c_end:
                            buf.extend(b"\x00" * (c_end - len(buf)))
                        buf[c_start:c_end] = piece
                        new_blob = bytes(buf)

                    conn.execute(
                        """
                        INSERT INTO file_data (file_id, chunk_index, data)
                        VALUES (?, ?, ?)
                        ON CONFLICT(file_id, chunk_index)
                        DO UPDATE SET data = excluded.data;
                        """,
                        (file_id, idx, sqlite3.Binary(new_blob)),
                    )

                new_size = max(old_size, write_end)
                conn.execute(
                    """
                    UPDATE files
                    SET size = ?, mtime = ?, ctime = ?
                    WHERE id = ?;
                    """,
                    (new_size, ts, ts, file_id),
                )
                return len(payload)

    def truncate_file(
        self, path: str, length: int, now: Optional[float] = None
    ) -> None:
        norm = normalize_path(path)
        ts = time.time() if now is None else float(now)

        with self.lock:
            with self._transaction() as conn:
                meta = conn.execute(
                    "SELECT id, size FROM files WHERE path = ?;", (norm,)
                ).fetchone()
                if meta is None:
                    raise FileNotFoundError(norm)

                file_id = int(meta["id"])
                old_size = int(meta["size"])

                if length == 0:
                    conn.execute(
                        "DELETE FROM file_data WHERE file_id = ?;", (file_id,)
                    )
                elif length < old_size:
                    cs = self.chunk_size
                    last_chunk = (length - 1) // cs
                    keep = length - last_chunk * cs
                    conn.execute(
                        "DELETE FROM file_data WHERE file_id = ? AND chunk_index > ?;",
                        (file_id, last_chunk),
                    )
                    if keep < cs:
                        row = conn.execute(
                            """
                            SELECT data FROM file_data
                            WHERE file_id = ? AND chunk_index = ?;
                            """,
                            (file_id, last_chunk),
                        ).fetchone()
                        if row is not None and row["data"] is not None:
                            blob = bytes(row["data"])
                            if len(blob) > keep:
                                conn.execute(
                                    """
                                    UPDATE file_data
                                    SET data = ?
                                    WHERE file_id = ? AND chunk_index = ?;
                                    """,
                                    (sqlite3.Binary(blob[:keep]), file_id, last_chunk),
                                )

                conn.execute(
                    """
                    UPDATE files
                    SET size = ?, mtime = ?, ctime = ?
                    WHERE id = ?;
                    """,
                    (length, ts, ts, file_id),
                )

    def delete_entry(self, path: str, now: Optional[float] = None) -> None:
        norm = normalize_path(path)
        ts = time.time() if now is None else float(now)

        with self.lock:
            with self._transaction() as conn:
                row = conn.execute(
                    "SELECT id, mode FROM files WHERE path = ?;", (norm,)
                ).fetchone()
                if row is None:
                    raise FileNotFoundError(norm)

                is_dir = stat.S_ISDIR(int(row["mode"]))
                conn.execute("DELETE FROM files WHERE id = ?;", (int(row["id"]),))

                if norm != "/":
                    p_path = parent_path(norm)
                    if is_dir:
                        conn.execute(
                            """
                            UPDATE files
                            SET mtime = ?, ctime = ?,
                                nlink = CASE WHEN nlink > 1 THEN nlink - 1 ELSE 1 END
                            WHERE path = ?;
                            """,
                            (ts, ts, p_path),
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE files
                            SET mtime = ?, ctime = ?
                            WHERE path = ?;
                            """,
                            (ts, ts, p_path),
                        )

    def update_mode(
        self, path: str, mode: int, now: Optional[float] = None
    ) -> None:
        norm = normalize_path(path)
        ts = time.time() if now is None else float(now)
        with self.lock:
            with self._transaction() as conn:
                conn.execute(
                    "UPDATE files SET mode = ?, ctime = ? WHERE path = ?;",
                    (mode, ts, norm),
                )

    def update_owner(
        self, path: str, uid: int, gid: int, now: Optional[float] = None
    ) -> None:
        norm = normalize_path(path)
        ts = time.time() if now is None else float(now)
        with self.lock:
            with self._transaction() as conn:
                conn.execute(
                    "UPDATE files SET uid = ?, gid = ?, ctime = ? WHERE path = ?;",
                    (uid, gid, ts, norm),
                )

    def update_times(
        self, path: str, atime: float, mtime: float, now: Optional[float] = None
    ) -> None:
        norm = normalize_path(path)
        ts = time.time() if now is None else float(now)
        with self.lock:
            with self._transaction() as conn:
                conn.execute(
                    "UPDATE files SET atime = ?, mtime = ?, ctime = ? WHERE path = ?;",
                    (atime, mtime, ts, norm),
                )

    def rename_entry(
        self, old_path: str, new_path: str, now: Optional[float] = None
    ) -> None:
        old_norm = normalize_path(old_path)
        new_norm = normalize_path(new_path)
        ts = time.time() if now is None else float(now)

        if old_norm == new_norm:
            return

        old_parent = parent_path(old_norm)
        new_parent = parent_path(new_norm)

        with self.lock:
            with self._transaction() as conn:
                old_row = conn.execute(
                    "SELECT id, mode FROM files WHERE path = ?;", (old_norm,)
                ).fetchone()
                if old_row is None:
                    raise FileNotFoundError(old_norm)

                old_id = int(old_row["id"])
                old_is_dir = stat.S_ISDIR(int(old_row["mode"]))

                target_row = conn.execute(
                    "SELECT id, mode FROM files WHERE path = ?;", (new_norm,)
                ).fetchone()
                if target_row is not None:
                    target_id = int(target_row["id"])
                    target_is_dir = stat.S_ISDIR(int(target_row["mode"]))
                    conn.execute("DELETE FROM files WHERE id = ?;", (target_id,))
                    if target_is_dir:
                        conn.execute(
                            """
                            UPDATE files
                            SET nlink = CASE WHEN nlink > 1 THEN nlink - 1 ELSE 1 END
                            WHERE path = ?;
                            """,
                            (new_parent,),
                        )

                conn.execute(
                    "UPDATE files SET path = ?, ctime = ? WHERE id = ?;",
                    (new_norm, ts, old_id),
                )

                if old_is_dir:
                    lower, upper, start = _prefix_bounds(old_norm)
                    conn.execute(
                        """
                        UPDATE files
                        SET path = ? || substr(path, ?), ctime = ?
                        WHERE path >= ? AND path < ?;
                        """,
                        (new_norm, start - 1, ts, lower, upper),
                    )

                if old_parent == new_parent:
                    conn.execute(
                        "UPDATE files SET mtime = ?, ctime = ? WHERE path = ?;",
                        (ts, ts, old_parent),
                    )
                else:
                    if old_is_dir:
                        conn.execute(
                            """
                            UPDATE files
                            SET mtime = ?, ctime = ?,
                                nlink = CASE WHEN nlink > 1 THEN nlink - 1 ELSE 1 END
                            WHERE path = ?;
                            """,
                            (ts, ts, old_parent),
                        )
                        conn.execute(
                            """
                            UPDATE files
                            SET mtime = ?, ctime = ?, nlink = nlink + 1
                            WHERE path = ?;
                            """,
                            (ts, ts, new_parent),
                        )
                    else:
                        conn.execute(
                            "UPDATE files SET mtime = ?, ctime = ? WHERE path IN (?, ?);",
                            (ts, ts, old_parent, new_parent),
                        )

    def get_stats(self) -> Tuple[int, int]:
        with self.lock:
            with self._transaction() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt, COALESCE(SUM(size), 0) AS total FROM files;"
                ).fetchone()
                return int(row["cnt"]), int(row["total"])
