"""Matplotlib visualizations for S3 benchmark comparisons."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

STORAGE_ORDER = ("s3fs", "goofys", "boto3")
STORAGE_LABELS = {
    "s3fs": "s3fs-fuse",
    "goofys": "goofys",
    "boto3": "Native API (boto3)",
}
STORAGE_COLORS = {
    "s3fs": "#e74c3c",
    "goofys": "#3498db",
    "boto3": "#2ecc71",
}

PERCENTILE_KEYS = ("latency_avg_ms", "latency_p95_ms", "latency_p99_ms")
PERCENTILE_LABELS = ("avg", "p95", "p99")
PERCENTILE_COLORS = ("#3498db", "#f39c12", "#e74c3c")

WORKLOAD_ORDER = (
    ("sequential_write", "Sequential Write\n(1 MB x N)"),
    ("sequential_read", "Sequential Read\n(1 MB x N)"),
    ("random_io", "Random I/O\n(4 KB Reads)"),
    ("small_files", "Small Files\n(4 KB x N)"),
    ("metadata_ops", "Metadata Ops\n(Create/Stat/Del)"),
)


def _format_value(val: float) -> str:
    if val >= 100:
        return f"{val:.0f}"
    if val >= 10:
        return f"{val:.1f}"
    if val >= 1:
        return f"{val:.2f}"
    if val > 0:
        return f"{val:.3f}"
    return "0"


def _active_workloads(results_data: Dict[str, Any], include_metadata: bool) -> List[Tuple[str, str]]:
    results = results_data.get("results", {})
    out = []
    for key, label in WORKLOAD_ORDER:
        if not include_metadata and key == "metadata_ops":
            continue
        if key in results and results[key]:
            out.append((key, label))
    return out


def _active_storages(results_data: Dict[str, Any]) -> List[str]:
    meta_storages = results_data.get("metadata", {}).get("storages")
    if meta_storages:
        return [s for s in STORAGE_ORDER if s in meta_storages]
    found = set()
    for wl_map in results_data.get("results", {}).values():
        found.update(wl_map.keys())
    return [s for s in STORAGE_ORDER if s in found]


def plot_throughput_comparison(
    results_data: Dict[str, Any],
    output_path: Union[str, Path],
) -> Path:
    """Plot grouped bar chart comparing Throughput (MB/s) across backends."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    workloads = _active_workloads(results_data, include_metadata=False)
    storages = _active_storages(results_data)
    results = results_data.get("results", {})

    fig, ax = plt.subplots(figsize=(11, 6))
    x = np.arange(len(workloads))
    width = 0.25
    offsets = (np.arange(len(storages)) - (len(storages) - 1) / 2.0) * width

    max_val = 0.0
    min_pos = float("inf")

    for s_idx, storage in enumerate(storages):
        vals = [
            float(results.get(w_key, {}).get(storage, {}).get("throughput_mbps", 0.0))
            for w_key, _ in workloads
        ]
        for v in vals:
            max_val = max(max_val, v)
            if v > 0:
                min_pos = min(min_pos, v)

        bars = ax.bar(
            x + offsets[s_idx],
            vals,
            width=width * 0.92,
            label=STORAGE_LABELS.get(storage, storage),
            color=STORAGE_COLORS.get(storage, "#7f8c8d"),
            edgecolor="#2c3e50",
            linewidth=0.6,
        )
        for bar, val in zip(bars, vals):
            ax.annotate(
                _format_value(val),
                xy=(bar.get_x() + bar.get_width() / 2.0, val),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8.5,
                fontweight="bold",
            )

    use_log = min_pos < float("inf") and max_val / max(min_pos, 1e-6) > 30
    if use_log:
        ax.set_yscale("log")
        ax.set_ylim(bottom=max(min_pos * 0.4, 1e-3), top=max_val * 2.8)
    else:
        ax.set_ylim(0, max_val * 1.22 if max_val > 0 else 10)

    ax.set_xticks(x)
    ax.set_xticklabels([label for _, label in workloads], fontsize=10)
    ax.set_ylabel("Throughput (MiB/s)", fontsize=11, fontweight="bold")
    ax.set_title(
        "S3 Storage Solutions — Throughput Comparison",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax.grid(axis="y", linestyle="--", alpha=0.35, which="both")
    ax.set_axisbelow(True)
    ax.legend(frameon=True, fontsize=10, loc="upper right")

    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_iops_comparison(
    results_data: Dict[str, Any],
    output_path: Union[str, Path],
) -> Path:
    """Plot grouped bar chart comparing IOPS across all workloads."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    workloads = _active_workloads(results_data, include_metadata=True)
    storages = _active_storages(results_data)
    results = results_data.get("results", {})

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(workloads))
    width = 0.25
    offsets = (np.arange(len(storages)) - (len(storages) - 1) / 2.0) * width

    max_val = 0.0
    min_pos = float("inf")

    for s_idx, storage in enumerate(storages):
        vals = [
            float(results.get(w_key, {}).get(storage, {}).get("iops", 0.0))
            for w_key, _ in workloads
        ]
        for v in vals:
            max_val = max(max_val, v)
            if v > 0:
                min_pos = min(min_pos, v)

        bars = ax.bar(
            x + offsets[s_idx],
            vals,
            width=width * 0.92,
            label=STORAGE_LABELS.get(storage, storage),
            color=STORAGE_COLORS.get(storage, "#7f8c8d"),
            edgecolor="#2c3e50",
            linewidth=0.6,
        )
        for bar, val in zip(bars, vals):
            ax.annotate(
                _format_value(val),
                xy=(bar.get_x() + bar.get_width() / 2.0, val),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8.5,
                fontweight="bold",
            )

    use_log = min_pos < float("inf") and max_val / max(min_pos, 1e-6) > 25
    if use_log:
        ax.set_yscale("log")
        ax.set_ylim(bottom=max(min_pos * 0.4, 0.1), top=max_val * 2.8)
    else:
        ax.set_ylim(0, max_val * 1.22 if max_val > 0 else 10)

    ax.set_xticks(x)
    ax.set_xticklabels([label for _, label in workloads], fontsize=10)
    ax.set_ylabel("IOPS (ops/sec)", fontsize=11, fontweight="bold")
    ax.set_title(
        "S3 Storage Solutions — IOPS Comparison",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax.grid(axis="y", linestyle="--", alpha=0.35, which="both")
    ax.set_axisbelow(True)
    ax.legend(frameon=True, fontsize=10, loc="upper left")

    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_latency_percentiles(
    results_data: Dict[str, Any],
    output_path: Union[str, Path],
) -> Path:
    """Plot grouped latency percentiles (avg, p95, p99) per workload and backend."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    workloads = _active_workloads(results_data, include_metadata=True)
    storages = _active_storages(results_data)
    results = results_data.get("results", {})

    fig, axes = plt.subplots(2, 3, figsize=(16, 9.5))
    flat_axes = list(axes.flat)

    legend_handles = None
    for idx, (w_key, w_label) in enumerate(workloads):
        ax = flat_axes[idx]
        x = np.arange(len(storages))
        width = 0.24
        offsets = (-width, 0.0, width)

        max_val = 0.0
        min_pos = float("inf")

        for p_idx, (p_key, p_label, p_color) in enumerate(
            zip(PERCENTILE_KEYS, PERCENTILE_LABELS, PERCENTILE_COLORS)
        ):
            vals = [
                float(results.get(w_key, {}).get(s, {}).get(p_key, 0.0))
                for s in storages
            ]
            for v in vals:
                max_val = max(max_val, v)
                if v > 0:
                    min_pos = min(min_pos, v)

            bars = ax.bar(
                x + offsets[p_idx],
                vals,
                width=width * 0.9,
                label=p_label,
                color=p_color,
                edgecolor="#2c3e50",
                linewidth=0.5,
            )
            for bar, val in zip(bars, vals):
                ax.annotate(
                    _format_value(val),
                    xy=(bar.get_x() + bar.get_width() / 2.0, val),
                    xytext=(0, 4),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    rotation=90,
                    fontsize=7.5,
                    fontweight="bold",
                )

        if idx == 0:
            legend_handles, _ = ax.get_legend_handles_labels()

        use_log = min_pos < float("inf") and max_val / max(min_pos, 1e-6) > 20
        if use_log:
            ax.set_yscale("log")
            ax.set_ylim(bottom=max(min_pos * 0.4, 0.05), top=max_val * 5.0)
        else:
            ax.set_ylim(0, max_val * 1.45 if max_val > 0 else 10)

        ax.set_xticks(x)
        ax.set_xticklabels(
            [STORAGE_LABELS.get(s, s) for s in storages],
            fontsize=9,
        )
        ax.set_ylabel("Latency (ms)", fontsize=9.5)
        ax.set_title(w_label.replace("\n", " "), fontsize=11, fontweight="bold", pad=8)
        ax.grid(axis="y", linestyle="--", alpha=0.35, which="both")
        ax.set_axisbelow(True)

    # Use remaining empty subplot panel(s) for clean legend & context
    for empty_idx in range(len(workloads), len(flat_axes)):
        ax = flat_axes[empty_idx]
        ax.axis("off")
        if empty_idx == len(workloads) and legend_handles:
            ax.legend(
                legend_handles,
                ["avg latency (ms)", "p95 latency (ms)", "p99 latency (ms)"],
                loc="center",
                fontsize=11,
                frameon=True,
                title="Latency Percentiles",
                title_fontsize=12,
            )

    fig.suptitle(
        "S3 Storage Solutions — Latency Percentiles (avg / p95 / p99)",
        fontsize=14,
        fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def generate_all_charts(
    results_data: Dict[str, Any],
    output_dir: Union[str, Path],
) -> List[Path]:
    """Generate throughput, IOPS, and latency percentile charts in `output_dir`."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return [
        plot_throughput_comparison(results_data, out_dir / "throughput_comparison.png"),
        plot_iops_comparison(results_data, out_dir / "iops_comparison.png"),
        plot_latency_percentiles(results_data, out_dir / "latency_percentiles.png"),
    ]
