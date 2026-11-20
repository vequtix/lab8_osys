"""S3 storage benchmark package comparing s3fs, goofys, and native boto3."""

from benchmark.base import BenchmarkBase, BenchmarkResult
from benchmark.workloads import WORKLOADS, WorkloadSpec, get_workloads

__all__ = [
    "BenchmarkBase",
    "BenchmarkResult",
    "WORKLOADS",
    "WorkloadSpec",
    "get_workloads",
]
