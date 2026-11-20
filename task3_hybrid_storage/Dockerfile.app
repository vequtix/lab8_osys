FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    s3fs \
    fuse \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && if [ -f /etc/fuse.conf ]; then sed -i 's/^#user_allow_other/user_allow_other/' /etc/fuse.conf; fi \
    && mkdir -p /data/hot /data/warm /data/cold /tmp/s3cache

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scripts/app-entrypoint.sh ./scripts/app-entrypoint.sh
RUN chmod +x /app/scripts/app-entrypoint.sh

ENTRYPOINT ["/app/scripts/app-entrypoint.sh"]
CMD ["python3", "-m", "app.cli"]
