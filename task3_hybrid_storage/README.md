# Задание 3: Гибридное хранилище TechData Solutions (HOT / WARM / COLD)

Proof-of-concept трёхуровневого гибридного хранилища видеоконтента на базе Docker Compose, MinIO, `s3fs-fuse` и Python (`HybridStorageManager` + интерактивный CLI).

## Компоненты

- [`docker-compose.yml`](./docker-compose.yml) — стек из 4 сервисов: `minio` (с `healthcheck`), `createbuckets` (создаёт бакет `hybrid-storage`), `s3fs` (`--privileged`, `/dev/fuse`, кэширование) и `app` (3 уровня: `/data/hot`, `/data/warm`, `/data/cold`).
- [`Dockerfile.s3fs`](./Dockerfile.s3fs) и [`scripts/s3fs-entrypoint.sh`](./scripts/s3fs-entrypoint.sh) — контейнер монтирования `s3fs` (`use_cache`, `parallel_count=15`, `multipart_size=52`, `allow_other`).
- [`Dockerfile.app`](./Dockerfile.app) и [`scripts/app-entrypoint.sh`](./scripts/app-entrypoint.sh) — контейнер приложения с подключёнными уровнями хранения.
- [`app/hybrid_storage.py`](./app/hybrid_storage.py) — класс `HybridStorageManager`, персистентное хранение `metadata.json`, MD5-верификация при всех перемещениях, автоматическое продвижение (`_promote`) при `get` и миграция (`HOT -> WARM > 7d`, `WARM -> COLD > 30d`).
- [`app/cli.py`](./app/cli.py) и [`app/main.py`](./app/main.py) — интерактивный CLI (`put`, `get`, `status`, `migrate`, `age`, `history`, `delete`).
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — полная архитектурная документация, диаграммы, политики миграции, TCO-анализ для 500 TB и план внедрения.

## Запуск и демонстрация

```bash
cd task3_hybrid_storage

# 1. Сборка и запуск стека в фоне
docker compose up -d --build

# 2. Проверка статуса сервисов
docker compose ps

# 3. Интерактивная сессия CLI
docker compose exec app python3 -m app.cli
```

### Сценарий демонстрации в CLI (`put -> age -> migrate -> get`)

```text
hybrid> put promo.txt Hello, Hybrid Storage!
hybrid> put raw_clip.bin 2
hybrid> status
hybrid> age promo.txt 10
hybrid> age raw_clip.bin 10
hybrid> migrate
hybrid> status
hybrid> age raw_clip.bin 25
hybrid> migrate
hybrid> status
hybrid> get promo.txt
hybrid> get raw_clip.bin
hybrid> status
hybrid> history
```

Веб-консоль MinIO: `http://localhost:9001` (`minioadmin` / `minioadmin123`).

Остановка и очистка томов:

```bash
docker compose down -v
```
