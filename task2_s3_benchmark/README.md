# Задание 2: Benchmark сравнение S3-решений (`s3fs`, `goofys`, `boto3`)

Модульный benchmark-фреймворк на Python для сравнительного тестирования производительности `s3fs-fuse`, `goofys v0.24.0` и нативного S3 API (`boto3`) против локального MinIO. Контейнер `bench` запускается с `platform: linux/amd64` (для корректной работы бинарника `goofys` через Rosetta на Apple Silicon), `--privileged` и `/dev/fuse`.

## Структура

- [`Dockerfile.bench`](./Dockerfile.bench) — образ `linux/amd64` на базе `ubuntu:22.04` с `s3fs`, `goofys v0.24.0`, `boto3`, `matplotlib`, `numpy`.
- [`docker-compose.yml`](./docker-compose.yml) — сервисы `minio`, init-контейнер `mc` (создание бакета `benchmark`) и `bench`.
- [`scripts/mount_s3.sh`](./scripts/mount_s3.sh) — entrypoint-скрипт монтирования `/mnt/s3fs` и `/mnt/goofys` перед запуском тестов.
- [`benchmark/`](./benchmark/) — пакет бенчмарков (`base.py`, `filesystem.py`, `native_s3.py`, `workloads.py`, `metrics.py`, `visualize.py`, `main.py`).
- [`results/`](./results/) — сырые метрики (`results.json`) и графики (`*.png`).
- [`REPORT.md`](./REPORT.md) — аналитический отчёт по результатам полного прогона.

## Запуск в Docker

```bash
cd task2_s3_benchmark

# 1. Сборка образа bench (linux/amd64)
docker compose build bench

# 2. Быстрая демонстрация (итерации уменьшены в 10 раз)
docker compose run --rm bench python3 -m benchmark.main --quick

# 3. Полный прогон всех 5 нагрузок по методичке
docker compose run --rm bench

# 4. Перегенерация только графиков по готовому results/results.json
docker compose run --rm --no-deps --entrypoint python3 bench -m benchmark.main --plot-only

# 5. Остановка и очистка сервисов/томов
docker compose down -v
```
