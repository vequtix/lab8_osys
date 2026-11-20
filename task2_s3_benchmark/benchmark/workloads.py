"""Workload definitions and shared S3 payload/cleanup utilities."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import List, Optional, Sequence

import boto3
from botocore.config import Config


@dataclass(frozen=True)
class WorkloadSpec:
    """Specification of a single benchmark workload."""

    key: str
    label: str
    iterations: int
    block_size_bytes: int
    description: str
    file_size_bytes: Optional[int] = None


WORKLOADS: List[WorkloadSpec] = [
    WorkloadSpec(
        key="sequential_write",
        label="Sequential Write",
        iterations=100,
        block_size_bytes=1024 * 1024,
        description="1 MB x 100 files sequential write",
    ),
    WorkloadSpec(
        key="sequential_read",
        label="Sequential Read",
        iterations=100,
        block_size_bytes=1024 * 1024,
        description="1 MB x 100 files sequential read",
    ),
    WorkloadSpec(
        key="random_io",
        label="Random I/O",
        iterations=200,
        block_size_bytes=4096,
        file_size_bytes=4 * 1024 * 1024,
        description="4 KB random aligned reads over a 4 MB file",
    ),
    WorkloadSpec(
        key="small_files",
        label="Small Files",
        iterations=1000,
        block_size_bytes=4096,
        description="4 KB x 1000 small files creation",
    ),
    WorkloadSpec(
        key="metadata_ops",
        label="Metadata Ops",
        iterations=200,
        block_size_bytes=0,
        description="create + stat/head + delete metadata cycle",
    ),
]


def get_workloads(
    quick: bool = False, selected: Optional[Sequence[str]] = None
) -> List[WorkloadSpec]:
    """Return workloads, optionally filtered by key and scaled for --quick."""
    specs = WORKLOADS
    if selected:
        wanted = set(selected)
        specs = [w for w in specs if w.key in wanted]
        if not specs:
            valid = ", ".join(w.key for w in WORKLOADS)
            raise ValueError(f"Unknown workload(s): {selected}. Valid keys: {valid}")

    if not quick:
        return list(specs)

    return [
        replace(w, iterations=max(1, w.iterations // 10))
        for w in specs
    ]


def generate_payload(size: int, seed: int = 42) -> bytes:
    """Generate deterministic pseudo-random bytes of `size`."""
    if size <= 0:
        return b""
    return random.Random(seed).randbytes(size)


def create_s3_client(
    endpoint: str,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
):
    """Create a path-style boto3 S3 client for MinIO."""
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            max_pool_connections=32,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def purge_s3_prefix(client, bucket: str, prefix: str) -> None:
    """Delete all S3 objects starting with `prefix` using batched DeleteObjects."""
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        contents = page.get("Contents", [])
        if not contents:
            continue
        keys = [{"Key": obj["Key"]} for obj in contents]
        for start in range(0, len(keys), 1000):
            client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": keys[start : start + 1000], "Quiet": True},
            )
