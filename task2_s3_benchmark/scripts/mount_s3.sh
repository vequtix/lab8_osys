#!/usr/bin/env bash
set -euo pipefail

S3_ENDPOINT="${S3_ENDPOINT:-http://minio:9000}"
S3_BUCKET="${S3_BUCKET:-benchmark}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-minioadmin}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-minioadmin123}"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_REGION

S3FS_MOUNT="${S3FS_MOUNT:-/mnt/s3fs}"
GOOFYS_MOUNT="${GOOFYS_MOUNT:-/mnt/goofys}"
GOOFYS_PID=""

cleanup() {
    set +e
    if mountpoint -q "$S3FS_MOUNT" 2>/dev/null; then
        fusermount -u "$S3FS_MOUNT" || fusermount -uz "$S3FS_MOUNT"
    fi
    if mountpoint -q "$GOOFYS_MOUNT" 2>/dev/null; then
        fusermount -u "$GOOFYS_MOUNT" || fusermount -uz "$GOOFYS_MOUNT"
    fi
    if [ -n "$GOOFYS_PID" ] && kill -0 "$GOOFYS_PID" 2>/dev/null; then
        wait "$GOOFYS_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if [ ! -e /dev/fuse ]; then
    echo "ERROR: /dev/fuse not found. Run with --privileged --device /dev/fuse." >&2
    exit 1
fi

echo "Waiting for MinIO at ${S3_ENDPOINT}..."
until curl -sf "${S3_ENDPOINT}/minio/health/live" >/dev/null 2>&1; do
    sleep 1
done

mkdir -p "$S3FS_MOUNT" "$GOOFYS_MOUNT"

echo "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}" > /root/.passwd-s3fs
chmod 600 /root/.passwd-s3fs

echo "Mounting s3fs -> ${S3FS_MOUNT}"
s3fs "${S3_BUCKET}" "$S3FS_MOUNT" \
    -o passwd_file=/root/.passwd-s3fs \
    -o url="${S3_ENDPOINT}" \
    -o use_path_request_style \
    -o allow_other \
    -o parallel_count=15 \
    -o multipart_size=5

echo "Mounting goofys -> ${GOOFYS_MOUNT}"
goofys -f \
    --endpoint "${S3_ENDPOINT}" \
    --region "${AWS_REGION}" \
    -o allow_other \
    "${S3_BUCKET}" "$GOOFYS_MOUNT" >/tmp/goofys.log 2>&1 &
GOOFYS_PID=$!

for _ in $(seq 1 30); do
    if mountpoint -q "$S3FS_MOUNT" 2>/dev/null && mountpoint -q "$GOOFYS_MOUNT" 2>/dev/null; then
        break
    fi
    sleep 0.5
done

if ! mountpoint -q "$S3FS_MOUNT" 2>/dev/null || ! mountpoint -q "$GOOFYS_MOUNT" 2>/dev/null; then
    echo "ERROR: FUSE mount check failed." >&2
    if [ -f /tmp/goofys.log ]; then
        cat /tmp/goofys.log >&2
    fi
    exit 1
fi

echo "Mounts ready: ${S3FS_MOUNT}, ${GOOFYS_MOUNT}"
"$@"
