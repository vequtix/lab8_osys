"""3-tier Hybrid Storage Manager (HOT / WARM / COLD) with MD5 verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SECONDS_PER_DAY = 86400.0
COPY_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class StorageTier(str, Enum):
    """Storage tiers ordered from fastest/most expensive to slowest/cheapest."""

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


@dataclass
class FileMetadata:
    """Persistent metadata record for a file stored in HybridStorageManager."""

    filename: str
    tier: StorageTier
    size: int
    created_at: float
    last_accessed: float
    access_count: int
    checksum: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["tier"] = self.tier.value
        return data

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "FileMetadata":
        return cls(
            filename=str(raw["filename"]),
            tier=StorageTier(raw["tier"]),
            size=int(raw["size"]),
            created_at=float(raw["created_at"]),
            last_accessed=float(raw["last_accessed"]),
            access_count=int(raw["access_count"]),
            checksum=str(raw["checksum"]),
        )


@dataclass
class HistoryEvent:
    """Audit event for storage operations and tier transitions."""

    timestamp: float
    action: str
    filename: str
    from_tier: Optional[str]
    to_tier: Optional[str]
    size: int
    checksum: str
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "HistoryEvent":
        return cls(
            timestamp=float(raw["timestamp"]),
            action=str(raw["action"]),
            filename=str(raw["filename"]),
            from_tier=raw.get("from_tier"),
            to_tier=raw.get("to_tier"),
            size=int(raw["size"]),
            checksum=str(raw["checksum"]),
            details=str(raw.get("details", "")),
        )


class HybridStorageManager:
    """Manages file placement, lifecycle migration, and auto-promotion across 3 tiers."""

    def __init__(
        self,
        hot_path: str = "/data/hot",
        warm_path: str = "/data/warm",
        cold_path: str = "/data/cold",
        metadata_path: Optional[str] = None,
        hot_to_warm_days: float = 7.0,
        warm_to_cold_days: float = 30.0,
    ) -> None:
        self.paths: Dict[StorageTier, Path] = {
            StorageTier.HOT: Path(hot_path),
            StorageTier.WARM: Path(warm_path),
            StorageTier.COLD: Path(cold_path),
        }
        self.metadata_path = (
            Path(metadata_path)
            if metadata_path is not None
            else self.paths[StorageTier.HOT] / "metadata.json"
        )
        self.hot_to_warm_days = float(hot_to_warm_days)
        self.warm_to_cold_days = float(warm_to_cold_days)

        self.metadata: Dict[str, FileMetadata] = {}
        self.history: List[HistoryEvent] = []

        self._ensure_dirs()
        self.reload()

    def _ensure_dirs(self) -> None:
        for path in self.paths.values():
            path.mkdir(parents=True, exist_ok=True)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_filename(filename: str) -> str:
        clean = filename.strip()
        if (
            not clean
            or "/" in clean
            or "\\" in clean
            or clean in {".", "..", "metadata.json", "metadata.json.tmp"}
        ):
            raise ValueError(f"Invalid filename: {filename!r}")
        return clean

    @staticmethod
    def _compute_md5_bytes(data: bytes) -> str:
        return hashlib.md5(data).hexdigest()

    @staticmethod
    def _compute_md5_file(path: Path) -> str:
        digest = hashlib.md5()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def reload(self) -> None:
        """Load persisted metadata and history from metadata.json."""
        if not self.metadata_path.exists():
            self.metadata = {}
            self.history = []
            return
        raw_text = self.metadata_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            self.metadata = {}
            self.history = []
            return
        payload = json.loads(raw_text)
        self.metadata = {
            name: FileMetadata.from_dict(item)
            for name, item in payload.get("files", {}).items()
        }
        self.history = [
            HistoryEvent.from_dict(ev)
            for ev in payload.get("history", [])
        ]

    def _save_state(self) -> None:
        """Atomically persist metadata and history to metadata.json."""
        payload = {
            "files": {name: meta.to_dict() for name, meta in self.metadata.items()},
            "history": [ev.to_dict() for ev in self.history],
        }
        tmp_path = self.metadata_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp_path, self.metadata_path)

    def _record_event(
        self,
        action: str,
        filename: str,
        from_tier: Optional[StorageTier],
        to_tier: Optional[StorageTier],
        size: int,
        checksum: str,
        details: str = "",
        ts: Optional[float] = None,
    ) -> None:
        self.history.append(
            HistoryEvent(
                timestamp=time.time() if ts is None else float(ts),
                action=action,
                filename=filename,
                from_tier=from_tier.value if from_tier is not None else None,
                to_tier=to_tier.value if to_tier is not None else None,
                size=size,
                checksum=checksum,
                details=details,
            )
        )

    def _cleanup_other_tiers(self, filename: str, keep_tier: StorageTier) -> None:
        for tier, directory in self.paths.items():
            if tier == keep_tier:
                continue
            stale = directory / filename
            if stale.exists():
                stale.unlink()

    def put(self, filename: str, data: bytes) -> FileMetadata:
        """Store `data` in the HOT tier and persist metadata with MD5 checksum."""
        clean = self._validate_filename(filename)
        self.reload()

        target = self.paths[StorageTier.HOT] / clean
        target.write_bytes(data)
        self._cleanup_other_tiers(clean, StorageTier.HOT)

        now = time.time()
        checksum = self._compute_md5_bytes(data)
        meta = FileMetadata(
            filename=clean,
            tier=StorageTier.HOT,
            size=len(data),
            created_at=now,
            last_accessed=now,
            access_count=1,
            checksum=checksum,
        )
        self.metadata[clean] = meta
        self._record_event(
            action="PUT",
            filename=clean,
            from_tier=None,
            to_tier=StorageTier.HOT,
            size=len(data),
            checksum=checksum,
            details="Stored new object in HOT tier",
            ts=now,
        )
        self._save_state()
        return meta

    def put_sized(self, filename: str, size_mb: float) -> FileMetadata:
        """Stream-generate a synthetic file of `size_mb` MiB directly into HOT."""
        if size_mb <= 0:
            raise ValueError("size_mb must be positive")
        clean = self._validate_filename(filename)
        self.reload()

        total_bytes = max(1, int(round(size_mb * 1024 * 1024)))
        target = self.paths[StorageTier.HOT] / clean
        pattern = (
            f"TechDataSolutions:{clean}:".encode("utf-8") + b"0123456789ABCDEF" * 64
        )
        digest = hashlib.md5()
        remaining = total_bytes

        with target.open("wb") as fh:
            while remaining > 0:
                block_len = min(COPY_CHUNK_SIZE, remaining)
                repeats = (block_len // len(pattern)) + 1
                chunk = (pattern * repeats)[:block_len]
                fh.write(chunk)
                digest.update(chunk)
                remaining -= block_len

        self._cleanup_other_tiers(clean, StorageTier.HOT)

        now = time.time()
        checksum = digest.hexdigest()
        meta = FileMetadata(
            filename=clean,
            tier=StorageTier.HOT,
            size=total_bytes,
            created_at=now,
            last_accessed=now,
            access_count=1,
            checksum=checksum,
        )
        self.metadata[clean] = meta
        self._record_event(
            action="PUT",
            filename=clean,
            from_tier=None,
            to_tier=StorageTier.HOT,
            size=total_bytes,
            checksum=checksum,
            details=f"Generated {size_mb:.2f} MiB synthetic video asset in HOT tier",
            ts=now,
        )
        self._save_state()
        return meta

    def _transfer_file(
        self,
        filename: str,
        source_tier: StorageTier,
        target_tier: StorageTier,
        action: str,
        details: str,
    ) -> None:
        meta = self.metadata[filename]
        src_path = self.paths[source_tier] / filename
        dst_path = self.paths[target_tier] / filename

        if not src_path.exists():
            raise FileNotFoundError(
                f"Source file missing on {source_tier.value}: {src_path}"
            )

        # shutil.copyfile avoids EXDEV across filesystems and avoids chmod/utime quirks on s3fs.
        shutil.copyfile(src_path, dst_path)
        actual_md5 = self._compute_md5_file(dst_path)
        if actual_md5 != meta.checksum:
            dst_path.unlink(missing_ok=True)
            raise ValueError(
                f"MD5 mismatch during {action} of {filename} "
                f"({source_tier.value} -> {target_tier.value}): "
                f"expected {meta.checksum}, got {actual_md5}"
            )

        src_path.unlink()
        meta.tier = target_tier
        self._record_event(
            action=action,
            filename=filename,
            from_tier=source_tier,
            to_tier=target_tier,
            size=meta.size,
            checksum=actual_md5,
            details=details,
        )
        self._save_state()

    def _promote(self, filename: str) -> StorageTier:
        meta = self.metadata[filename]
        source_tier = meta.tier
        self._transfer_file(
            filename=filename,
            source_tier=source_tier,
            target_tier=StorageTier.HOT,
            action="PROMOTE",
            details=f"Auto-promoted on read ({source_tier.value} -> hot), MD5 verified",
        )
        return source_tier

    def _demote(self, filename: str, target_tier: StorageTier, age_days: float) -> None:
        meta = self.metadata[filename]
        source_tier = meta.tier
        self._transfer_file(
            filename=filename,
            source_tier=source_tier,
            target_tier=target_tier,
            action="DEMOTE",
            details=(
                f"Migrated after {age_days:.1f}d idle "
                f"({source_tier.value} -> {target_tier.value}), MD5 verified"
            ),
        )

    def get_with_info(
        self, filename: str
    ) -> Tuple[Optional[bytes], Optional[Dict[str, Any]]]:
        """Read file bytes, auto-promoting from WARM/COLD to HOT when needed."""
        clean = self._validate_filename(filename)
        self.reload()

        if clean not in self.metadata:
            return None, None

        meta = self.metadata[clean]
        promoted_from: Optional[StorageTier] = None
        if meta.tier != StorageTier.HOT:
            promoted_from = self._promote(clean)

        hot_file = self.paths[StorageTier.HOT] / clean
        data = hot_file.read_bytes()
        actual_md5 = self._compute_md5_bytes(data)
        if actual_md5 != meta.checksum:
            raise ValueError(
                f"MD5 mismatch reading {clean}: expected {meta.checksum}, got {actual_md5}"
            )

        now = time.time()
        meta.last_accessed = now
        meta.access_count += 1
        detail = (
            f"Read after auto-promote from {promoted_from.value}"
            if promoted_from is not None
            else "Served directly from HOT tier"
        )
        self._record_event(
            action="GET",
            filename=clean,
            from_tier=StorageTier.HOT,
            to_tier=StorageTier.HOT,
            size=len(data),
            checksum=actual_md5,
            details=detail,
            ts=now,
        )
        self._save_state()

        info = {
            "meta": meta,
            "promoted_from": promoted_from.value if promoted_from is not None else None,
            "md5_verified": True,
        }
        return data, info

    def get(self, filename: str) -> Optional[bytes]:
        """Read file bytes (auto-promoting to HOT if located on WARM or COLD)."""
        data, _ = self.get_with_info(filename)
        return data

    def migrate(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Apply tiering policies: HOT -> WARM (>7d) and WARM -> COLD (>30d)."""
        self.reload()
        ref_time = time.time() if now is None else float(now)
        migrations: List[Dict[str, Any]] = []

        for filename in sorted(self.metadata.keys()):
            meta = self.metadata[filename]
            age_days = (ref_time - meta.last_accessed) / SECONDS_PER_DAY

            if meta.tier == StorageTier.HOT and age_days > self.hot_to_warm_days:
                self._demote(filename, StorageTier.WARM, age_days)
                migrations.append(
                    {
                        "filename": filename,
                        "from_tier": StorageTier.HOT.value,
                        "to_tier": StorageTier.WARM.value,
                        "age_days": age_days,
                        "size": meta.size,
                        "checksum": meta.checksum,
                    }
                )
            elif meta.tier == StorageTier.WARM and age_days > self.warm_to_cold_days:
                self._demote(filename, StorageTier.COLD, age_days)
                migrations.append(
                    {
                        "filename": filename,
                        "from_tier": StorageTier.WARM.value,
                        "to_tier": StorageTier.COLD.value,
                        "age_days": age_days,
                        "size": meta.size,
                        "checksum": meta.checksum,
                    }
                )

        return migrations

    def age_file(self, filename: str, days: float) -> FileMetadata:
        """Shift `last_accessed` backward by `days` days for migration demos."""
        clean = self._validate_filename(filename)
        self.reload()
        if clean not in self.metadata:
            raise FileNotFoundError(f"File not found in metadata: {clean}")

        meta = self.metadata[clean]
        meta.last_accessed -= float(days) * SECONDS_PER_DAY
        total_age = (time.time() - meta.last_accessed) / SECONDS_PER_DAY
        self._record_event(
            action="AGE",
            filename=clean,
            from_tier=meta.tier,
            to_tier=meta.tier,
            size=meta.size,
            checksum=meta.checksum,
            details=f"Simulated +{days:.1f}d inactivity (total age {total_age:.1f}d)",
        )
        self._save_state()
        return meta

    def delete(self, filename: str) -> bool:
        """Delete a file from its current tier and remove metadata."""
        clean = self._validate_filename(filename)
        self.reload()
        if clean not in self.metadata:
            return False

        meta = self.metadata.pop(clean)
        target = self.paths[meta.tier] / clean
        if target.exists():
            target.unlink()

        self._record_event(
            action="DELETE",
            filename=clean,
            from_tier=meta.tier,
            to_tier=None,
            size=meta.size,
            checksum=meta.checksum,
            details=f"Removed from {meta.tier.value} tier",
        )
        self._save_state()
        return True

    def get_status(self) -> Dict[str, Any]:
        """Return current file inventory and per-tier capacity summary."""
        self.reload()
        now = time.time()
        tier_summary: Dict[str, Dict[str, int]] = {
            tier.value: {"count": 0, "bytes": 0} for tier in StorageTier
        }
        files_info: List[Dict[str, Any]] = []

        for name in sorted(self.metadata.keys()):
            meta = self.metadata[name]
            age_days = max(0.0, (now - meta.last_accessed) / SECONDS_PER_DAY)
            tier_summary[meta.tier.value]["count"] += 1
            tier_summary[meta.tier.value]["bytes"] += meta.size
            files_info.append(
                {
                    "filename": meta.filename,
                    "tier": meta.tier.value,
                    "size": meta.size,
                    "age_days": age_days,
                    "access_count": meta.access_count,
                    "checksum": meta.checksum,
                    "exists_on_tier": (self.paths[meta.tier] / meta.filename).exists(),
                }
            )

        return {
            "files": files_info,
            "tiers": tier_summary,
            "hot_to_warm_days": self.hot_to_warm_days,
            "warm_to_cold_days": self.warm_to_cold_days,
        }

    def get_history(self) -> List[HistoryEvent]:
        """Return full chronological audit log of storage operations."""
        self.reload()
        return list(self.history)
