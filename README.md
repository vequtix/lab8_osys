# Лабораторная работа: FUSE файловые системы и гибридное хранилище данных

Монорепозиторий лабораторной работы из трёх взаимосвязанных заданий по методическому пособию [FUSE_Lab_Guide.docx](./FUSE_Lab_Guide.docx).

## Окружение и совместимость с macOS Apple Silicon (ARM64)

- **Нет привязки к Linux-хосту:** все проекты не содержат хардкода локальных путей хоста и запускаются в контейнерах Docker с `/dev/fuse` через относительные тома и именованные Docker-тома.
- **Задания 1 и 3:** собираются и работают нативно на **`linux/arm64`** (`ubuntu:22.04`, `fusepy`, `s3fs-fuse`, `pgsty/minio`, `pgsty/mc`).
- **Задание 2 (`bench`):** запускается с `platform: linux/amd64` (через Rosetta 2 в Docker Desktop на Apple Silicon), чтобы официальный бинарник `goofys v0.24.0` работал в одном окружении с `s3fs-fuse` и `boto3`, а сервер MinIO и `mc` работают нативно на `linux/arm64`.
- **Образы MinIO / mc:** в связи с удалением официальных репозиториев `minio/minio` и `minio/mc` из Docker Hub используются мультиархитектурные drop-in образы `pgsty/minio:latest` и `pgsty/mc:latest`.

---

## Навигация и статус заданий

| Задание | Директория | Описание и готовность | Ключевые файлы |
| :--- | :--- | :--- | :--- |
| **Задание 1** | [task1_sqlitefs/](./task1_sqlitefs/) | **Готово** — FUSE ФС на базе SQLite (чанки 4096 B, все базовые и доп. операции, 16 тестов, покрытие **99%**, демо с `/dev/fuse`) | [`database.py`](./task1_sqlitefs/database.py), [`sqlitefs.py`](./task1_sqlitefs/sqlitefs.py), [`test_sqlitefs.py`](./task1_sqlitefs/test_sqlitefs.py), [`run_demo.sh`](./task1_sqlitefs/run_demo.sh), [`Dockerfile`](./task1_sqlitefs/Dockerfile), [`docker-compose.yml`](./task1_sqlitefs/docker-compose.yml), [`README.md`](./task1_sqlitefs/README.md) |
| **Задание 2** | [task2_s3_benchmark/](./task2_s3_benchmark/) | **Готово** — Benchmark `s3fs` vs `goofys` vs `boto3` по 5 нагрузкам, полный прогон (`0` ошибок), графики и отчёт | [`benchmark/`](./task2_s3_benchmark/benchmark/), [`scripts/mount_s3.sh`](./task2_s3_benchmark/scripts/mount_s3.sh), [`Dockerfile.bench`](./task2_s3_benchmark/Dockerfile.bench), [`docker-compose.yml`](./task2_s3_benchmark/docker-compose.yml), [`results/results.json`](./task2_s3_benchmark/results/results.json), [`results/*.png`](./task2_s3_benchmark/results/), [`REPORT.md`](./task2_s3_benchmark/REPORT.md) |
| **Задание 3** | [task3_hybrid_storage/](./task3_hybrid_storage/) | **Готово** — Гибридное хранилище TechData Solutions (HOT/WARM/COLD, MinIO + `s3fs`, MD5, `metadata.json`, TCO для 500 TB) | [`app/hybrid_storage.py`](./task3_hybrid_storage/app/hybrid_storage.py), [`app/cli.py`](./task3_hybrid_storage/app/cli.py), [`scripts/s3fs-entrypoint.sh`](./task3_hybrid_storage/scripts/s3fs-entrypoint.sh), [`scripts/app-entrypoint.sh`](./task3_hybrid_storage/scripts/app-entrypoint.sh), [`Dockerfile.s3fs`](./task3_hybrid_storage/Dockerfile.s3fs), [`Dockerfile.app`](./task3_hybrid_storage/Dockerfile.app), [`docker-compose.yml`](./task3_hybrid_storage/docker-compose.yml), [`ARCHITECTURE.md`](./task3_hybrid_storage/ARCHITECTURE.md) |

---

## Шпаргалка команд для демонстрации преподавателю

### Задание 1 — SQLiteFS (`task1_sqlitefs/`)

```bash
cd task1_sqlitefs

# 1. Сборка и запуск всех 16 unit-тестов с проверкой покрытия (одной командой)
docker compose run --rm --build sqlitefs

# 2. Автоматическая живая демонстрация с реальным монтированием /dev/fuse:
#    создание файлов/папок, 64 KB бинарник + sha256sum, chmod/truncate/touch,
#    рекурсивный mv, df -h, проверка персистентности после перемонтирования
docker compose run --rm sqlitefs ./run_demo.sh

# 3. (Опционально) Ручная интерактивная проверка в контейнере
docker compose run --rm --entrypoint bash sqlitefs
python3 /app/sqlitefs.py /mnt/sqlitefs --database /tmp/demo.db &
sleep 1
echo "Hello, FUSE!" > /mnt/sqlitefs/test.txt
cat /mnt/sqlitefs/test.txt
mkdir -p /mnt/sqlitefs/dir/sub
mv /mnt/sqlitefs/dir /mnt/sqlitefs/dir_renamed
ls -la /mnt/sqlitefs/dir_renamed
fusermount -u /mnt/sqlitefs
exit
```

---

### Задание 2 — Benchmark S3 (`task2_s3_benchmark/`)

```bash
cd task2_s3_benchmark

# 1. Быстрый прогон для защиты (в 10 раз меньше итераций, ~15-20 сек):
#    поднимает MinIO, создаёт бакет benchmark, монтирует /mnt/s3fs и /mnt/goofys,
#    выполняет все 5 нагрузок и обновляет results/results.json + results/*.png
docker compose run --rm --build bench python3 -m benchmark.main --quick

# 2. Полный прогон по методичке (100x1MB write/read, 200x4KB random, 1000x4KB small files, 200 metadata ops)
docker compose run --rm bench

# 3. Просмотр результатов и отчёта на хосте macOS
cat results/results.json
open results/throughput_comparison.png results/iops_comparison.png results/latency_percentiles.png
# Подробный отчёт с таблицами и анализом: REPORT.md

# 4. Остановка MinIO и освобождение портов 9000/9001
docker compose down -v
```

---

### Задание 3 — Гибридное хранилище TechData Solutions (`task3_hybrid_storage/`)

```bash
cd task3_hybrid_storage

# 1. Сборка и запуск всего стека в фоне (minio + createbuckets + s3fs + app)
docker compose up -d --build

# 2. Проверка статуса контейнеров и логов s3fs
docker compose ps
docker compose logs s3fs

# 3. Демонстрация полного жизненного цикла (non-interactive CLI команды)
docker compose exec -T app python3 app/cli.py put promo.txt "Hello, Hybrid Storage!"
docker compose exec -T app python3 app/cli.py put raw_clip.bin 2
docker compose exec -T app python3 app/cli.py status

# Имитация старения > 7 дней и миграция HOT -> WARM (в MinIO через s3fs)
docker compose exec -T app python3 app/cli.py age promo.txt 10
docker compose exec -T app python3 app/cli.py age raw_clip.bin 10
docker compose exec -T app python3 app/cli.py migrate
docker compose exec -T app python3 app/cli.py status

# Проверка, что файлы реально появились в S3-бакете (видно в контейнере s3fs и MinIO Console)
docker compose exec -T s3fs ls -lh /mnt/s3
# Веб-консоль MinIO: http://localhost:9001 (логин: minioadmin / minioadmin123)

# Имитация дальнейшего старения > 30 дней и миграция WARM -> COLD (Glacier simulation)
docker compose exec -T app python3 app/cli.py age raw_clip.bin 25
docker compose exec -T app python3 app/cli.py migrate
docker compose exec -T app python3 app/cli.py status

# Автоматическое продвижение (auto-promote WARM->HOT и COLD->HOT) при чтении
docker compose exec -T app python3 app/cli.py get promo.txt
docker compose exec -T app python3 app/cli.py get raw_clip.bin
docker compose exec -T app python3 app/cli.py status
docker compose exec -T app python3 app/cli.py history

# 4. (Опционально) Интерактивная сессия CLI
docker compose exec app python3 -m app.cli

# 5. Остановка стека и освобождение портов 9000/9001
docker compose down -v
```

---

## Структура монорепозитория

```text
fuse_lab/
├── .gitignore
├── FUSE_Lab_Guide.docx
├── README.md
├── task1_sqlitefs/
│   ├── Dockerfile
│   ├── README.md
│   ├── REPORT.md
│   ├── database.py
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── run_demo.sh
│   ├── sqlitefs.py
│   └── test_sqlitefs.py
├── task2_s3_benchmark/
│   ├── Dockerfile.bench
│   ├── README.md
│   ├── REPORT.md
│   ├── benchmark/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── filesystem.py
│   │   ├── main.py
│   │   ├── metrics.py
│   │   ├── native_s3.py
│   │   ├── visualize.py
│   │   └── workloads.py
│   ├── charts/
│   │   └── .gitkeep
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── results/
│   │   ├── .gitkeep
│   │   ├── iops_comparison.png
│   │   ├── latency_percentiles.png
│   │   ├── results.json
│   │   └── throughput_comparison.png
│   └── scripts/
│       └── mount_s3.sh
└── task3_hybrid_storage/
    ├── ARCHITECTURE.md
    ├── Dockerfile.app
    ├── Dockerfile.s3fs
    ├── README.md
    ├── app/
    │   ├── __init__.py
    │   ├── cli.py
    │   ├── hybrid_storage.py
    │   └── main.py
    ├── docker-compose.yml
    ├── requirements.txt
    └── scripts/
        ├── app-entrypoint.sh
        └── s3fs-entrypoint.sh
```
