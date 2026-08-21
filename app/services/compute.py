from __future__ import annotations

import json
import math
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from app.db import execute, fetchall, fetchone, now_iso
from . import hardware

TASK_TYPES = {
    "asr_segments",
    "asr_words",
    "highlights",
    "tracking",
    "render",
    "thumbnail",
    "embeddings",
    "quality",
}

HEAVY_TASKS = {"asr_segments", "asr_words", "tracking", "render", "embeddings"}
CLOUD_ALLOWED_TASKS = {"asr_segments", "asr_words", "highlights", "tracking", "render", "embeddings"}

# Conservative multipliers. They are continuously corrected by real samples.
DEFAULT_SPEED = {
    ("local_cpu", "asr_segments"): 0.65,
    ("local_cpu", "asr_words"): 0.52,
    ("local_cpu", "tracking"): 0.80,
    ("local_cpu", "render"): 1.00,
    ("local_cpu", "highlights"): 30.0,
    ("local_gpu", "asr_segments"): 4.0,
    ("local_gpu", "asr_words"): 3.2,
    ("local_gpu", "tracking"): 3.5,
    ("local_gpu", "render"): 5.0,
    ("cloud_cpu", "asr_segments"): 1.30,
    ("cloud_cpu", "asr_words"): 1.05,
    ("cloud_cpu", "tracking"): 0.95,
    ("cloud_cpu", "render"): 0.85,
    ("cloud_cpu", "highlights"): 35.0,
    ("cloud_cpu", "embeddings"): 1.0,
}

@dataclass
class ComputeNode:
    id: str
    kind: str
    label: str
    online: bool
    free_only: bool = True
    busy: bool = False
    queue_depth: int = 0
    speed: float = 1.0
    wake_seconds: float = 0.0
    transfer_mbps: float = 0.0
    details: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["details"] = data.get("details") or {}
        return data


def _avg_sample(node_kind: str, task_type: str) -> float | None:
    row = fetchone(
        """
        SELECT AVG(speed) AS avg_speed FROM performance_samples
        WHERE node_kind=? AND task_type=? AND ok=1 AND speed>0 AND created_at >= datetime('now','-30 days')
        """,
        (node_kind, task_type),
    )
    if not row:
        return None
    try:
        value = float(row["avg_speed"] or 0)
        return value if value > 0 else None
    except Exception:
        return None


def record_sample(
    *, node_kind: str, task_type: str, units: float, seconds: float,
    ok: bool = True, metadata: dict[str, Any] | None = None,
) -> None:
    if task_type not in TASK_TYPES or seconds <= 0:
        return
    speed = max(0.0, float(units)) / max(0.001, float(seconds))
    execute(
        "INSERT INTO performance_samples(id,node_kind,task_type,units,seconds,speed,ok,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, node_kind, task_type, float(units), float(seconds), speed, 1 if ok else 0,
         json.dumps(metadata or {}, ensure_ascii=False), now_iso()),
    )


def local_nodes(profile: dict[str, Any] | None = None) -> list[ComputeNode]:
    profile = profile or hardware.load_or_build_profile()
    load = hardware.runtime_load()
    cpu_threads = int(profile.get("cpu_threads") or os.cpu_count() or 1)
    gpu_vendor = str(profile.get("gpu_vendor") or "cpu")
    gpu_name = str(profile.get("gpu_name") or "")
    render = profile.get("render") or {}
    cpu_load = float(load.get("cpu_percent") or 0.0)
    # Keep an overloaded PC responsive. This multiplier feeds ETA rather than
    # disabling local processing, so local remains a guaranteed fallback.
    cpu_factor = max(0.22, 1.0 - max(0.0, cpu_load - 25.0) / 105.0)
    nodes = [ComputeNode(
        id="local_cpu", kind="local_cpu", label=f"CPU local · {cpu_threads} threads", online=True,
        busy=cpu_load >= 85.0, speed=cpu_factor,
        details={"threads": cpu_threads, "ram_mb": int(profile.get("ram_mb") or 0), **load},
    )]
    if gpu_vendor != "cpu":
        gpu_load = load.get("gpu_percent")
        gpu_factor = 1.0 if gpu_load is None else max(0.22, 1.0 - max(0.0, float(gpu_load) - 25.0) / 105.0)
        nodes.append(ComputeNode(
            id="local_gpu", kind="local_gpu", label=f"GPU local · {gpu_name or gpu_vendor.upper()}", online=True,
            busy=(float(gpu_load) >= 85.0 if gpu_load is not None else False), speed=gpu_factor,
            details={"vendor": gpu_vendor, "name": gpu_name, "vram_mb": int(profile.get("vram_mb") or 0), "encoder": render.get("encoder"), **load},
        ))
    return nodes


def task_speed(node_kind: str, task_type: str) -> float:
    measured = _avg_sample(node_kind, task_type)
    if measured:
        return measured
    return float(DEFAULT_SPEED.get((node_kind, task_type), 1.0))


def estimate_seconds(
    node: ComputeNode,
    task_type: str,
    *, units: float = 1.0,
    transfer_bytes: int = 0,
) -> float:
    speed = max(0.01, task_speed(node.kind, task_type) * max(0.05, float(node.speed or 1.0)))
    compute_seconds = max(0.05, float(units)) / speed
    queue_seconds = max(0, int(node.queue_depth or 0)) * compute_seconds
    transfer_seconds = 0.0
    if transfer_bytes > 0 and node.kind.startswith("cloud"):
        mbps = max(0.1, float(node.transfer_mbps or 20.0))
        transfer_seconds = (float(transfer_bytes) * 8.0 / 1_000_000.0) / mbps
    return float(node.wake_seconds or 0.0) + queue_seconds + compute_seconds + transfer_seconds


def _allowed(node: ComputeNode, task_type: str, mode: str) -> bool:
    mode = (mode or "auto").lower()
    if not node.online:
        return False
    if task_type not in TASK_TYPES:
        return False
    if node.kind == "cloud_gpu":
        return False  # V4.2 FREE CPU ONLY hard safety guard.
    if node.kind.startswith("cloud") and task_type not in CLOUD_ALLOWED_TASKS:
        return False
    if mode == "local":
        return node.kind.startswith("local")
    if mode == "cpu-local":
        return node.kind == "local_cpu"
    if mode == "gpu-local":
        return node.kind == "local_gpu" or (node.kind == "local_cpu" and task_type == "highlights")
    if mode == "cloud":
        return node.kind == "cloud_cpu" or node.kind == "local_cpu"  # local remains fail-safe
    return True


def choose_node(
    task_type: str,
    nodes: Iterable[ComputeNode],
    *, units: float = 1.0,
    transfer_bytes: int = 0,
    mode: str = "auto",
    prefer_hybrid: bool = False,
) -> dict[str, Any]:
    candidates = []
    for node in nodes:
        if not _allowed(node, task_type, mode):
            continue
        eta = estimate_seconds(node, task_type, units=units, transfer_bytes=transfer_bytes)
        # Hybrid mode mildly favors an idle cloud node so local and remote work naturally overlap,
        # but only if it is close to the fastest route.
        if prefer_hybrid and node.kind == "cloud_cpu" and not node.busy:
            eta *= 0.92
        if node.busy:
            eta *= 1.08
        candidates.append((eta, node))
    if not candidates:
        fallback = ComputeNode("local_cpu", "local_cpu", "CPU local", True)
        candidates = [(estimate_seconds(fallback, task_type, units=units), fallback)]
    candidates.sort(key=lambda item: item[0])
    eta, selected = candidates[0]
    decision = {
        "task_type": task_type,
        "selected": selected.kind,
        "selected_id": selected.id,
        "eta_seconds": round(eta, 3),
        "mode": mode,
        "candidates": [
            {"node": n.kind, "id": n.id, "label": n.label, "eta_seconds": round(e, 3)}
            for e, n in candidates
        ],
        "created_at": now_iso(),
    }
    return decision


def log_decision(task_id: str | None, decision: dict[str, Any]) -> None:
    execute(
        "INSERT INTO scheduler_decisions(id,task_id,task_type,selected_node,decision_json,created_at) VALUES(?,?,?,?,?,?)",
        (uuid.uuid4().hex, task_id, decision.get("task_type"), decision.get("selected"), json.dumps(decision, ensure_ascii=False), now_iso()),
    )


def create_task(
    *, project_id: str | None, clip_id: str | None, task_type: str,
    units: float = 1.0, input_hash: str | None = None, metadata: dict[str, Any] | None = None,
) -> str:
    task_id = uuid.uuid4().hex
    execute(
        """
        INSERT INTO processing_tasks(id,project_id,clip_id,task_type,state,progress,units,input_hash,metadata_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (task_id, project_id, clip_id, task_type, "queued", 0.0, float(units), input_hash,
         json.dumps(metadata or {}, ensure_ascii=False), now_iso(), now_iso()),
    )
    return task_id


def update_task(task_id: str, *, state: str | None = None, progress: float | None = None, node_kind: str | None = None,
                error: str | None = None, result: dict[str, Any] | None = None) -> None:
    sets: list[str] = ["updated_at=?"]
    params: list[Any] = [now_iso()]
    if state is not None:
        sets.append("state=?"); params.append(state)
        if state == "running": sets.append("started_at=COALESCE(started_at,?)"); params.append(now_iso())
        if state in {"done", "failed", "cancelled"}: sets.append("finished_at=?"); params.append(now_iso())
    if progress is not None:
        sets.append("progress=?"); params.append(max(0.0, min(1.0, float(progress))))
    if node_kind is not None:
        sets.append("node_kind=?"); params.append(node_kind)
    if error is not None:
        sets.append("error_message=?"); params.append(str(error)[:2000])
    if result is not None:
        sets.append("result_json=?"); params.append(json.dumps(result, ensure_ascii=False))
    params.append(task_id)
    execute(f"UPDATE processing_tasks SET {', '.join(sets)} WHERE id=?", params)


def recent_tasks(limit: int = 50) -> list[dict[str, Any]]:
    rows = fetchall("SELECT * FROM processing_tasks ORDER BY created_at DESC LIMIT ?", (max(1, min(500, int(limit))),))
    out = []
    for row in rows:
        item = dict(row)
        try: item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except Exception: item["metadata"] = {}
        try: item["result"] = json.loads(item.pop("result_json") or "{}")
        except Exception: item["result"] = {}
        out.append(item)
    return out


def cache_get(cache_key: str) -> dict[str, Any] | None:
    row = fetchone("SELECT * FROM task_cache WHERE cache_key=?", (cache_key,))
    if not row:
        return None
    path = Path(row["result_path"]) if row["result_path"] else None
    if path and not path.exists():
        execute("DELETE FROM task_cache WHERE cache_key=?", (cache_key,))
        return None
    execute("UPDATE task_cache SET last_used_at=?,hit_count=hit_count+1 WHERE cache_key=?", (now_iso(), cache_key))
    item = dict(row)
    try: item["metadata"] = json.loads(item.get("metadata_json") or "{}")
    except Exception: item["metadata"] = {}
    return item


def cache_put(cache_key: str, task_type: str, *, result_path: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    execute(
        """
        INSERT INTO task_cache(cache_key,task_type,result_path,metadata_json,hit_count,created_at,last_used_at)
        VALUES(?,?,?,?,0,?,?)
        ON CONFLICT(cache_key) DO UPDATE SET task_type=excluded.task_type,result_path=excluded.result_path,metadata_json=excluded.metadata_json,last_used_at=excluded.last_used_at
        """,
        (cache_key, task_type, result_path, json.dumps(metadata or {}, ensure_ascii=False), now_iso(), now_iso()),
    )
