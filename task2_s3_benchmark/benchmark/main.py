"""CLI entrypoint for running S3 FUSE vs native boto3 benchmarks."""

from __future__ import annotations

import argparse
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from benchmark.filesystem import create_fs_benchmark
from benchmark.metrics import load_results_json, save_results_json
from benchmark.native_s3 import create_native_s3_benchmark
from benchmark.visualize import generate_all_charts
from benchmark.workloads import WORKLOADS, get_workloads


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark s3fs-fuse, goofys, and native boto3 against MinIO."
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Scale iteration counts down by 10x for fast verification.",
    )
    parser.add_argument(
        "--workloads",
        nargs="+",
        choices=[w.key for w in WORKLOADS],
        help="Subset of workload keys to execute.",
    )
    parser.add_argument(
        "--storages",
        nargs="+",
        choices=["s3fs", "goofys", "boto3"],
        default=["s3fs", "goofys", "boto3"],
        help="Storage backends to benchmark (default: all three).",
    )
    parser.add_argument(
        "--s3fs-mount",
        default=os.environ.get("S3FS_MOUNT", "/mnt/s3fs"),
        help="Path where s3fs is mounted.",
    )
    parser.add_argument(
        "--goofys-mount",
        default=os.environ.get("GOOFYS_MOUNT", "/mnt/goofys"),
        help="Path where goofys is mounted.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("S3_ENDPOINT", "http://minio:9000"),
        help="MinIO/S3 endpoint URL.",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("S3_BUCKET", "benchmark"),
        help="Target S3 bucket name.",
    )
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Directory for results.json and generated PNG charts.",
    )
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="Regenerate PNG charts from existing <output-dir>/results.json.",
    )
    return parser.parse_args(argv)


def _print_summary_table(results: Dict[str, Dict[str, Any]]) -> None:
    header = (
        f"{'Workload':<18} {'Storage':<8} {'Iter':>5} {'Time(s)':>8} "
        f"{'MB/s':>9} {'IOPS':>9} {'Avg(ms)':>9} {'P95(ms)':>9} {'P99(ms)':>9} {'Err':>4}"
    )
    print("\n" + "=" * len(header))
    print(header)
    print("-" * len(header))
    for w_key, storages_map in results.items():
        for s_key, item in storages_map.items():
            print(
                f"{w_key:<18} {s_key:<8} {item['iterations']:>5} "
                f"{item['total_time_sec']:>8.2f} {item['throughput_mbps']:>9.2f} "
                f"{item['iops']:>9.1f} {item['latency_avg_ms']:>9.2f} "
                f"{item['latency_p95_ms']:>9.2f} {item['latency_p99_ms']:>9.2f} "
                f"{item['errors']:>4}"
            )
    print("=" * len(header) + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.output_dir)
    results_json_path = out_dir / "results.json"

    if args.plot_only:
        payload = load_results_json(results_json_path)
        charts = generate_all_charts(payload, out_dir)
        for chart in charts:
            print(f"Generated chart: {chart}")
        return 0

    s3_config = {
        "endpoint": args.endpoint,
        "bucket": args.bucket,
        "access_key": os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
        "secret_key": os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin123"),
        "region": os.environ.get("AWS_REGION", "us-east-1"),
    }

    mount_paths = {
        "s3fs": args.s3fs_mount,
        "goofys": args.goofys_mount,
    }

    for storage in args.storages:
        if storage in mount_paths and not os.path.ismount(mount_paths[storage]):
            print(
                f"WARNING: {mount_paths[storage]} does not report as a mountpoint.",
                file=sys.stderr,
            )

    workloads = get_workloads(quick=args.quick, selected=args.workloads)
    all_results: Dict[str, Dict[str, Any]] = {}
    any_errors = False

    for spec in workloads:
        all_results[spec.key] = {}
        for storage in args.storages:
            print(
                f"Running [{spec.label}] on [{storage}] "
                f"({spec.iterations} iterations)..."
            )
            if storage == "boto3":
                bench = create_native_s3_benchmark(spec, s3_config)
            else:
                bench = create_fs_benchmark(
                    storage=storage,
                    mount_path=mount_paths[storage],
                    workload=spec,
                    s3_config=s3_config,
                )

            res = bench.run(iterations=spec.iterations)
            all_results[spec.key][storage] = res.to_dict()
            if res.errors > 0:
                any_errors = True
            print(
                f"  -> time={res.total_time_sec:.2f}s, "
                f"throughput={res.throughput_mbps:.2f} MB/s, "
                f"iops={res.iops:.1f}, "
                f"avg={res.latency_avg_ms:.2f}ms, "
                f"p95={res.latency_p95_ms:.2f}ms, "
                f"p99={res.latency_p99_ms:.2f}ms, "
                f"errors={res.errors}"
            )

    payload = {
        "metadata": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "quick": args.quick,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "endpoint": args.endpoint,
            "bucket": args.bucket,
            "storages": list(args.storages),
            "workloads": [w.key for w in workloads],
        },
        "results": all_results,
    }

    saved_json = save_results_json(payload, results_json_path)
    print(f"Saved raw results to {saved_json}")
    _print_summary_table(all_results)

    charts: List[Path] = generate_all_charts(payload, out_dir)
    for chart in charts:
        print(f"Generated chart: {chart}")

    return 1 if any_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
