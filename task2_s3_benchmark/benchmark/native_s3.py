"""Native S3 API benchmark implementations using boto3."""

from __future__ import annotations

import random
from typing import Any, Dict, List

from benchmark.base import BenchmarkBase
from benchmark.workloads import (
    WorkloadSpec,
    create_s3_client,
    generate_payload,
    purge_s3_prefix,
)


class _NativeS3BenchmarkBase(BenchmarkBase):
    """Common setup/cleanup helpers for direct boto3 S3 benchmarks."""

    def __init__(
        self,
        workload: WorkloadSpec,
        s3_config: Dict[str, str],
    ) -> None:
        super().__init__(
            name=f"boto3:{workload.key}",
            storage="boto3",
            workload=workload.key,
        )
        self.spec = workload
        self.bucket = s3_config["bucket"]
        self.prefix = f"bench_boto3_{workload.key}"
        self.s3_client = create_s3_client(
            endpoint=s3_config["endpoint"],
            access_key=s3_config["access_key"],
            secret_key=s3_config["secret_key"],
            region=s3_config.get("region", "us-east-1"),
        )

    def _purge(self) -> None:
        purge_s3_prefix(self.s3_client, self.bucket, f"{self.prefix}/")

    def cleanup(self) -> None:
        self._purge()


class NativeS3SequentialWriteBenchmark(_NativeS3BenchmarkBase):
    """Sequential write of 1 MB objects via boto3 put_object."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.payload = generate_payload(self.spec.block_size_bytes, seed=101)

    def setup(self) -> None:
        self._purge()

    def run_iteration(self, iteration: int) -> int:
        key = f"{self.prefix}/seq_w_{iteration:04d}.bin"
        self.s3_client.put_object(Bucket=self.bucket, Key=key, Body=self.payload)
        return len(self.payload)


class NativeS3SequentialReadBenchmark(_NativeS3BenchmarkBase):
    """Sequential read of 1 MB objects via boto3 get_object."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.payload = generate_payload(self.spec.block_size_bytes, seed=202)

    def setup(self) -> None:
        self._purge()
        for idx in range(self.spec.iterations):
            key = f"{self.prefix}/seq_r_{idx:04d}.bin"
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=self.payload,
            )

    def run_iteration(self, iteration: int) -> int:
        key = f"{self.prefix}/seq_r_{iteration:04d}.bin"
        resp = self.s3_client.get_object(Bucket=self.bucket, Key=key)
        data = resp["Body"].read()
        if len(data) != len(self.payload):
            raise RuntimeError(
                f"Short S3 read on {key}: expected {len(self.payload)}, got {len(data)}"
            )
        return len(data)


class NativeS3RandomIOBenchmark(_NativeS3BenchmarkBase):
    """Random 4 KB byte-range reads over a 4 MB object via boto3 get_object."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.block_size = self.spec.block_size_bytes
        self.file_size = self.spec.file_size_bytes or (4 * 1024 * 1024)
        self.target_key = f"{self.prefix}/random_target.bin"
        self.offsets: List[int] = []

    def setup(self) -> None:
        self._purge()
        blob = generate_payload(self.file_size, seed=303)
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=self.target_key,
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
        byte_range = f"bytes={offset}-{offset + self.block_size - 1}"
        resp = self.s3_client.get_object(
            Bucket=self.bucket,
            Key=self.target_key,
            Range=byte_range,
        )
        data = resp["Body"].read()
        if len(data) != self.block_size:
            raise RuntimeError(
                f"Short range read at {offset}: expected {self.block_size}, got {len(data)}"
            )
        return len(data)


class NativeS3SmallFilesBenchmark(_NativeS3BenchmarkBase):
    """Creation of many 4 KB objects via boto3 put_object."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.payload = generate_payload(self.spec.block_size_bytes, seed=404)

    def setup(self) -> None:
        self._purge()

    def run_iteration(self, iteration: int) -> int:
        key = f"{self.prefix}/small_{iteration:05d}.bin"
        self.s3_client.put_object(Bucket=self.bucket, Key=key, Body=self.payload)
        return len(self.payload)


class NativeS3MetadataOpsBenchmark(_NativeS3BenchmarkBase):
    """Metadata cycle (put_object + head_object + delete_object) via boto3."""

    def setup(self) -> None:
        self._purge()

    def run_iteration(self, iteration: int) -> int:
        key = f"{self.prefix}/meta_{iteration:04d}.tmp"
        self.s3_client.put_object(Bucket=self.bucket, Key=key, Body=b"")
        self.s3_client.head_object(Bucket=self.bucket, Key=key)
        self.s3_client.delete_object(Bucket=self.bucket, Key=key)
        return 0


_NATIVE_BENCHMARK_MAP = {
    "sequential_write": NativeS3SequentialWriteBenchmark,
    "sequential_read": NativeS3SequentialReadBenchmark,
    "random_io": NativeS3RandomIOBenchmark,
    "small_files": NativeS3SmallFilesBenchmark,
    "metadata_ops": NativeS3MetadataOpsBenchmark,
}


def create_native_s3_benchmark(
    workload: WorkloadSpec,
    s3_config: Dict[str, str],
) -> BenchmarkBase:
    """Instantiate the appropriate native boto3 S3 benchmark for a workload."""
    cls = _NATIVE_BENCHMARK_MAP.get(workload.key)
    if cls is None:
        raise ValueError(f"Unsupported workload key: {workload.key}")
    return cls(workload=workload, s3_config=s3_config)
