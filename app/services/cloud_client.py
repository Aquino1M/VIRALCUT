from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from app.config import (
    LIGHTNING_CLOUD_URL,
    LIGHTNING_CLOUD_TOKEN,
    LIGHTNING_ENABLED,
    LIGHTNING_FREE_CPU_ONLY,
    LIGHTNING_TIMEOUT,
    LIGHTNING_UPLOAD_CHUNK_MB,
)
from . import compute, media_transfer

Progress = Callable[[float, str], None]

@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float = 0.0

_lock = threading.Lock()
_circuit = CircuitState()
_CIRCUIT_FAILURES = 4
_CIRCUIT_COOLDOWN = 60.0


def configured() -> bool:
    return bool(LIGHTNING_ENABLED and LIGHTNING_CLOUD_URL and LIGHTNING_CLOUD_TOKEN)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {LIGHTNING_CLOUD_TOKEN}", "X-ViralClip-Client": "4.2"}


def _base() -> str:
    return LIGHTNING_CLOUD_URL.rstrip("/")


def _response_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("detail", body) if isinstance(body, dict) else body
    except ValueError:
        detail = response.text
    return str(detail).strip().replace("\n", " ")[:500]


def _circuit_available() -> bool:
    with _lock:
        if _circuit.failures < _CIRCUIT_FAILURES:
            return True
        if time.time() - _circuit.opened_at >= _CIRCUIT_COOLDOWN:
            return True
        return False


def _success() -> None:
    with _lock:
        _circuit.failures = 0
        _circuit.opened_at = 0.0


def _failure() -> None:
    with _lock:
        _circuit.failures += 1
        if _circuit.failures >= _CIRCUIT_FAILURES and not _circuit.opened_at:
            _circuit.opened_at = time.time()


def health(*, timeout: float = 3.0) -> dict[str, Any]:
    if not configured():
        return {"ok": False, "status": "not-configured", "free_cpu_only": True}
    if not _circuit_available():
        return {"ok": False, "status": "circuit-open", "free_cpu_only": True}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(f"{_base()}/health", headers=_headers())
            r.raise_for_status()
            data = r.json()
        caps = data.get("capabilities") or {}
        # Hard safety: V4.2 refuses a remote worker that advertises GPU or paid mode.
        if LIGHTNING_FREE_CPU_ONLY and (caps.get("gpu") or str(caps.get("machine_type") or "").lower() not in {"", "cpu", "free-cpu", "free_cpu"}):
            return {"ok": False, "status": "rejected-paid-or-gpu-worker", "free_cpu_only": True, "capabilities": caps}
        media_tools = caps.get("media_tools")
        if isinstance(media_tools, dict) and not all(media_tools.get(tool) for tool in ("ffmpeg", "ffprobe")):
            return {"ok": False, "status": "missing-media-tools", "free_cpu_only": True, "capabilities": caps}
        _success()
        return {"ok": True, "status": data.get("status") or "online", **data, "free_cpu_only": True}
    except Exception as exc:
        _failure()
        return {"ok": False, "status": "offline", "error": f"{type(exc).__name__}: {exc}"[:500], "free_cpu_only": True}


def cloud_node() -> compute.ComputeNode:
    info = health()
    caps = info.get("capabilities") or {}
    queue = info.get("queue") or {}
    return compute.ComputeNode(
        id="lightning_free_cpu",
        kind="cloud_cpu",
        label="Lightning · CPU grátis (4 vCPU)",
        online=bool(info.get("ok")),
        free_only=True,
        busy=bool(queue.get("active") or 0),
        queue_depth=int(queue.get("queued") or 0),
        speed=float(caps.get("speed_factor") or 1.0),
        wake_seconds=float(info.get("wake_seconds") or 0.0),
        transfer_mbps=float(info.get("measured_upload_mbps") or 20.0),
        details={"status": info.get("status"), "cpu_count": caps.get("cpu_count"), "ram_mb": caps.get("ram_mb"), "api_version": caps.get("api_version")},
    )


def _request(method: str, path: str, *, timeout: float | None = None, **kwargs) -> httpx.Response:
    if not configured():
        raise RuntimeError("Lightning CPU grátis não configurada.")
    if not _circuit_available():
        raise RuntimeError("Circuit breaker da Lightning está aberto; usando fallback local.")
    with httpx.Client(timeout=timeout or LIGHTNING_TIMEOUT, follow_redirects=True) as client:
        r = client.request(method, f"{_base()}{path}", headers={**_headers(), **kwargs.pop("headers", {})}, **kwargs)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"CPU Cloud retornou HTTP {r.status_code}: {_response_detail(r)}") from exc
        _success()
        return r


def ensure_uploaded(path: str | Path, *, progress: Progress | None = None) -> dict[str, Any]:
    p = Path(path)
    manifest = media_transfer.file_manifest(p, chunk_size=max(1, LIGHTNING_UPLOAD_CHUNK_MB) * 1024 * 1024)
    init = _request("POST", "/uploads/init", json=manifest).json()
    upload_id = str(init["upload_id"])
    present = {int(x) for x in init.get("present_chunks") or []}
    total = max(1, int(manifest["total_chunks"]))
    chunk_size = int(manifest["chunk_size"])
    for index, data, chunk_hash in media_transfer.iter_chunks(p, chunk_size=chunk_size):
        if index in present:
            if progress: progress((index + 1) / total, f"Cloud upload · {index+1}/{total} reutilizado")
            continue
        headers = {"X-Chunk-SHA256": chunk_hash, "Content-Type": "application/octet-stream"}
        _request("PUT", f"/uploads/{upload_id}/chunks/{index}", content=data, headers=headers, timeout=max(LIGHTNING_TIMEOUT, 300))
        if progress: progress((index + 1) / total, f"Cloud upload · {index+1}/{total}")
    complete = _request("POST", f"/uploads/{upload_id}/complete", json={"sha256": manifest["sha256"]}).json()
    return complete


def submit_task(task_type: str, payload: dict[str, Any], *, media_path: str | Path | None = None, idempotency_key: str | None = None,
                progress: Progress | None = None) -> str:
    media = None
    if media_path:
        media = ensure_uploaded(media_path, progress=progress)
    body = {"task_type": task_type, "payload": payload, "upload_id": media.get("upload_id") if media else None, "free_cpu_only": True}
    key = idempotency_key or uuid.uuid4().hex
    r = _request("POST", "/jobs", json=body, headers={"Idempotency-Key": key})
    return str(r.json()["job_id"])


def wait_job(job_id: str, *, progress: Progress | None = None, cancel_check: Callable[[], bool] | None = None,
             poll_seconds: float = 1.0, timeout_seconds: float = 7200.0) -> dict[str, Any]:
    started = time.monotonic()
    while True:
        if cancel_check and cancel_check():
            try: _request("POST", f"/jobs/{job_id}/cancel", json={})
            except Exception: pass
            raise RuntimeError("Tarefa Cloud cancelada")
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError("Cloud Worker excedeu o tempo limite")
        data = _request("GET", f"/jobs/{job_id}", timeout=15).json()
        state = str(data.get("state") or "")
        frac = max(0.0, min(1.0, float(data.get("progress") or 0.0)))
        if progress: progress(frac, str(data.get("message") or state))
        if state == "done":
            return data.get("result") or {}
        if state in {"failed", "cancelled"}:
            raise RuntimeError(str(data.get("error") or data.get("message") or f"Cloud job {state}"))
        time.sleep(max(0.25, poll_seconds))


def run_task(task_type: str, payload: dict[str, Any], *, media_path: str | Path | None = None,
             idempotency_key: str | None = None, progress: Progress | None = None,
             cancel_check: Callable[[], bool] | None = None) -> dict[str, Any]:
    try:
        job_id = submit_task(task_type, payload, media_path=media_path, idempotency_key=idempotency_key, progress=progress)
        return wait_job(job_id, progress=progress, cancel_check=cancel_check)
    except Exception:
        _failure()
        raise


def download_result_file(job_id: str, destination: str | Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    try:
        with httpx.Client(timeout=max(LIGHTNING_TIMEOUT, 300), follow_redirects=True) as client:
            with client.stream("GET", f"{_base()}/jobs/{job_id}/result-file", headers=_headers()) as response:
                response.raise_for_status()
                with partial.open("wb") as fh:
                    for chunk in response.iter_bytes(1024 * 1024):
                        fh.write(chunk)
        partial.replace(target)
        _success()
        return target
    except Exception:
        partial.unlink(missing_ok=True)
        _failure()
        raise
