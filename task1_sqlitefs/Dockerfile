FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    fuse \
    libfuse-dev \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && if [ -f /etc/fuse.conf ]; then sed -i 's/^#user_allow_other/user_allow_other/' /etc/fuse.conf; fi

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY database.py sqlitefs.py test_sqlitefs.py run_demo.sh ./
RUN chmod +x /app/sqlitefs.py /app/run_demo.sh \
    && mkdir -p /mnt/sqlitefs

CMD ["pytest", "--cov=.", "--cov-report=term-missing", "-v"]
