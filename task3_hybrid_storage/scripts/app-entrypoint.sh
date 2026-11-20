#!/usr/bin/env bash
set -euo pipefail

S3_ENDPOINT="${S3_ENDPOINT:-http://minio:9000}"
S3_BUCKET="${S3_BUCKET:-hybrid-storage}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-minioadmin}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-minioadmin123}"
HOT_PATH="${HOT_PATH:-/data/hot}"
WARM_PATH="${WARM_PATH:-/data/warm}"
COLD_PATH="${COLD_PATH:-/data/cold}"
CACHE_DIR="${S3FS_CACHE_DIR:-/tmp/s3cache}"

mkdir -p "$HOT_PATH" "$WARM_PATH" "$COLD_PATH" "$CACHE_DIR"

mounted_here=0
cleanup() {
    set +e
    if [ "$mounted_here" -eq 1 ] && grep -qs " ${WARM_PATH} fuse" /proc/mounts; then
        fusermount -u "$WARM_PATH" || fusermount -uz "$WARM_PATH"
    fi
}
trap cleanup EXIT

if [ -e /dev/fuse ] && ! grep -qs " ${WARM_PATH} fuse" /proc/mounts; then
    echo "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}" > /etc/passwd-s3fs
    chmod 600 /etc/passwd-s3fs

    until curl -sf "${S3_ENDPOINT}/minio/health/live" >/dev/null 2>&1; do
        sleep 1
    done

    s3fs "${S3_BUCKET}" "$WARM_PATH" \
        -o passwd_file=/etc/passwd-s3fs \
        -o url="${S3_ENDPOINT}" \
        -o use_path_request_style \
        -o allow_other \
        -o nonempty \
        -o use_cache="${CACHE_DIR}" \
        -o parallel_count=15 \
        -o multipart_size=52 \
        -o stat_cache_expire=5

    if ! grep -qs " ${WARM_PATH} fuse" /proc/mounts; then
        echo "ERROR: s3fs failed to mount ${S3_BUCKET} onto ${WARM_PATH}" >&2
        exit 1
    fi
    mounted_here=1
fi

if [ "$mounted_here" -eq 1 ]; then
    "$@"
    exit $?
else
    exec "$@"
fi
