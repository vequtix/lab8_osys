from __future__ import annotations

import errno
import os
import sqlite3
import stat
import threading
import time
from pathlib import Path

import pytest
from fuse import FuseOSError

import sqlitefs as sqlitefs_mod
from database import CHUNK_SIZE, Database, normalize_path, parent_path
from sqlitefs import SQLiteFS


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_sqlitefs.db")


@pytest.fixture()
def fs(db_path: str) -> SQLiteFS:
    return SQLiteFS(Database(db_path))


def _assert_fuse_errno(exc_info: pytest.ExceptionInfo, expected_errno: int) -> None:
    assert exc_info.value.errno == expected_errno


def test_path_helpers():
    assert normalize_path("") == "/"
    assert normalize_path("/") == "/"
    assert normalize_path("///") == "/"
    assert normalize_path("//foo//bar/") == "/foo/bar"
    assert normalize_path("relative/file.txt") == "/relative/file.txt"
    assert normalize_path("/a/b/../c") == "/a/c"
    assert parent_path("/") == "/"
    assert parent_path("/top") == "/"
    assert parent_path("/a/b/c") == "/a/b"


def test_database_validation_and_low_level_errors(db_path: str):
    with pytest.raises(ValueError):
        Database(db_path, chunk_size=0)

    db = Database(db_path)
    db.create_entry("/", stat.S_IFDIR | 0o755, 0, 0)
    with pytest.raises(sqlite3.IntegrityError):
        db.create_entry("/", stat.S_IFDIR | 0o755, 0, 0)

    with pytest.raises(FileNotFoundError):
        db.read_data("/missing", 10, 0)
    with pytest.raises(FileNotFoundError):
        db.write_data("/missing", b"abc", 0)
    with pytest.raises(FileNotFoundError):
        db.truncate_file("/missing", 10)
    with pytest.raises(FileNotFoundError):
        db.delete_entry("/missing")
    with pytest.raises(FileNotFoundError):
        db.rename_entry("/missing", "/target")

    db.create_entry("/empty.txt", stat.S_IFREG | 0o644, 0, 0)
    assert db.write_data("/empty.txt", b"", 0) == 0
    assert db.read_data("/empty.txt", 0, 0) == b""
    assert db.read_data("/empty.txt", 10, -1) == b""
    db.rename_entry("/empty.txt", "/empty.txt")


def test_foreign_keys_pragma_and_cascade_delete(db_path: str):
    fs = SQLiteFS(Database(db_path))
    fs.create("/cascade.bin", 0o644)
    fs.write("/cascade.bin", b"A" * (CHUNK_SIZE * 3 + 123), 0)

    conn = sqlite3.connect(db_path)
    try:
        chunks_before = conn.execute("SELECT COUNT(*) FROM file_data;").fetchone()[0]
        assert chunks_before == 4
    finally:
        conn.close()

    fs.unlink("/cascade.bin")

    conn = sqlite3.connect(db_path)
    try:
        files_after = conn.execute(
            "SELECT COUNT(*) FROM files WHERE path = '/cascade.bin';"
        ).fetchone()[0]
        chunks_after = conn.execute("SELECT COUNT(*) FROM file_data;").fetchone()[0]
        assert files_after == 0
        assert chunks_after == 0
    finally:
        conn.close()

def test_root_initialized_and_listable(fs: SQLiteFS):
    attr = fs.getattr("/")
    assert stat.S_ISDIR(attr["st_mode"])
    assert stat.S_IMODE(attr["st_mode"]) == 0o755
    assert attr["st_nlink"] == 2
    assert fs.readdir("/", None) == [".", ".."]


def test_create_open_flush_fsync_release_read_write_unlink(fs: SQLiteFS):
    fh = fs.create("/hello.txt", 0o640)
    assert fh > 0
    attr = fs.getattr("/hello.txt")
    assert stat.S_ISREG(attr["st_mode"])
    assert stat.S_IMODE(attr["st_mode"]) == 0o640
    assert attr["st_size"] == 0

    written = fs.write("/hello.txt", b"Hello, SQLiteFS!", 0, fh)
    assert written == 16
    assert fs.flush("/hello.txt", fh) == 0
    assert fs.fsync("/hello.txt", 1, fh) == 0
    assert fs.release("/hello.txt", fh) == 0

    ro_fh = fs.open("/hello.txt", os.O_RDONLY)
    assert fs.read("/hello.txt", 100, 0, ro_fh) == b"Hello, SQLiteFS!"
    assert fs.read("/hello.txt", 5, 7, ro_fh) == b"SQLiteFS!"[:5]
    assert fs.read("/hello.txt", 10, 50, ro_fh) == b""
    fs.release("/hello.txt", ro_fh)

    trunc_fh = fs.open("/hello.txt", os.O_WRONLY | os.O_TRUNC)
    assert fs.getattr("/hello.txt")["st_size"] == 0
    assert fs.read("/hello.txt", 100, 0, trunc_fh) == b""
    fs.release("/hello.txt", trunc_fh)

    assert fs.unlink("/hello.txt") == 0
    with pytest.raises(FuseOSError) as exc:
        fs.getattr("/hello.txt")
    _assert_fuse_errno(exc, errno.ENOENT)

def test_large_multichunk_read_write_and_offsets(db_path: str):
    fs = SQLiteFS(Database(db_path))
    total_size = 64 * 1024 + 517  # > 50 KB (17 chunks of 4096 bytes)
    payload = bytes((i * 31 + 7) % 251 for i in range(total_size))

    fh = fs.create("/large.bin", 0o644)
    assert fs.write("/large.bin", payload, 0, fh) == total_size
    assert fs.getattr("/large.bin")["st_size"] == total_size
    assert fs.read("/large.bin", total_size, 0, fh) == payload

    # Read across multiple chunk boundaries
    cross_offset = CHUNK_SIZE * 3 - 25
    cross_size = CHUNK_SIZE * 2 + 111
    assert fs.read("/large.bin", cross_size, cross_offset, fh) == payload[
        cross_offset : cross_offset + cross_size
    ]

    # Overwrite mid-file across chunk boundary and verify surrounding bytes remain intact
    patch = b"\xAA\xBB\xCC" * 2000  # 6000 bytes spanning chunks
    patch_offset = CHUNK_SIZE * 5 - 300
    assert fs.write("/large.bin", patch, patch_offset, fh) == len(patch)

    expected = bytearray(payload)
    expected[patch_offset : patch_offset + len(patch)] = patch
    assert fs.read("/large.bin", total_size + 100, 0, fh) == bytes(expected)

    # Append at EOF
    tail = b"TAIL_MARKER_12345"
    assert fs.write("/large.bin", tail, total_size, fh) == len(tail)
    assert fs.getattr("/large.bin")["st_size"] == total_size + len(tail)
    assert fs.read("/large.bin", 100, total_size - 10, fh) == bytes(expected[-10:]) + tail
    fs.release("/large.bin", fh)

    # Inspect chunk table directly
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT chunk_index, length(data) FROM file_data ORDER BY chunk_index;"
        ).fetchall()
        assert len(rows) == 17
        assert all(length <= CHUNK_SIZE for _, length in rows)
    finally:
        conn.close()


def test_sparse_write_fills_gaps_with_zeros(fs: SQLiteFS):
    fs.create("/sparse.bin", 0o644)
    fs.write("/sparse.bin", b"HEAD", 0)
    sparse_offset = CHUNK_SIZE * 2 + 100
    fs.write("/sparse.bin", b"TAIL", sparse_offset)

    assert fs.getattr("/sparse.bin")["st_size"] == sparse_offset + 4
    data = fs.read("/sparse.bin", sparse_offset + 4, 0)
    assert data[:4] == b"HEAD"
    assert data[4:sparse_offset] == b"\x00" * (sparse_offset - 4)
    assert data[sparse_offset:] == b"TAIL"
    assert fs.read("/sparse.bin", 512, CHUNK_SIZE + 50) == b"\x00" * 512


def test_directories_and_special_characters_in_names(fs: SQLiteFS):
    assert fs.mkdir("/projects", 0o755) == 0
    assert fs.getattr("/")["st_nlink"] == 3

    assert fs.mkdir("/projects/sub_100%", 0o750) == 0
    assert fs.getattr("/projects")["st_nlink"] == 3

    # Sibling with similar prefix must not leak into /projects listing
    fs.mkdir("/projects_other", 0o755)
    fs.create("/projects_other/ghost.txt", 0o644)
    fs.create("/projects/a_file.txt", 0o644)
    fs.create("/projects/b%file.txt", 0o644)

    assert fs.readdir("/projects", None) == [
        ".",
        "..",
        "a_file.txt",
        "b%file.txt",
        "sub_100%",
    ]

    fs.rmdir("/projects/sub_100%")
    assert fs.getattr("/projects")["st_nlink"] == 2


def test_chmod_chown_utimens_and_statfs(fs: SQLiteFS):
    fs.create("/meta.txt", 0o644)
    fs.write("/meta.txt", b"X" * (CHUNK_SIZE * 2), 0)

    assert fs.chmod("/meta.txt", 0o750) == 0
    attr = fs.getattr("/meta.txt")
    assert stat.S_ISREG(attr["st_mode"])
    assert stat.S_IMODE(attr["st_mode"]) == 0o750

    assert fs.chown("/meta.txt", 1001, -1) == 0
    attr = fs.getattr("/meta.txt")
    assert attr["st_uid"] == 1001
    assert attr["st_gid"] == os.getgid()

    assert fs.chown("/meta.txt", -1, 2002) == 0
    attr = fs.getattr("/meta.txt")
    assert attr["st_uid"] == 1001
    assert attr["st_gid"] == 2002

    assert fs.utimens("/meta.txt", (12345.5, 67890.25)) == 0
    attr = fs.getattr("/meta.txt")
    assert attr["st_atime"] == pytest.approx(12345.5)
    assert attr["st_mtime"] == pytest.approx(67890.25)

    before_now = time.time()
    assert fs.utimens("/meta.txt", None) == 0
    attr = fs.getattr("/meta.txt")
    assert attr["st_atime"] >= before_now
    assert attr["st_mtime"] >= before_now

    vfs = fs.statfs("/")
    assert vfs["f_bsize"] == CHUNK_SIZE
    assert vfs["f_blocks"] - vfs["f_bfree"] == 2
    assert vfs["f_files"] - vfs["f_ffree"] == 2  # '/' and '/meta.txt'


def test_truncate_shrink_grow_and_zero_out(db_path: str):
    fs = SQLiteFS(Database(db_path))
    fs.create("/trunc.bin", 0o644)
    data = bytes(range(256)) * 40  # 10240 bytes (3 chunks)
    fs.write("/trunc.bin", data, 0)

    # Shrink mid-chunk 1 (offset 5000) and then re-extend to 7000
    assert fs.truncate("/trunc.bin", 5000) == 0
    assert fs.getattr("/trunc.bin")["st_size"] == 5000
    assert fs.read("/trunc.bin", 10000, 0) == data[:5000]

    assert fs.truncate("/trunc.bin", 7000) == 0
    assert fs.getattr("/trunc.bin")["st_size"] == 7000
    extended = fs.read("/trunc.bin", 10000, 0)
    assert extended[:5000] == data[:5000]
    assert extended[5000:] == b"\x00" * 2000

    # Truncate to exact same size (updates timestamps without corrupting data)
    assert fs.truncate("/trunc.bin", 7000) == 0
    assert fs.read("/trunc.bin", 7000, 0) == extended

    # Truncate to 0 removes all chunks
    assert fs.truncate("/trunc.bin", 0) == 0
    assert fs.getattr("/trunc.bin")["st_size"] == 0
    conn = sqlite3.connect(db_path)
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM file_data;").fetchone()[0]
        assert cnt == 0
    finally:
        conn.close()

def test_rename_files_and_overwrite(fs: SQLiteFS):
    fs.mkdir("/dir_a", 0o755)
    fs.mkdir("/dir_b", 0o755)
    fs.create("/dir_a/one.txt", 0o644)
    fs.write("/dir_a/one.txt", b"new-content", 0)

    fs.create("/dir_b/two.txt", 0o644)
    fs.write("/dir_b/two.txt", b"old-content-to-discard", 0)

    assert fs.rename("/dir_a/one.txt", "/dir_b/two.txt") == 0
    assert fs.read("/dir_b/two.txt", 100, 0) == b"new-content"
    with pytest.raises(FuseOSError) as exc:
        fs.getattr("/dir_a/one.txt")
    _assert_fuse_errno(exc, errno.ENOENT)
    assert fs.rename("/dir_b/two.txt", "/dir_b/two.txt") == 0


def test_rename_directory_recursive_and_prefix_isolation(fs: SQLiteFS):
    fs.mkdir("/src", 0o755)
    fs.mkdir("/src/nested", 0o755)
    fs.mkdir("/src_sibling", 0o755)
    fs.mkdir("/dst_parent", 0o755)

    big_payload = b"Z" * 55000
    fs.create("/src/root.txt", 0o644)
    fs.write("/src/root.txt", b"root-file", 0)
    fs.create("/src/nested/big.bin", 0o644)
    fs.write("/src/nested/big.bin", big_payload, 0)
    fs.create("/src_sibling/keep.txt", 0o644)
    fs.write("/src_sibling/keep.txt", b"untouched", 0)

    assert fs.rename("/src", "/dst_parent/moved") == 0

    assert fs.getattr("/")["st_nlink"] == 4  # '.', '..', 'src_sibling', 'dst_parent'
    assert fs.getattr("/dst_parent")["st_nlink"] == 3
    assert fs.read("/dst_parent/moved/root.txt", 100, 0) == b"root-file"
    assert fs.read("/dst_parent/moved/nested/big.bin", len(big_payload), 0) == big_payload
    assert fs.readdir("/dst_parent/moved/nested", None) == [".", "..", "big.bin"]
    assert fs.read("/src_sibling/keep.txt", 100, 0) == b"untouched"

    for old_path in ("/src", "/src/root.txt", "/src/nested", "/src/nested/big.bin"):
        with pytest.raises(FuseOSError) as exc:
            fs.getattr(old_path)
        _assert_fuse_errno(exc, errno.ENOENT)

    # Replacing an empty directory works atomically
    fs.mkdir("/empty_target", 0o755)
    assert fs.rename("/dst_parent/moved", "/empty_target") == 0
    assert fs.read("/empty_target/nested/big.bin", len(big_payload), 0) == big_payload

def test_error_conditions(fs: SQLiteFS):
    fs.mkdir("/folder", 0o755)
    fs.create("/folder/file.txt", 0o644)
    fs.create("/regular.txt", 0o644)

    # ENOENT
    for op in (
        lambda: fs.getattr("/nope"),
        lambda: fs.readdir("/nope", None),
        lambda: fs.open("/nope", os.O_RDONLY),
        lambda: fs.read("/nope", 10, 0),
        lambda: fs.write("/nope", b"x", 0),
        lambda: fs.unlink("/nope"),
        lambda: fs.rmdir("/nope"),
        lambda: fs.chmod("/nope", 0o644),
        lambda: fs.chown("/nope", 0, 0),
        lambda: fs.truncate("/nope", 0),
        lambda: fs.utimens("/nope"),
        lambda: fs.rename("/nope", "/other"),
        lambda: fs.rename("/regular.txt", "/missing_parent/file"),
        lambda: fs.create("/missing_parent/file", 0o644),
        lambda: fs.mkdir("/missing_parent/sub", 0o755),
    ):
        with pytest.raises(FuseOSError) as exc:
            op()
        _assert_fuse_errno(exc, errno.ENOENT)

    # EEXIST
    for op in (
        lambda: fs.create("/regular.txt", 0o644),
        lambda: fs.mkdir("/folder", 0o755),
    ):
        with pytest.raises(FuseOSError) as exc:
            op()
        _assert_fuse_errno(exc, errno.EEXIST)

    # ENOTEMPTY
    fs.mkdir("/nonempty_target", 0o755)
    fs.create("/nonempty_target/inner.txt", 0o644)
    for op in (
        lambda: fs.rmdir("/folder"),
        lambda: fs.rename("/folder", "/nonempty_target"),
    ):
        with pytest.raises(FuseOSError) as exc:
            op()
        _assert_fuse_errno(exc, errno.ENOTEMPTY)

    # EISDIR
    for op in (
        lambda: fs.open("/folder", os.O_RDONLY),
        lambda: fs.read("/folder", 10, 0),
        lambda: fs.write("/folder", b"x", 0),
        lambda: fs.unlink("/folder"),
        lambda: fs.truncate("/folder", 0),
        lambda: fs.rename("/regular.txt", "/folder"),
    ):
        with pytest.raises(FuseOSError) as exc:
            op()
        _assert_fuse_errno(exc, errno.EISDIR)

    # ENOTDIR
    for op in (
        lambda: fs.readdir("/regular.txt", None),
        lambda: fs.rmdir("/regular.txt"),
        lambda: fs.create("/regular.txt/child", 0o644),
        lambda: fs.mkdir("/regular.txt/child", 0o755),
        lambda: fs.rename("/regular.txt", "/regular.txt/child"),
        lambda: fs.rename("/folder", "/regular.txt"),
    ):
        with pytest.raises(FuseOSError) as exc:
            op()
        _assert_fuse_errno(exc, errno.ENOTDIR)

    # EINVAL
    for op in (
        lambda: fs.read("/regular.txt", 10, -1),
        lambda: fs.read("/regular.txt", -1, 0),
        lambda: fs.write("/regular.txt", b"x", -1),
        lambda: fs.truncate("/regular.txt", -5),
        lambda: fs.rename("/folder", "/folder/inside"),
    ):
        with pytest.raises(FuseOSError) as exc:
            op()
        _assert_fuse_errno(exc, errno.EINVAL)

    # EBUSY
    for op in (
        lambda: fs.rmdir("/"),
        lambda: fs.rename("/", "/newroot"),
    ):
        with pytest.raises(FuseOSError) as exc:
            op()
        _assert_fuse_errno(exc, errno.EBUSY)

def test_persistence_across_reinstantiation(db_path: str):
    payload = b"Persist-" * 8000  # 64000 bytes (> 50 KB)
    fs1 = SQLiteFS(Database(db_path))
    fs1.mkdir("/persist", 0o750)
    fs1.create("/persist/data.bin", 0o640)
    fs1.write("/persist/data.bin", payload, 0)
    fs1.utimens("/persist/data.bin", (1000.0, 2000.0))

    # Recreate Database and SQLiteFS from the same SQLite file
    fs2 = SQLiteFS(Database(db_path))
    assert fs2.readdir("/", None) == [".", "..", "persist"]
    assert fs2.readdir("/persist", None) == [".", "..", "data.bin"]

    attr = fs2.getattr("/persist/data.bin")
    assert stat.S_IMODE(attr["st_mode"]) == 0o640
    assert attr["st_size"] == len(payload)
    assert attr["st_mtime"] == pytest.approx(2000.0)
    assert fs2.read("/persist/data.bin", len(payload), 0) == payload


def test_concurrent_thread_safety(fs: SQLiteFS):
    errors: list[Exception] = []

    def worker(idx: int) -> None:
        try:
            path = f"/thread_{idx}.bin"
            data = bytes([idx % 256]) * (CHUNK_SIZE * 3 + idx * 17)
            fh = fs.create(path, 0o644)
            fs.write(path, data, 0, fh)
            assert fs.read(path, len(data), 0, fh) == data
            fs.chmod(path, 0o600)
            fs.release(path, fh)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(fs.readdir("/", None)) == 14  # '.', '..' + 12 files


def test_fuse_context_and_cli_entrypoint(
    monkeypatch: pytest.MonkeyPatch, db_path: str, tmp_path: Path
):
    monkeypatch.setattr(sqlitefs_mod, "fuse_get_context", lambda: (1234, 5678, 99))
    fs = SQLiteFS(Database(db_path))
    fs.create("/from_ctx.txt", 0o644)
    attr = fs.getattr("/from_ctx.txt")
    assert attr["st_uid"] == 1234
    assert attr["st_gid"] == 5678

    captured = {}

    def fake_fuse(operations, mountpoint, **kwargs):
        captured["operations"] = operations
        captured["mountpoint"] = mountpoint
        captured["kwargs"] = kwargs

    monkeypatch.setattr(sqlitefs_mod, "FUSE", fake_fuse)
    mnt = str(tmp_path / "mnt")
    sqlitefs_mod.main([mnt, "--database", db_path, "--foreground", "--allow-other"])

    assert isinstance(captured["operations"], SQLiteFS)
    assert captured["mountpoint"] == mnt
    assert captured["kwargs"]["foreground"] is True
    assert captured["kwargs"]["allow_other"] is True
    assert captured["kwargs"]["nothreads"] is False
