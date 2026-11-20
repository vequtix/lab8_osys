#!/usr/bin/env bash
set -euo pipefail

S3_ENDPOINT="${S3_ENDPOINT:-http://minio:9000}"
S3_BUCKET="${S3_BUCKET:-hybrid-storage}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-minioadmin}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-minioadmin123}"
MOUNT_POINT="${S3FS_MOUNT:-/mnt/s3}"
CACHE_DIR="${S3FS_CACHE_DIR:-/tmp/s3cache}"

cleanup() {
    set +e
    if grep -qs " ${MOUNT_POINT} fuse" /proc/mounts; then
        fusermount -u "$MOUNT_POINT" || fusermount -uz "$MOUNT_POINT"
    fi
    exit 0
}
trap cleanup SIGTERM SIGINT EXIT

if [ ! -e /dev/fuse ]; then
    echo "ERROR: /dev/fuse device not available." >&2
    exit 1
fi

mkdir -p "$MOUNT_POINT" "$CACHE_DIR"

echo "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}" > /etc/passwd-s3fs
chmod 600 /etc/passwd-s3fs

echo "Waiting for MinIO at ${S3_ENDPOINT}..."
until curl -sf "${S3_ENDPOINT}/minio/health/live" >/dev/null 2>&1; do
    sleep 1
done

mounted=0
for attempt in $(seq 1 10); do
    if s3fs "${S3_BUCKET}" "$MOUNT_POINT" \
        -o passwd_file=/etc/passwd-s3fs \
        -o url="${S3_ENDPOINT}" \
        -o use_path_request_style \
        -o allow_other \
        -o nonempty \
        -o use_cache="${CACHE_DIR}" \
        -o parallel_count=15 \
        -o multipart_size=52 \
        -o stat_cache_expire=5; then
        if grep -qs " ${MOUNT_POINT} fuse" /proc/mounts; then
            mounted=1
            break
        fi
    fi
    echo "s3fs mount attempt ${attempt} failed, retrying..."
    sleep 2
done

if [ "$mounted" -ne 1 ] || ! grep -qs " ${MOUNT_POINT} fuse" /proc/mounts; then
    echo "ERROR: Failed to mount ${S3_BUCKET} onto ${MOUNT_POINT}" >&2
    exit 1
fi

echo "s3fs mounted successfully: bucket=${S3_BUCKET} -> ${MOUNT_POINT}"
tail -f /dev/null &
wait $!
