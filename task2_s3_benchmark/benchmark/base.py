"""Abstract benchmark base class and result dataclass."""

from __future__ import annotations

import sys
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from benchmark.metrics import (
    compute_iops,
    compute_latency_stats,
    compute_throughput_mbps,
)


@dataclass
class BenchmarkResult:
    """Aggregated performance metrics for a single (storage, workload) run."""

    name: str
    storage: str
    workload: str
    iterations: int
    total_bytes: int
    total_time_sec: float
    throughput_mbps: float
    iops: float
    latency_avg_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    errors: int

    def to_dict(self) -> Dict[str, Any]:
        """Serialize result to a plain dictionary."""
        return asdict(self)


class BenchmarkBase(ABC):
    """Unified benchmark lifecycle using time.perf_counter() per iteration."""

    def __init__(self, name: str, storage: str, workload: str) -> None:
        self.name = name
        self.storage = storage
        self.workload = workload
        self.latencies: List[float] = []

    @abstractmethod
    def setup(self) -> None:
        """Prepare state before timing starts."""

    @abstractmethod
    def run_iteration(self, iteration: int) -> int:
        """Execute one benchmark iteration and return processed byte count."""

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up objects/files created during setup and run."""

    def run(self, iterations: int = 100) -> BenchmarkResult:
        """Run setup, timed iterations, cleanup, and compute summary metrics."""
        self.latencies = []
        total_bytes = 0
        errors = 0
        successful_ops = 0

        self.setup()
        try:
            for idx in range(iterations):
                start = time.perf_counter()
                try:
                    processed = int(self.run_iteration(idx))
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    if errors <= 3:
                        print(
                            f"[{self.name}] iteration {idx} error: {exc}",
                            file=sys.stderr,
                        )
                    continue
                elapsed = time.perf_counter() - start
                self.latencies.append(elapsed * 1000.0)
                total_bytes += processed
                successful_ops += 1
        finally:
            self.cleanup()

        return self._calculate_results(
            iterations=iterations,
            successful_ops=successful_ops,
            total_bytes=total_bytes,
            errors=errors,
        )

    def _calculate_results(
        self,
        iterations: int,
        successful_ops: int,
        total_bytes: int,
        errors: int,
    ) -> BenchmarkResult:
        total_time_sec = sum(self.latencies) / 1000.0
        avg_ms, p95_ms, p99_ms = compute_latency_stats(self.latencies)
        throughput_mbps = compute_throughput_mbps(total_bytes, total_time_sec)
        iops = compute_iops(successful_ops, total_time_sec)

        return BenchmarkResult(
            name=self.name,
            storage=self.storage,
            workload=self.workload,
            iterations=iterations,
            total_bytes=total_bytes,
            total_time_sec=round(total_time_sec, 4),
            throughput_mbps=round(throughput_mbps, 4),
            iops=round(iops, 2),
            latency_avg_ms=round(avg_ms, 3),
            latency_p95_ms=round(p95_ms, 3),
            latency_p99_ms=round(p99_ms, 3),
            errors=errors,
        )
