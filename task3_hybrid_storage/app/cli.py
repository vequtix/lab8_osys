"""Interactive CLI for TechData Solutions Hybrid Storage Manager."""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.hybrid_storage import HybridStorageManager

_SIZE_TOKEN_RE = re.compile(r"^(\d+(?:\.\d+)?)(?:mb)?$", re.IGNORECASE)

HELP_TEXT = """Available commands:
  put <filename> <content_or_size_mb>  Write text content or <N>[MB] synthetic asset to HOT
  get <filename>                       Read file (auto-promotes WARM/COLD -> HOT)
  status                               Show files table & per-tier capacity summary
  migrate                              Run tiering migration (HOT->WARM >7d, WARM->COLD >30d)
  age <filename> <days>                Shift last_accessed backward by <days> for demo
  history                              Show full migration & access audit log
  delete <filename>                    Remove file from storage & metadata
  help                                 Show this help message
  exit | quit                          Exit CLI
"""


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.2f} KiB"
    return f"{num_bytes / (1024 * 1024):.2f} MiB"


def _print_status(manager: HybridStorageManager) -> None:
    st = manager.get_status()
    files = st["files"]
    tiers = st["tiers"]

    print("\n=== Hybrid Storage Inventory ===")
    if not files:
        print("  (no files stored)")
    else:
        header = (
            f"{'Filename':<22} {'Tier':<6} {'Size':>11} "
            f"{'Age(d)':>8} {'Hits':>5} {'MD5 Checksum':<34} {'OnDisk':<6}"
        )
        print(header)
        print("-" * len(header))
        for item in files:
            print(
                f"{item['filename']:<22} {item['tier'].upper():<6} "
                f"{_format_size(item['size']):>11} {item['age_days']:>8.1f} "
                f"{item['access_count']:>5} {item['checksum']:<34} "
                f"{'OK' if item['exists_on_tier'] else 'MISS':<6}"
            )

    print("\n--- Tier Summary ---")
    for tier_name in ("hot", "warm", "cold"):
        summary = tiers[tier_name]
        print(
            f"  {tier_name.upper():<5}: {summary['count']:>3} file(s), "
            f"{_format_size(summary['bytes'])}"
        )
    print(
        f"Policies: HOT->WARM after {st['hot_to_warm_days']:.0f}d | "
        f"WARM->COLD after {st['warm_to_cold_days']:.0f}d\n"
    )


def _print_history(manager: HybridStorageManager) -> None:
    events = manager.get_history()
    print("\n=== Operation History ===")
    if not events:
        print("  (no events recorded)\n")
        return

    header = (
        f"{'UTC Timestamp':<20} {'Action':<8} {'Filename':<18} "
        f"{'Transition':<14} {'Size':>10} {'MD5 (short)':<12} {'Details'}"
    )
    print(header)
    print("-" * len(header))
    for ev in events:
        ts_str = datetime.fromtimestamp(ev.timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        if ev.from_tier and ev.to_tier and ev.from_tier != ev.to_tier:
            transition = f"{ev.from_tier.upper()}->{ev.to_tier.upper()}"
        elif ev.to_tier:
            transition = ev.to_tier.upper()
        elif ev.from_tier:
            transition = f"{ev.from_tier.upper()}->DEL"
        else:
            transition = "-"

        print(
            f"{ts_str:<20} {ev.action:<8} {ev.filename:<18} "
            f"{transition:<14} {_format_size(ev.size):>10} "
            f"{ev.checksum[:10]:<12} {ev.details}"
        )
    print()


def _dispatch_parts(manager: HybridStorageManager, parts: List[str]) -> bool:
    """Dispatch parsed command tokens `[cmd, ...rest]`. Returns False on exit."""
    if not parts:
        return True

    cmd = parts[0].lower()

    if cmd in {"exit", "quit"}:
        return False

    if cmd == "help":
        print(HELP_TEXT)
        return True

    if cmd == "status":
        _print_status(manager)
        return True

    if cmd == "migrate":
        migrations = manager.migrate()
        if not migrations:
            print("No files eligible for migration.")
        else:
            for m in migrations:
                print(
                    f"[MIGRATE] {m['filename']}: "
                    f"{m['from_tier'].upper()} -> {m['to_tier'].upper()} "
                    f"(age={m['age_days']:.1f}d, size={_format_size(m['size'])}, "
                    f"MD5={m['checksum']} verified)"
                )
        return True

    if cmd == "history":
        _print_history(manager)
        return True

    if cmd == "put":
        if len(parts) < 3:
            raise ValueError("Usage: put <filename> <content_or_size_mb>")
        filename, value = parts[1], parts[2]
        match = _SIZE_TOKEN_RE.match(value.strip())
        if match:
            size_mb = float(match.group(1))
            meta = manager.put_sized(filename, size_mb)
        else:
            meta = manager.put(filename, value.encode("utf-8"))
        print(
            f"[PUT] {meta.filename} -> {meta.tier.value.upper()} "
            f"({_format_size(meta.size)}, MD5={meta.checksum})"
        )
        return True

    if cmd == "get":
        if len(parts) < 2:
            raise ValueError("Usage: get <filename>")
        filename = parts[1]
        data, info = manager.get_with_info(filename)
        if data is None or info is None:
            raise FileNotFoundError(f"File not found: {filename}")
        meta = info["meta"]
        if info["promoted_from"]:
            print(
                f"[AUTO-PROMOTE] {meta.filename}: "
                f"{info['promoted_from'].upper()} -> HOT (MD5 verified)"
            )
        preview: Optional[str] = None
        if len(data) <= 512:
            try:
                decoded = data.decode("utf-8")
                if decoded.isprintable() or "\n" in decoded:
                    preview = decoded
            except UnicodeDecodeError:
                preview = None
        if preview is not None:
            print(
                f"[GET] {meta.filename} (tier={meta.tier.value.upper()}, "
                f"hits={meta.access_count}, MD5={meta.checksum}): {preview}"
            )
        else:
            print(
                f"[GET] {meta.filename} (tier={meta.tier.value.upper()}, "
                f"size={_format_size(len(data))}, hits={meta.access_count}, "
                f"MD5={meta.checksum} verified)"
            )
        return True

    if cmd == "age":
        if len(parts) < 3:
            raise ValueError("Usage: age <filename> <days>")
        filename = parts[1]
        days = float(parts[2])
        meta = manager.age_file(filename, days)
        print(
            f"[AGE] {meta.filename}: shifted last_accessed back by {days:.1f}d "
            f"(tier={meta.tier.value.upper()})"
        )
        return True

    if cmd == "delete":
        if len(parts) < 2:
            raise ValueError("Usage: delete <filename>")
        filename = parts[1]
        if manager.delete(filename):
            print(f"[DELETE] Removed {filename}")
        else:
            raise FileNotFoundError(f"File not found: {filename}")
        return True

    raise ValueError(f"Unknown command: {cmd!r}. Type 'help' for commands.")


def execute_line(manager: HybridStorageManager, line: str) -> bool:
    """Execute one CLI command line. Returns False if exit requested."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return True
    return _dispatch_parts(manager, stripped.split(None, 2))


def main(argv: Optional[Sequence[str]] = None) -> int:
    hot_path = os.environ.get("HOT_PATH", "/data/hot")
    warm_path = os.environ.get("WARM_PATH", "/data/warm")
    cold_path = os.environ.get("COLD_PATH", "/data/cold")
    manager = HybridStorageManager(hot_path, warm_path, cold_path)

    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        parts = args if len(args) <= 2 else [args[0], args[1], " ".join(args[2:])]
        try:
            _dispatch_parts(manager, parts)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        return 0

    interactive = sys.stdin.isatty()
    if interactive:
        print(
            "TechData Solutions — Hybrid Storage Manager CLI\n"
            f"Tiers: HOT={hot_path} | WARM={warm_path} | COLD={cold_path}\n"
            "Type 'help' for available commands."
        )

    while True:
        try:
            line = input("hybrid> ") if interactive else sys.stdin.readline()
            if not interactive and line == "":
                break
        except (EOFError, KeyboardInterrupt):
            if interactive:
                print()
            break

        try:
            keep_going = execute_line(manager, line)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            keep_going = True

        if not keep_going:
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
