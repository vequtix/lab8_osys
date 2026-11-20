#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import os
import stat
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

from fuse import FUSE, FuseOSError, Operations, fuse_get_context

from database import CHUNK_SIZE, Database, normalize_path, parent_path


class SQLiteFS(Operations):
    def __init__(self, database: Database) -> None:
        self.db = database
        self._fh_lock = threading.Lock()
        self._fh_counter = 0
        self._open_files: Dict[int, str] = {}
        self._ensure_root()

    def _ensure_root(self) -> None:
        if self.db.get_entry("/") is None:
            self.db.create_entry(
                "/",
                mode=stat.S_IFDIR | 0o755,
                uid=os.getuid(),
                gid=os.getgid(),
                size=0,
                nlink=2,
            )

    def _get_caller_ids(self) -> Tuple[int, int]:
        try:
            uid, gid, pid = fuse_get_context()
            if pid > 0:
                return int(uid), int(gid)
        except (ValueError, OSError, RuntimeError):
            pass
        return os.getuid(), os.getgid()

    def _alloc_fh(self, path: str) -> int:
        with self._fh_lock:
            self._fh_counter += 1
            fh = self._fh_counter
            self._open_files[fh] = path
            return fh

    def _require_entry(self, path: str) -> Dict:
        norm = normalize_path(path)
        entry = self.db.get_entry(norm)
        if entry is None:
            raise FuseOSError(errno.ENOENT)
        return entry

    def getattr(self, path: str, fh: Optional[int] = None) -> Dict:
        entry = self._require_entry(path)
        size = int(entry["size"])
        return {
            "st_mode": int(entry["mode"]),
            "st_nlink": int(entry["nlink"]),
            "st_uid": int(entry["uid"]),
            "st_gid": int(entry["gid"]),
            "st_size": size,
            "st_atime": float(entry["atime"]),
            "st_mtime": float(entry["mtime"]),
            "st_ctime": float(entry["ctime"]),
            "st_blksize": CHUNK_SIZE,
            "st_blocks": (size + 511) // 512,
        }

    def readdir(self, path: str, fh: Optional[int] = None) -> List[str]:
        norm = normalize_path(path)
        entry = self._require_entry(norm)
        if not stat.S_ISDIR(int(entry["mode"])):
            raise FuseOSError(errno.ENOTDIR)
        return [".", ".."] + self.db.list_children(norm)

    def create(self, path: str, mode: int, fi=None) -> int:
        norm = normalize_path(path)
        if self.db.get_entry(norm) is not None:
            raise FuseOSError(errno.EEXIST)

        p_entry = self.db.get_entry(parent_path(norm))
        if p_entry is None:
            raise FuseOSError(errno.ENOENT)
        if not stat.S_ISDIR(int(p_entry["mode"])):
            raise FuseOSError(errno.ENOTDIR)

        uid, gid = self._get_caller_ids()
        self.db.create_entry(
            norm,
            mode=stat.S_IFREG | (mode & 0o7777),
            uid=uid,
            gid=gid,
            size=0,
            nlink=1,
        )
        return self._alloc_fh(norm)

    def open(self, path: str, flags: int) -> int:
        norm = normalize_path(path)
        entry = self._require_entry(norm)
        if stat.S_ISDIR(int(entry["mode"])):
            raise FuseOSError(errno.EISDIR)

        if (flags & os.O_TRUNC) and (flags & (os.O_WRONLY | os.O_RDWR)):
            self.db.truncate_file(norm, 0)

        return self._alloc_fh(norm)

    def release(self, path: str, fh: int) -> int:
        with self._fh_lock:
            self._open_files.pop(fh, None)
        return 0

    def flush(self, path: str, fh: int) -> int:
        self._require_entry(path)
        return 0

    def fsync(self, path: str, datasync: int, fh: int) -> int:
        """Synchronize file state."""
        self._require_entry(path)
        return 0

    def read(
        self, path: str, size: int, offset: int, fh: Optional[int] = None
    ) -> bytes:
        norm = normalize_path(path)
        entry = self._require_entry(norm)
        if stat.S_ISDIR(int(entry["mode"])):
            raise FuseOSError(errno.EISDIR)
        if offset < 0 or size < 0:
            raise FuseOSError(errno.EINVAL)
        return self.db.read_data(norm, size, offset)

    def write(
        self, path: str, data: bytes, offset: int, fh: Optional[int] = None
    ) -> int:
        norm = normalize_path(path)
        entry = self._require_entry(norm)
        if stat.S_ISDIR(int(entry["mode"])):
            raise FuseOSError(errno.EISDIR)
        if offset < 0:
            raise FuseOSError(errno.EINVAL)
        return self.db.write_data(norm, bytes(data), offset)

    def unlink(self, path: str) -> int:
        """Remove a regular file."""
        norm = normalize_path(path)
        entry = self._require_entry(norm)
        if stat.S_ISDIR(int(entry["mode"])):
            raise FuseOSError(errno.EISDIR)
        self.db.delete_entry(norm)
        return 0

    def mkdir(self, path: str, mode: int) -> int:
        """Create a directory."""
        norm = normalize_path(path)
        if self.db.get_entry(norm) is not None:
            raise FuseOSError(errno.EEXIST)

        p_entry = self.db.get_entry(parent_path(norm))
        if p_entry is None:
            raise FuseOSError(errno.ENOENT)
        if not stat.S_ISDIR(int(p_entry["mode"])):
            raise FuseOSError(errno.ENOTDIR)

        uid, gid = self._get_caller_ids()
        self.db.create_entry(
            norm,
            mode=stat.S_IFDIR | (mode & 0o7777),
            uid=uid,
            gid=gid,
            size=0,
            nlink=2,
        )
        return 0

    def rmdir(self, path: str) -> int:
        """Remove an empty directory."""
        norm = normalize_path(path)
        if norm == "/":
            raise FuseOSError(errno.EBUSY)

        entry = self._require_entry(norm)
        if not stat.S_ISDIR(int(entry["mode"])):
            raise FuseOSError(errno.ENOTDIR)
        if self.db.has_children(norm):
            raise FuseOSError(errno.ENOTEMPTY)

        self.db.delete_entry(norm)
        return 0

    def chmod(self, path: str, mode: int) -> int:
        """Change permission bits while preserving file type bits."""
        norm = normalize_path(path)
        entry = self._require_entry(norm)
        new_mode = stat.S_IFMT(int(entry["mode"])) | (mode & 0o7777)
        self.db.update_mode(norm, new_mode)
        return 0

    def chown(self, path: str, uid: int, gid: int) -> int:
        """Change owner uid and/or gid (-1 leaves an ID unchanged)."""
        norm = normalize_path(path)
        entry = self._require_entry(norm)
        new_uid = int(entry["uid"]) if uid == -1 else int(uid)
        new_gid = int(entry["gid"]) if gid == -1 else int(gid)
        self.db.update_owner(norm, new_uid, new_gid)
        return 0

    def rename(self, old: str, new: str) -> int:
        """Rename or move a file or directory tree recursively."""
        old_norm = normalize_path(old)
        new_norm = normalize_path(new)

        old_entry = self._require_entry(old_norm)
        if old_norm == new_norm:
            return 0
        if old_norm == "/" or new_norm == "/":
            raise FuseOSError(errno.EBUSY)

        new_parent = self.db.get_entry(parent_path(new_norm))
        if new_parent is None:
            raise FuseOSError(errno.ENOENT)
        if not stat.S_ISDIR(int(new_parent["mode"])):
            raise FuseOSError(errno.ENOTDIR)

        old_is_dir = stat.S_ISDIR(int(old_entry["mode"]))
        if old_is_dir and new_norm.startswith(f"{old_norm}/"):
            raise FuseOSError(errno.EINVAL)

        target_entry = self.db.get_entry(new_norm)
        if target_entry is not None:
            target_is_dir = stat.S_ISDIR(int(target_entry["mode"]))
            if old_is_dir and not target_is_dir:
                raise FuseOSError(errno.ENOTDIR)
            if not old_is_dir and target_is_dir:
                raise FuseOSError(errno.EISDIR)
            if old_is_dir and target_is_dir and self.db.has_children(new_norm):
                raise FuseOSError(errno.ENOTEMPTY)

        self.db.rename_entry(old_norm, new_norm)
        return 0

    def truncate(self, path: str, length: int, fh: Optional[int] = None) -> int:
        """Truncate or zero-extend a regular file to `length` bytes."""
        norm = normalize_path(path)
        entry = self._require_entry(norm)
        if stat.S_ISDIR(int(entry["mode"])):
            raise FuseOSError(errno.EISDIR)
        if length < 0:
            raise FuseOSError(errno.EINVAL)
        self.db.truncate_file(norm, length)
        return 0

    def utimens(
        self, path: str, times: Optional[Tuple[float, float]] = None
    ) -> int:
        """Update access and modification timestamps."""
        norm = normalize_path(path)
        self._require_entry(norm)
        if times is None:
            now = time.time()
            atime, mtime = now, now
        else:
            atime, mtime = float(times[0]), float(times[1])
        self.db.update_times(norm, atime, mtime)
        return 0

    def statfs(self, path: str) -> Dict[str, int]:
        """Return virtual filesystem capacity and inode statistics."""
        self._require_entry(path)
        total_blocks = 262144  # 1 GiB in 4096-byte blocks
        total_files = 100000
        file_count, total_bytes = self.db.get_stats()
        used_blocks = (total_bytes + CHUNK_SIZE - 1) // CHUNK_SIZE
        free_blocks = max(0, total_blocks - used_blocks)
        free_files = max(0, total_files - file_count)
        return {
            "f_bsize": CHUNK_SIZE,
            "f_frsize": CHUNK_SIZE,
            "f_blocks": total_blocks,
            "f_bfree": free_blocks,
            "f_bavail": free_blocks,
            "f_files": total_files,
            "f_ffree": free_files,
            "f_favail": free_files,
            "f_namemax": 255,
        }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for mounting SQLiteFS."""
    parser = argparse.ArgumentParser(
        description="Mount a SQLite-backed FUSE filesystem."
    )
    parser.add_argument("mountpoint", help="Directory where the FS will be mounted.")
    parser.add_argument(
        "--database",
        default="sqlitefs.db",
        help="Path to the SQLite database file (default: sqlitefs.db).",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run FUSE daemon in the foreground.",
    )
    parser.add_argument(
        "--allow-other",
        action="store_true",
        help="Allow other system users to access the mount.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable libfuse debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    db = Database(args.database)
    fs = SQLiteFS(db)
    FUSE(
        fs,
        args.mountpoint,
        nothreads=False,
        foreground=args.foreground,
        allow_other=args.allow_other,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
