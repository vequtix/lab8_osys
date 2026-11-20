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
| **Задание 1** | [task1_sqlitefs/](./task1_sqlitefs/) | **Готово** — FUSE ФС на базе SQLite (чанки 4096 B, все базовые и доп. операции, 16 тестов, покрытие **99%**, демо с `/dev/fuse` и `sqlite3`) | [`database.py`](./task1_sqlitefs/database.py), [`sqlitefs.py`](./task1_sqlitefs/sqlitefs.py), [`test_sqlitefs.py`](./task1_sqlitefs/test_sqlitefs.py), [`run_demo.sh`](./task1_sqlitefs/run_demo.sh), [`Dockerfile`](./task1_sqlitefs/Dockerfile), [`docker-compose.yml`](./task1_sqlitefs/docker-compose.yml), [`README.md`](./task1_sqlitefs/README.md) |
| **Задание 2** | [task2_s3_benchmark/](./task2_s3_benchmark/) | **Готово** — Benchmark `s3fs` vs `goofys` vs `boto3` по 5 нагрузкам, полный прогон (`0` ошибок), графики и отчёт | [`benchmark/`](./task2_s3_benchmark/benchmark/), [`scripts/mount_s3.sh`](./task2_s3_benchmark/scripts/mount_s3.sh), [`Dockerfile.bench`](./task2_s3_benchmark/Dockerfile.bench), [`docker-compose.yml`](./task2_s3_benchmark/docker-compose.yml), [`results/results.json`](./task2_s3_benchmark/results/results.json), [`results/*.png`](./task2_s3_benchmark/results/), [`REPORT.md`](./task2_s3_benchmark/REPORT.md) |
| **Задание 3** | [task3_hybrid_storage/](./task3_hybrid_storage/) | **Готово** — Гибридное хранилище TechData Solutions (HOT/WARM/COLD, MinIO + `s3fs`, MD5, `metadata.json`, TCO для 500 TB) | [`app/hybrid_storage.py`](./task3_hybrid_storage/app/hybrid_storage.py), [`app/cli.py`](./task3_hybrid_storage/app/cli.py), [`scripts/s3fs-entrypoint.sh`](./task3_hybrid_storage/scripts/s3fs-entrypoint.sh), [`scripts/app-entrypoint.sh`](./task3_hybrid_storage/scripts/app-entrypoint.sh), [`Dockerfile.s3fs`](./task3_hybrid_storage/Dockerfile.s3fs), [`Dockerfile.app`](./task3_hybrid_storage/Dockerfile.app), [`docker-compose.yml`](./task3_hybrid_storage/docker-compose.yml), [`ARCHITECTURE.md`](./task3_hybrid_storage/ARCHITECTURE.md) |

---

## 1. Отчёт о прогоне и проверке

### Внесённые правки при аудите
- В [`task1_sqlitefs/Dockerfile`](./task1_sqlitefs/Dockerfile#L7-L13) добавлен пакет `sqlite3`, а в [`task1_sqlitefs/run_demo.sh`](./task1_sqlitefs/run_demo.sh#L72-L83) — инспекция таблиц `files` и `file_data` через `sqlite3` между размонтированием (`fusermount -u`) и повторным монтированием БД.

### Результаты по заданиям

1. **Задание 1 — SQLiteFS (`task1_sqlitefs/`, образ `ubuntu:22.04` arm64):**
   - **Unit-тесты (`docker compose run --rm sqlitefs`):** **`16 passed in 0.42s`**, общее покрытие **`99%`** ([`database.py`](./task1_sqlitefs/database.py) — 99%, [`sqlitefs.py`](./task1_sqlitefs/sqlitefs.py) — 99%, [`test_sqlitefs.py`](./task1_sqlitefs/test_sqlitefs.py) — 100%).
   - **Интеграционный прогон с `/dev/fuse` (`./run_demo.sh`):** пройдены запись/чтение, вложенный `mkdir`, 64 KB бинарный файл (SHA-256 совпал до и после перемонтирования), `chmod 0750`, `truncate -s 5`, `touch`, рекурсивный `mv /mnt/sqlitefs/projects /mnt/sqlitefs/projects_moved`, `df -h` и размонтирование через `fusermount -u`.
   - **Проверка через `sqlite3`:** для `/projects_moved/nested/blob_64k.bin` (`size = 65536`) таблица `file_data` содержит ровно **16 чанков по 4096 байт** (`total_bytes = 65536`), а для `/hello.txt` после `truncate -s 5` — 1 чанк длиной 5 байт.

2. **Задание 2 — S3 Benchmark (`task2_s3_benchmark/`, `bench` на `linux/amd64` под Rosetta 2 + `pgsty/minio` и `pgsty/mc`):**
   - Живая проверка в Docker (`--quick`) подтвердила старт MinIO, создание бакета `benchmark`, монтирование `/mnt/s3fs` и `/mnt/goofys`, выполнение всех 5 нагрузок (`errors = 0`), генерацию JSON и 3 PNG-графиков и корректное размонтирование.
   - Полные эталонные результаты сохранены в [`results/results.json`](./task2_s3_benchmark/results/results.json), графики — [`throughput_comparison.png`](./task2_s3_benchmark/results/throughput_comparison.png), [`iops_comparison.png`](./task2_s3_benchmark/results/iops_comparison.png), [`latency_percentiles.png`](./task2_s3_benchmark/results/latency_percentiles.png), отчёт — [`REPORT.md`](./task2_s3_benchmark/REPORT.md):

| Нагрузка | `s3fs-fuse` | `goofys v0.24.0` | `boto3` (Native S3) |
| :--- | :--- | :--- | :--- |
| **Sequential Write** (1 MiB × 100) | 75.69 MiB/s (P99 20.46 мс) | 66.32 MiB/s (P99 29.45 мс) | **86.92 MiB/s** (P99 13.29 мс) |
| **Sequential Read** (1 MiB × 100) | 231.98 MiB/s (P99 10.71 мс) | **237.34 MiB/s** (P99 7.75 мс) | 215.61 MiB/s (P99 **6.01 мс**) |
| **Random I/O** (4 KiB × 200) | 440.05 IOPS (avg 2.27 мс) | 547.73 IOPS (avg 1.83 мс) | **566.27 IOPS** (avg **1.77 мс**) |
| **Small Files** (4 KiB × 1000) | 290.47 IOPS (avg 3.44 мс) | 342.18 IOPS (avg 2.92 мс) | **480.32 IOPS** (avg **2.08 мс**) |
| **Metadata Ops** (200 циклов) | **295.28 IOPS** (avg 3.39 мс) | 266.42 IOPS (avg 3.75 мс) | 213.75 IOPS (avg 4.68 мс) |

3. **Задание 3 — Гибридное хранилище TechData Solutions (`task3_hybrid_storage/`):**
   - Стек `minio` (`healthy`) + `createbuckets` (`Exited 0`, бакет `hybrid-storage`) + `s3fs` (`healthy`, лог: `s3fs mounted successfully: bucket=hybrid-storage -> /mnt/s3`) + `app` (`Up`) стартовал через `docker compose up -d --build`.
   - Подтверждён полный жизненный цикл через CLI [`app/cli.py`](./task3_hybrid_storage/app/cli.py): `put` в `HOT` → `age 10` + `migrate` (`HOT → WARM`, файлы `promo.txt` 22 B и `raw_clip.bin` 2.0M подтверждены в `task3-s3fs:/mnt/s3`) → `age 25` + `migrate` (`WARM → COLD`) → `get` (`[AUTO-PROMOTE] WARM -> HOT` и `COLD -> HOT` с проверкой MD5) → `status` и `history`.

---

## 2. Пошаговая инструкция для демонстрации преподавателю (Copy-Paste)

### Задание 1 — SQLiteFS (`task1_sqlitefs/`)

```bash
cd /Users/daniel/fuse_lab/task1_sqlitefs

# 1. Unit-тесты и покрытие кода (> 80%)
docker compose run --rm --build sqlitefs

# 2. Автоматическая живая демонстрация с /dev/fuse, чанками > 4 KB и инспекцией sqlite3
docker compose run --rm sqlitefs ./run_demo.sh
```

**Ручная интерактивная проверка в контейнере (если попросит преподаватель):**
```bash
docker compose run --rm --entrypoint bash sqlitefs
python3 /app/sqlitefs.py /mnt/sqlitefs --database /tmp/live.db --foreground &
sleep 1
echo "Hello FUSE!" > /mnt/sqlitefs/test.txt
dd if=/dev/urandom of=/mnt/sqlitefs/big.bin bs=1024 count=20 status=none
mkdir /mnt/sqlitefs/dir && mv /mnt/sqlitefs/test.txt /mnt/sqlitefs/dir/renamed.txt
chmod 0750 /mnt/sqlitefs/dir/renamed.txt && truncate -s 5 /mnt/sqlitefs/dir/renamed.txt
ls -la /mnt/sqlitefs /mnt/sqlitefs/dir
fusermount -u /mnt/sqlitefs
sqlite3 -header -column /tmp/live.db "SELECT id, path, printf('%o', mode & 4095) AS perm, size FROM files;"
sqlite3 -header -column /tmp/live.db "SELECT file_id, COUNT(*) AS chunks, SUM(length(data)) AS bytes FROM file_data GROUP BY file_id;"
python3 /app/sqlitefs.py /mnt/sqlitefs --database /tmp/live.db --foreground &
sleep 1 && cat /mnt/sqlitefs/dir/renamed.txt && ls -lh /mnt/sqlitefs/big.bin
fusermount -u /mnt/sqlitefs
exit
```

### Задание 2 — Benchmark S3 (`task2_s3_benchmark/`)

```bash
cd /Users/daniel/fuse_lab/task2_s3_benchmark

# 1. Быстрый живой прогон на защите (~15 сек, пишет в /tmp чтобы не затирать полный отчёт)
docker compose run --rm --build bench python3 -m benchmark.main --quick --output-dir /tmp/demo_results

# 2. (Опционально) Полный прогон по методичке (обновит results/results.json и results/*.png)
docker compose run --rm bench

# 3. Просмотр результатов и графиков на хосте macOS
cat results/results.json
open results/throughput_comparison.png results/iops_comparison.png results/latency_percentiles.png

# 4. Остановка MinIO и освобождение портов 9000/9001 перед Заданием 3
docker compose down -v
```

### Задание 3 — Гибридное хранилище TechData Solutions (`task3_hybrid_storage/`)

```bash
cd /Users/daniel/fuse_lab/task3_hybrid_storage

# 1. Поднять весь стек (MinIO + createbuckets + s3fs + app)
docker compose up -d --build

# 2. Проверка статуса, созданного бакета и монтирования s3fs
docker compose ps
docker compose logs createbuckets s3fs

# 3. Демонстрация жизненного цикла (HOT -> WARM -> COLD -> auto-promote HOT)
docker compose exec -T app python3 app/cli.py put promo.txt "Hello, Hybrid Storage!"
docker compose exec -T app python3 app/cli.py put raw_clip.bin 2
docker compose exec -T app python3 app/cli.py status

# Старение > 7 дней -> миграция в WARM (MinIO через s3fs)
docker compose exec -T app python3 app/cli.py age promo.txt 10
docker compose exec -T app python3 app/cli.py age raw_clip.bin 10
docker compose exec -T app python3 app/cli.py migrate
docker compose exec -T app python3 app/cli.py status

# Проверка объектов физически в S3 через контейнер s3fs (и в браузере http://localhost:9001 — minioadmin / minioadmin123)
docker compose exec -T s3fs ls -lh /mnt/s3

# Старение > 30 дней -> миграция WARM -> COLD (симуляция Glacier)
docker compose exec -T app python3 app/cli.py age raw_clip.bin 25
docker compose exec -T app python3 app/cli.py migrate
docker compose exec -T app python3 app/cli.py status

# Чтение с автоматическим возвратом (auto-promote) на HOT + аудит-лог
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

## 3. Шпаргалка «Что рассказывать и где это в коде»

### Задание 1: SQLite FUSE файловая система

- **[`task1_sqlitefs/database.py`](./task1_sqlitefs/database.py):**
  - **Чанкование 4 KB:** [`L11`](./task1_sqlitefs/database.py#L11) (`CHUNK_SIZE = 4096`). Файлы бьются на 4 KB чанки, что снижает потребление RAM, ускоряет частичные `read`/`write` и поддерживает разреженные (sparse) файлы.
  - **Потокобезопасность и каскад FK:** `Database.__init__` ([`L41-L48`](./task1_sqlitefs/database.py#L41-L48) — `threading.Lock()`), `_transaction` ([`L50-L62`](./task1_sqlitefs/database.py#L50-L62) — `PRAGMA foreign_keys = ON;` при каждом соединении + `commit`/`rollback`). Схема `files`, `file_data` (`ON DELETE CASCADE`) и индексы `idx_files_path`, `idx_file_data_file_id` — [`L64-L100`](./task1_sqlitefs/database.py#L64-L100).
  - **Префиксный поиск без багов `LIKE`:** `_prefix_bounds` ([`L33-L38`](./task1_sqlitefs/database.py#L33-L38)) и `list_children` ([`L159-L176`](./task1_sqlitefs/database.py#L159-L176)) используют диапазон ASCII (`'/' < path < '0'`), чтобы `_` и `%` в именах файлов не работали как wildcard в `LIKE` и работал индекс `idx_files_path`.
  - **Чтение/запись по чанкам и sparse-файлы:** `read_data` ([`L194-L243`](./task1_sqlitefs/database.py#L194-L243) — дозаполнение дыр нулями `\x00`) и `write_data` ([`L245-L319`](./task1_sqlitefs/database.py#L245-L319) — merge граничных чанков и `ON CONFLICT DO UPDATE`).
  - **Корректный `truncate` и рекурсивный `rename`:** `truncate_file` ([`L321-L377`](./task1_sqlitefs/database.py#L321-L377) — обрезает BLOB последнего остающегося чанка, чтобы при последующем расширении читались нули); `rename_entry` ([`L452-L537`](./task1_sqlitefs/database.py#L452-L537) — атомарный рекурсивный `UPDATE` путей через `substr` и пересчёт `nlink` родителей).
- **[`task1_sqlitefs/sqlitefs.py`](./task1_sqlitefs/sqlitefs.py):**
  - **Наследование от `fuse.Operations`:** `SQLiteFS` и `_ensure_root` ([`L17-L34`](./task1_sqlitefs/sqlitefs.py#L17-L34)), защита `fuse_get_context()` в `_get_caller_ids` ([`L36-L43`](./task1_sqlitefs/sqlitefs.py#L36-L43)).
  - **FUSE callback-и:** `getattr` ([`L59-L73`](./task1_sqlitefs/sqlitefs.py#L59-L73)), `readdir` ([`L75-L80`](./task1_sqlitefs/sqlitefs.py#L75-L80)), `create`/`open`/`release`/`flush`/`fsync` ([`L82-L127`](./task1_sqlitefs/sqlitefs.py#L82-L127)), `read`/`write` ([`L129-L149`](./task1_sqlitefs/sqlitefs.py#L129-L149)), `unlink`/`mkdir`/`rmdir` ([`L151-L196`](./task1_sqlitefs/sqlitefs.py#L151-L196)), `chmod`/`chown` ([`L198-L213`](./task1_sqlitefs/sqlitefs.py#L198-L213)), `rename` с POSIX-проверками `EINVAL`/`ENOTEMPTY`/`EISDIR`/`ENOTDIR` ([`L215-L247`](./task1_sqlitefs/sqlitefs.py#L215-L247)), `truncate`/`utimens`/`statfs` ([`L249-L293`](./task1_sqlitefs/sqlitefs.py#L249-L293)).
  - **CLI-точка входа:** `parse_args` и `main` ([`L296-L340`](./task1_sqlitefs/sqlitefs.py#L296-L340) — `--database`, `--foreground`, `--allow-other`, `--debug`, `FUSE(..., nothreads=False)`).
- **[`task1_sqlitefs/test_sqlitefs.py`](./task1_sqlitefs/test_sqlitefs.py):** `test_large_multichunk_read_write_and_offsets` ([`L135-L177`](./task1_sqlitefs/test_sqlitefs.py#L135-L177)), `test_rename_directory_recursive_and_prefix_isolation` ([`L303-L334`](./task1_sqlitefs/test_sqlitefs.py#L303-L334)), `test_error_conditions` ([`L336-L428`](./task1_sqlitefs/test_sqlitefs.py#L336-L428)), `test_persistence_across_reinstantiation` ([`L430-L447`](./task1_sqlitefs/test_sqlitefs.py#L430-L447)).

### Задание 2: Benchmark сравнение S3 решений

- **Окружение Apple Silicon и монтирование:**
  - [`task2_s3_benchmark/Dockerfile.bench`](./task2_s3_benchmark/Dockerfile.bench): `FROM --platform=linux/amd64 ubuntu:22.04` ([`L1`](./task2_s3_benchmark/Dockerfile.bench#L1)) и загрузка `goofys v0.24.0` ([`L17-L18`](./task2_s3_benchmark/Dockerfile.bench#L17-L18)) для запуска через Rosetta 2 рядом с нативным `pgsty/minio`.
  - [`task2_s3_benchmark/scripts/mount_s3.sh`](./task2_s3_benchmark/scripts/mount_s3.sh): `cleanup` trap (`fusermount -u`) ([`L15-L27`](./task2_s3_benchmark/scripts/mount_s3.sh#L15-L27)), монтирование `s3fs` ([`L45-L51`](./task2_s3_benchmark/scripts/mount_s3.sh#L45-L51)) и `goofys` с `--region` ([`L54-L59`](./task2_s3_benchmark/scripts/mount_s3.sh#L54-L59)).
- **Единый интерфейс и математика метрик:**
  - [`task2_s3_benchmark/benchmark/base.py`](./task2_s3_benchmark/benchmark/base.py): `BenchmarkResult` ([`L18-L37`](./task2_s3_benchmark/benchmark/base.py#L18-L37)), `BenchmarkBase.run` с `time.perf_counter()` и `try/finally: self.cleanup()` ([`L61-L94`](./task2_s3_benchmark/benchmark/base.py#L61-L94)).
  - [`task2_s3_benchmark/benchmark/metrics.py`](./task2_s3_benchmark/benchmark/metrics.py): `compute_latency_stats` (`np.mean`, `np.percentile` 95/99) ([`L12-L21`](./task2_s3_benchmark/benchmark/metrics.py#L12-L21)), `compute_throughput_mbps` / `compute_iops` ([`L24-L35`](./task2_s3_benchmark/benchmark/metrics.py#L24-L35)).
- **5 нагрузок и методика:**
  - [`task2_s3_benchmark/benchmark/workloads.py`](./task2_s3_benchmark/benchmark/workloads.py): `WORKLOADS` ([`L25-L62`](./task2_s3_benchmark/benchmark/workloads.py#L25-L62)), `get_workloads` (`--quick`) ([`L65-L83`](./task2_s3_benchmark/benchmark/workloads.py#L65-L83)).
  - [`task2_s3_benchmark/benchmark/filesystem.py`](./task2_s3_benchmark/benchmark/filesystem.py) vs [`task2_s3_benchmark/benchmark/native_s3.py`](./task2_s3_benchmark/benchmark/native_s3.py): cold-cache seeding через `boto3` перед чтением в `FSSequentialReadBenchmark` ([`L73-L98`](./task2_s3_benchmark/benchmark/filesystem.py#L73-L98)) и `FSRandomIOBenchmark` ([`L101-L135`](./task2_s3_benchmark/benchmark/filesystem.py#L101-L135)); `NativeS3RandomIOBenchmark` ([`L91-L129`](./task2_s3_benchmark/benchmark/native_s3.py#L91-L129)) с HTTP `Range`.
  - **Ключевые выводы для защиты:** на `Small Files` `boto3` быстрее `s3fs` на **65%** (`480` vs `290` IOPS) за счёт прямого `PutObject` без VFS/FUSE context switches и POSIX-метаданных; на `Metadata Ops` FUSE быстрее (`295` vs `214` IOPS), т.к. `os.stat()` попадает в `stat_cache` FUSE, тогда как `NativeS3MetadataOpsBenchmark` ([`L148-L159`](./task2_s3_benchmark/benchmark/native_s3.py#L148-L159)) делает 3 явных HTTP-вызова (`PutObject` + `HeadObject` + `DeleteObject`).
- **Визуализация и CLI:** [`task2_s3_benchmark/benchmark/visualize.py`](./task2_s3_benchmark/benchmark/visualize.py#L72-L342) и [`task2_s3_benchmark/benchmark/main.py`](./task2_s3_benchmark/benchmark/main.py#L20-L184).

### Задание 3: Гибридное хранилище TechData Solutions

- **Стек сервисов и macOS/FUSE-нюанс:**
  - [`task3_hybrid_storage/docker-compose.yml`](./task3_hybrid_storage/docker-compose.yml): `minio` с `healthcheck` ([`L3-L20`](./task3_hybrid_storage/docker-compose.yml#L3-L20)), `createbuckets` ([`L22-L33`](./task3_hybrid_storage/docker-compose.yml#L22-L33)), `s3fs` с `/dev/fuse` и FUSE `healthcheck` ([`L35-L64`](./task3_hybrid_storage/docker-compose.yml#L35-L64)), `app` с `/data/hot`, `/data/warm`, `/data/cold` ([`L66-L92`](./task3_hybrid_storage/docker-compose.yml#L66-L92)).
  - [`task3_hybrid_storage/scripts/s3fs-entrypoint.sh`](./task3_hybrid_storage/scripts/s3fs-entrypoint.sh#L37-L49) и [`task3_hybrid_storage/scripts/app-entrypoint.sh`](./task3_hybrid_storage/scripts/app-entrypoint.sh#L24-L48): обход ограничения Docker Desktop macOS (отсутствие `:rshared` propagation) через проверку `grep -qs " ${WARM_PATH} fuse" /proc/mounts`, чтобы `/data/warm` в `app` гарантированно был смонтирован через `s3fs` (`use_cache`, `parallel_count=15`, `multipart_size=52`, `allow_other`).
- **Ядро менеджера гибридного хранилища ([`task3_hybrid_storage/app/hybrid_storage.py`](./task3_hybrid_storage/app/hybrid_storage.py)):**
  - **Модель данных и персистентность:** `StorageTier`, `FileMetadata`, `HistoryEvent` ([`L19-L84`](./task3_hybrid_storage/app/hybrid_storage.py#L19-L84)), атомарная запись `metadata.json` через `os.replace()` в `reload` / `_save_state` ([`L150-L182`](./task3_hybrid_storage/app/hybrid_storage.py#L150-L182)).
  - **Запись и MD5:** `put` ([`L216-L248`](./task3_hybrid_storage/app/hybrid_storage.py#L216-L248)) и потоковый `put_sized` ([`L250-L299`](./task3_hybrid_storage/app/hybrid_storage.py#L250-L299)) — запись в `HOT` с подсчётом MD5.
  - **Протокол Copy-Verify-Delete:** `_transfer_file` ([`L301-L340`](./task3_hybrid_storage/app/hybrid_storage.py#L301-L340)) — `shutil.copyfile` (обход `EXDEV` и ограничений `s3fs` на `chmod`/`utime`) + сверка MD5 до удаления исходника.
  - **Auto-promote и миграция:** `get_with_info` ([`L368-L416`](./task3_hybrid_storage/app/hybrid_storage.py#L368-L416)) вызывает `_promote` при чтении из `WARM`/`COLD`; `migrate` ([`L423-L458`](./task3_hybrid_storage/app/hybrid_storage.py#L423-L458)) переводит `HOT → WARM` (> 7д) и `WARM → COLD` (> 30д); `age_file` ([`L460-L480`](./task3_hybrid_storage/app/hybrid_storage.py#L460-L480)).
- **CLI и архитектура:**
  - [`task3_hybrid_storage/app/cli.py`](./task3_hybrid_storage/app/cli.py): неинтерактивный и интерактивный режимы `main` ([`L229-L272`](./task3_hybrid_storage/app/cli.py#L229-L272)), таблица `status` ([`L40-L73`](./task3_hybrid_storage/app/cli.py#L40-L73)), аудит `history` ([`L76-L107`](./task3_hybrid_storage/app/cli.py#L76-L107)).
  - [`task3_hybrid_storage/ARCHITECTURE.md`](./task3_hybrid_storage/ARCHITECTURE.md): Executive Summary и SLA ([`L3-L29`](./task3_hybrid_storage/ARCHITECTURE.md#L3-L29)), Mermaid/ASCII-диаграммы ([`L35-L79`](./task3_hybrid_storage/ARCHITECTURE.md#L35-L79)), политики ILM ([`L97-L112`](./task3_hybrid_storage/ARCHITECTURE.md#L97-L112)), TCO для 500 TB (**\$50,000/мес** All-NVMe vs **\$10,000/мес** гибрид, экономия **80%** / **\$480,000 в год**, [`L116-L137`](./task3_hybrid_storage/ARCHITECTURE.md#L116-L137)) и план внедрения с мониторингом Prometheus/Grafana ([`L141-L160`](./task3_hybrid_storage/ARCHITECTURE.md#L141-L160)).

---

## Структура монорепозитория

```text
fuse_lab/
├── .gitignore
├── Defense_Guide.docx
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
