"""Filesystem benchmark implementations for mounted FUSE paths (s3fs, goofys)."""

from __future__ import annotations

import os
import random
import shutil
from typing import Any, Dict, List

from benchmark.base import BenchmarkBase
from benchmark.workloads import (
    WorkloadSpec,
    create_s3_client,
    generate_payload,
    purge_s3_prefix,
)


class _FUSEBenchmarkBase(BenchmarkBase):
    """Common setup/cleanup helpers for mounted FUSE S3 benchmarks."""

    def __init__(
        self,
        storage: str,
        mount_path: str,
        workload: WorkloadSpec,
        s3_config: Dict[str, str],
    ) -> None:
        super().__init__(
            name=f"{storage}:{workload.key}",
            storage=storage,
            workload=workload.key,
        )
        self.mount_path = mount_path
        self.spec = workload
        self.bucket = s3_config["bucket"]
        self.prefix = f"bench_{storage}_{workload.key}"
        self.base_dir = os.path.join(mount_path, self.prefix)
        self.s3_client = create_s3_client(
            endpoint=s3_config["endpoint"],
            access_key=s3_config["access_key"],
            secret_key=s3_config["secret_key"],
            region=s3_config.get("region", "us-east-1"),
        )

    def _prepare_clean_dir(self) -> None:
        purge_s3_prefix(self.s3_client, self.bucket, f"{self.prefix}/")
        os.makedirs(self.base_dir, exist_ok=True)

    def cleanup(self) -> None:
        purge_s3_prefix(self.s3_client, self.bucket, f"{self.prefix}/")
        if os.path.isdir(self.base_dir):
            shutil.rmtree(self.base_dir, ignore_errors=True)


class FSSequentialWriteBenchmark(_FUSEBenchmarkBase):
    """Sequential write of 1 MB files through FUSE."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.payload = generate_payload(self.spec.block_size_bytes, seed=101)

    def setup(self) -> None:
        self._prepare_clean_dir()

    def run_iteration(self, iteration: int) -> int:
        target = os.path.join(self.base_dir, f"seq_w_{iteration:04d}.bin")
        with open(target, "wb") as fh:
            fh.write(self.payload)
        return len(self.payload)


class FSSequentialReadBenchmark(_FUSEBenchmarkBase):
    """Sequential read of pre-seeded 1 MB objects through FUSE."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.payload = generate_payload(self.spec.block_size_bytes, seed=202)

    def setup(self) -> None:
        self._prepare_clean_dir()
        for idx in range(self.spec.iterations):
            key = f"{self.prefix}/seq_r_{idx:04d}.bin"
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=self.payload,
            )

    def run_iteration(self, iteration: int) -> int:
        target = os.path.join(self.base_dir, f"seq_r_{iteration:04d}.bin")
        with open(target, "rb") as fh:
            data = fh.read()
        if len(data) != len(self.payload):
            raise RuntimeError(
                f"Short read on {target}: expected {len(self.payload)}, got {len(data)}"
            )
        return len(data)


class FSRandomIOBenchmark(_FUSEBenchmarkBase):
    """Random 4 KB aligned reads over a pre-seeded 4 MB object through FUSE."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.block_size = self.spec.block_size_bytes
        self.file_size = self.spec.file_size_bytes or (4 * 1024 * 1024)
        self.file_path = os.path.join(self.base_dir, "random_target.bin")
        self.offsets: List[int] = []

    def setup(self) -> None:
        self._prepare_clean_dir()
        blob = generate_payload(self.file_size, seed=303)
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=f"{self.prefix}/random_target.bin",
            Body=blob,
        )
        num_blocks = self.file_size // self.block_size
        rng = random.Random(303)
        self.offsets = [
            rng.randrange(0, num_blocks) * self.block_size
            for _ in range(self.spec.iterations)
        ]

    def run_iteration(self, iteration: int) -> int:
        offset = self.offsets[iteration]
        with open(self.file_path, "rb") as fh:
            fh.seek(offset)
            data = fh.read(self.block_size)
        if len(data) != self.block_size:
            raise RuntimeError(
                f"Short random read at {offset}: expected {self.block_size}, got {len(data)}"
            )
        return len(data)


class FSSmallFilesBenchmark(_FUSEBenchmarkBase):
    """Creation of many 4 KB files through FUSE."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.payload = generate_payload(self.spec.block_size_bytes, seed=404)

    def setup(self) -> None:
        self._prepare_clean_dir()

    def run_iteration(self, iteration: int) -> int:
        target = os.path.join(self.base_dir, f"small_{iteration:05d}.bin")
        with open(target, "wb") as fh:
            fh.write(self.payload)
        return len(self.payload)


class FSMetadataOpsBenchmark(_FUSEBenchmarkBase):
    """Metadata cycle (create + stat + unlink) through FUSE."""

    def setup(self) -> None:
        self._prepare_clean_dir()

    def run_iteration(self, iteration: int) -> int:
        target = os.path.join(self.base_dir, f"meta_{iteration:04d}.tmp")
        with open(target, "wb"):
            pass
        _ = os.stat(target)
        os.unlink(target)
        return 0


_FS_BENCHMARK_MAP = {
    "sequential_write": FSSequentialWriteBenchmark,
    "sequential_read": FSSequentialReadBenchmark,
    "random_io": FSRandomIOBenchmark,
    "small_files": FSSmallFilesBenchmark,
    "metadata_ops": FSMetadataOpsBenchmark,
}


def create_fs_benchmark(
    storage: str,
    mount_path: str,
    workload: WorkloadSpec,
    s3_config: Dict[str, str],
) -> BenchmarkBase:
    """Instantiate the appropriate FUSE filesystem benchmark for a workload."""
    cls = _FS_BENCHMARK_MAP.get(workload.key)
    if cls is None:
        raise ValueError(f"Unsupported workload key: {workload.key}")
    return cls(
        storage=storage,
        mount_path=mount_path,
        workload=workload,
        s3_config=s3_config,
    )
