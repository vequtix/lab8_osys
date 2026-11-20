#!/usr/bin/env bash
set -euo pipefail

MOUNT_POINT="${MOUNT_POINT:-/mnt/sqlitefs}"
DB_PATH="${DB_PATH:-/tmp/demo_sqlitefs.db}"
FUSE_PID=""

cleanup() {
    if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        fusermount -u "$MOUNT_POINT" || fusermount -uz "$MOUNT_POINT" || true
    fi
    if [ -n "$FUSE_PID" ] && kill -0 "$FUSE_PID" 2>/dev/null; then
        wait "$FUSE_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if [ ! -e /dev/fuse ]; then
    echo "ERROR: /dev/fuse not found. Run Docker with --privileged --device /dev/fuse" >&2
    exit 1
fi

rm -f "$DB_PATH"
mkdir -p "$MOUNT_POINT"

start_fs() {
    python3 /app/sqlitefs.py "$MOUNT_POINT" --database "$DB_PATH" --foreground &
    FUSE_PID=$!
    for _ in $(seq 1 30); do
        if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
            return 0
        fi
        sleep 0.2
    done
    echo "ERROR: SQLiteFS failed to mount on $MOUNT_POINT" >&2
    exit 1
}

stop_fs() {
    fusermount -u "$MOUNT_POINT"
    wait "$FUSE_PID" || true
    FUSE_PID=""
}

echo "1. Mounting SQLiteFS"
start_fs

echo "2. Testing basic file & directory operations"
echo "Hello, SQLiteFS!" > "$MOUNT_POINT/hello.txt"
cat "$MOUNT_POINT/hello.txt"
mkdir -p "$MOUNT_POINT/projects/nested"
echo "nested data" > "$MOUNT_POINT/projects/nested/note.txt"
ls -la "$MOUNT_POINT"

echo "3. Testing > 50 KB chunked binary I/O"
dd if=/dev/urandom of=/tmp/src_64k.bin bs=1024 count=64 status=none
cp /tmp/src_64k.bin "$MOUNT_POINT/projects/nested/blob_64k.bin"
SRC_SHA=$(sha256sum /tmp/src_64k.bin | awk '{print $1}')
DST_SHA=$(sha256sum "$MOUNT_POINT/projects/nested/blob_64k.bin" | awk '{print $1}')
test "$SRC_SHA" = "$DST_SHA"
echo "SHA-256 verified: $DST_SHA"

echo "4. Testing metadata, truncate, and recursive rename"
chmod 0750 "$MOUNT_POINT/hello.txt"
truncate -s 5 "$MOUNT_POINT/hello.txt"
test "$(cat "$MOUNT_POINT/hello.txt")" = "Hello"
touch "$MOUNT_POINT/hello.txt"
mv "$MOUNT_POINT/projects" "$MOUNT_POINT/projects_moved"
ls -la "$MOUNT_POINT/projects_moved/nested"
df -h "$MOUNT_POINT"

echo "5. Testing persistence across unmount / remount"
stop_fs
start_fs
REMOUNT_SHA=$(sha256sum "$MOUNT_POINT/projects_moved/nested/blob_64k.bin" | awk '{print $1}')
test "$SRC_SHA" = "$REMOUNT_SHA"
test "$(cat "$MOUNT_POINT/projects_moved/nested/note.txt")" = "nested data"
echo "Persistence verified after remount."

echo "6. Cleanup inside FS and unmount"
rm "$MOUNT_POINT/hello.txt" "$MOUNT_POINT/projects_moved/nested/note.txt" "$MOUNT_POINT/projects_moved/nested/blob_64k.bin"
rmdir "$MOUNT_POINT/projects_moved/nested" "$MOUNT_POINT/projects_moved"
stop_fs
rm -f /tmp/src_64k.bin "$DB_PATH"

echo "SQLiteFS live /dev/fuse demo PASSED"
