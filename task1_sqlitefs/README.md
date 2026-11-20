# Задание 1: SQLiteFS — FUSE файловая система на базе SQLite

Реализация POSIX-совместимой FUSE файловой системы (`fusepy`) с хранением метаданных и содержимого файлов (чанками по 4096 байт) в базе данных SQLite.

## Структура директории

- [`database.py`](./database.py) — потокобезопасный слой работы с SQLite (`threading.Lock`, `PRAGMA foreign_keys = ON;`, таблицы `files` и `file_data`, индексы, операции по чанкам).
- [`sqlitefs.py`](./sqlitefs.py) — класс `SQLiteFS(Operations)` и CLI-точка входа (`--database`, `--foreground`, `--allow-other`, `--debug`).
- [`test_sqlitefs.py`](./test_sqlitefs.py) — unit-тесты на `pytest` (базовые и дополнительные операции, файлы `> 50 KB`, разреженные записи, рекурсивный `rename`, граничные ошибки и персистентность).
- [`Dockerfile`](./Dockerfile) и [`docker-compose.yml`](./docker-compose.yml) — сборка окружения на `ubuntu:22.04` (совместимо с `linux/arm64` на Apple Silicon).
- [`run_demo.sh`](./run_demo.sh) — интеграционный сценарий с реальным монтированием `/dev/fuse` в Docker.

## Сборка и тестирование в Docker (Apple Silicon ARM64)

```bash
cd task1_sqlitefs

# 1. Сборка образа
docker build -t task1-sqlitefs .

# 2. Запуск unit-тестов с расчётом покрытия кода
docker run --rm task1-sqlitefs pytest --cov=. --cov-report=term-missing -v

# 3. Запуск живой демонстрации с монтированием /dev/fuse
docker run --rm --privileged --device /dev/fuse task1-sqlitefs ./run_demo.sh
```

## Ручное монтирование внутри контейнера

```bash
docker run --rm -it --privileged --device /dev/fuse task1-sqlitefs bash
python3 /app/sqlitefs.py /mnt/sqlitefs --database /tmp/test.db --foreground
```
