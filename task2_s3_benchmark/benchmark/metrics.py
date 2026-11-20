"""Metrics calculation and JSON persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple, Union

import numpy as np


def compute_latency_stats(latencies_ms: Sequence[float]) -> Tuple[float, float, float]:
    """Return (avg_ms, p95_ms, p99_ms) from latency samples in milliseconds."""
    if not latencies_ms:
        return 0.0, 0.0, 0.0
    arr = np.asarray(latencies_ms, dtype=np.float64)
    return (
        float(np.mean(arr)),
        float(np.percentile(arr, 95)),
        float(np.percentile(arr, 99)),
    )


def compute_throughput_mbps(total_bytes: int, elapsed_sec: float) -> float:
    """Return throughput in MiB/s."""
    if elapsed_sec <= 0 or total_bytes <= 0:
        return 0.0
    return (total_bytes / (1024.0 * 1024.0)) / elapsed_sec


def compute_iops(successful_ops: int, elapsed_sec: float) -> float:
    """Return operations per second."""
    if elapsed_sec <= 0 or successful_ops <= 0:
        return 0.0
    return successful_ops / elapsed_sec


def save_results_json(payload: Dict[str, Any], path: Union[str, Path]) -> Path:
    """Write benchmark results payload to formatted JSON."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def load_results_json(path: Union[str, Path]) -> Dict[str, Any]:
    """Load benchmark results payload from JSON."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
