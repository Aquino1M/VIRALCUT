from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, TEMP_DIR, PREVIEW_DIR

MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024
DEFAULT_RESERVE_BYTES = 128 * MIB


class InsufficientDiskSpace(RuntimeError):
    pass


def estimate_temp_bytes(source_size: int) -> int:
    """Conservative local working-set estimate for transcribe/render intermediates."""
    size = max(0, int(source_size or 0))
    return max(128 * MIB, int(size * 1.75))


def evaluate_space(*, source_size: int, free_bytes: int, reserve_bytes: int = DEFAULT_RESERVE_BYTES) -> dict[str, Any]:
    temp_bytes = estimate_temp_bytes(source_size)
    required = temp_bytes + max(0, int(reserve_bytes))
    free = max(0, int(free_bytes))
    return {
        "ok": free >= required,
        "free_bytes": free,
        "required_bytes": required,
        "estimated_temp_bytes": temp_bytes,
        "reserve_bytes": max(0, int(reserve_bytes)),
    }


def storage_snapshot(path: Path | None = None) -> dict[str, Any]:
    target = Path(path or DATA_DIR)
    target.mkdir(parents=True, exist_ok=True)
    total, used, free = shutil.disk_usage(target)
    return {"path": str(target), "total_bytes": total, "used_bytes": used, "free_bytes": free}


def ensure_job_space(source: Path, *, temp_root: Path | None = None, reserve_bytes: int = DEFAULT_RESERVE_BYTES) -> dict[str, Any]:
    source = Path(source)
    root = Path(temp_root or TEMP_DIR)
    root.mkdir(parents=True, exist_ok=True)
    source_size = source.stat().st_size if source.exists() else 0
    snap = storage_snapshot(root)
    result = {**snap, **evaluate_space(source_size=source_size, free_bytes=snap["free_bytes"], reserve_bytes=reserve_bytes)}
    if not result["ok"]:
        need_gb = result["required_bytes"] / GIB
        free_gb = result["free_bytes"] / GIB
        raise InsufficientDiskSpace(
            f"Espaço em disco insuficiente para este job: ~{need_gb:.1f} GB necessários e {free_gb:.1f} GB livres. "
            "Libere espaço ou altere a pasta de dados antes de tentar novamente."
        )
    return result


def cleanup_orphan_temp(*, temp_root: Path | None = None, older_than_seconds: int = 72 * 3600) -> dict[str, int]:
    """Remove only old files below the supplied temporary root; never user uploads."""
    root = Path(temp_root or TEMP_DIR).resolve()
    if not root.exists():
        return {"removed_files": 0, "removed_bytes": 0}
    cutoff = time.time() - max(0, int(older_than_seconds))
    removed_files = 0
    removed_bytes = 0
    for path in list(root.rglob("*")):
        try:
            resolved = path.resolve()
            if root not in resolved.parents:
                continue
            if path.is_file() and os.path.getmtime(path) < cutoff:
                removed_bytes += path.stat().st_size
                path.unlink(missing_ok=True)
                removed_files += 1
        except (FileNotFoundError, OSError):
            continue
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return {"removed_files": removed_files, "removed_bytes": removed_bytes}


def cleanup_default_temporaries() -> dict[str, int]:
    result = cleanup_orphan_temp(temp_root=TEMP_DIR)
    preview = cleanup_orphan_temp(temp_root=PREVIEW_DIR)
    return {
        "removed_files": result["removed_files"] + preview["removed_files"],
        "removed_bytes": result["removed_bytes"] + preview["removed_bytes"],
    }
