from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from . import cloud_client, compute, hardware, media_transfer
from .analyzer import find_highlights, sequential_highlights
from .transcriber import transcribe_segments, transcribe_words
from . import face_tracking

Progress = Callable[[float, str], None]


def _nodes(profile: dict[str, Any]) -> list[compute.ComputeNode]:
    nodes = compute.local_nodes(profile)
    if cloud_client.configured():
        nodes.append(cloud_client.cloud_node())
    return nodes


def _identity(path: Path, suffix: str) -> str:
    stat = path.stat()
    return hashlib.sha256(f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{suffix}".encode()).hexdigest()


def cloud_render_available(mode: str) -> bool:
    """Cloud/Híbrido deliberately make Lightning the primary renderer."""
    return str(mode or "auto").lower() in {"cloud", "hybrid"} and cloud_client.configured() and bool(cloud_client.health(timeout=2.5).get("ok"))


def render_adaptive(
    source: Path,
    out_path: Path,
    *,
    render_kind: str,
    payload: dict[str, Any],
    profile: dict[str, Any],
    mode: str = "auto",
    project_id: str | None = None,
    clip_id: str | None = None,
    progress: Progress | None = None,
    cancel_check: Callable[[], bool] | None = None,
    local_renderer=None,
) -> tuple[dict, dict]:
    """Render remotely for Cloud/Híbrido, keeping local encoding as the safe default."""
    if local_renderer is None:
        raise ValueError("local_renderer obrigatório")
    source = Path(source)
    units = max(0.1, float(payload.get("end") or 0) - float(payload.get("start") or 0))
    task_id = compute.create_task(
        project_id=project_id, clip_id=clip_id, task_type="render", units=units,
        input_hash=_identity(source, f"render:{render_kind}:{json.dumps(payload, sort_keys=True, ensure_ascii=False)}"),
    )
    remote = cloud_render_available(mode)
    selected = "cloud_cpu" if remote else "local_cpu"
    decision = {
        "task_type": "render", "selected": selected, "selected_id": "lightning_free_cpu" if remote else "local_cpu",
        "mode": mode, "primary": "lightning" if remote else "local", "created_at": compute.now_iso(),
    }
    compute.log_decision(task_id, decision)
    compute.update_task(task_id, state="running", node_kind=selected)
    started = time.monotonic()
    try:
        if remote:
            def cb(fraction: float, message: str) -> None:
                compute.update_task(task_id, progress=fraction)
                if progress: progress(fraction, f"Lightning CPU grátis · {message}")
            job_id = cloud_client.submit_task(
                "render", {**payload, "render_kind": render_kind}, media_path=source,
                idempotency_key=_identity(source, f"render:{render_kind}:{json.dumps(payload, sort_keys=True, ensure_ascii=False)}"), progress=cb,
            )
            result = cloud_client.wait_job(job_id, progress=cb, cancel_check=cancel_check)
            cloud_client.download_result_file(job_id, out_path)
            result = dict(result or {})
            result.setdefault("encoder", "lightning-cpu")
        else:
            result = dict(local_renderer() or {})
        elapsed = max(.001, time.monotonic() - started)
        compute.record_sample(node_kind=selected, task_type="render", units=units, seconds=elapsed, metadata={"project_id": project_id, "remote": remote})
        compute.update_task(task_id, state="done", progress=1, result={"node": selected, "encoder": result.get("encoder")})
        return result, {**decision, "task_id": task_id}
    except Exception as exc:
        compute.update_task(task_id, state="failed", error=str(exc))
        if remote:
            raise RuntimeError(f"Renderização na CPU Cloud falhou: {exc}") from exc
        raise


def transcribe_segments_adaptive(
    source: Path,
    language: str | None,
    *,
    profile: dict[str, Any],
    local_backend_id: str | None,
    mode: str = "auto",
    progress: Progress | None = None,
    cancel_check: Callable[[], bool] | None = None,
    project_id: str | None = None,
    local_transcriber=None,
) -> tuple[dict, dict]:
    audio = None
    transfer_bytes = 0
    if cloud_client.configured():
        try:
            audio = media_transfer.extract_cloud_audio(source)
            transfer_bytes = audio.stat().st_size
        except Exception:
            audio = None
    units = max(1.0, _probe_duration(source))
    task_id = compute.create_task(project_id=project_id, clip_id=None, task_type="asr_segments", units=units, input_hash=_identity(source, "asr_segments"))
    decision = compute.choose_node("asr_segments", _nodes(profile), units=units, transfer_bytes=transfer_bytes, mode=mode, prefer_hybrid=mode == "hybrid")
    compute.log_decision(task_id, decision)
    selected = decision["selected"]
    started = time.monotonic()
    compute.update_task(task_id, state="running", node_kind=selected)
    local_transcriber = local_transcriber or transcribe_segments
    try:
        if selected == "cloud_cpu" and audio is not None:
            def cb(frac: float, msg: str):
                compute.update_task(task_id, progress=frac)
                if progress: progress(frac, f"Lightning CPU grátis · {msg}")
            result = cloud_client.run_task(
                "asr_segments",
                {"language": language, "model": str((profile.get("transcription") or {}).get("model") or "small")},
                media_path=audio,
                idempotency_key=_identity(source, f"cloud:asr_segments:{language}"),
                progress=cb,
                cancel_check=cancel_check,
            )
        else:
            def local_cb(frac: float, backend: str):
                compute.update_task(task_id, progress=frac)
                if progress: progress(frac, backend)
            result = local_transcriber(source, language=language, progress_callback=local_cb, hardware_profile=profile, backend_id=local_backend_id)
            selected = "local_gpu" if "cuda" in str(result.get("runtime") or "").lower() else "local_cpu"
            compute.update_task(task_id, node_kind=selected)
        elapsed = max(0.001, time.monotonic() - started)
        compute.record_sample(node_kind=selected, task_type="asr_segments", units=units, seconds=elapsed, metadata={"project_id": project_id})
        compute.update_task(task_id, state="done", progress=1.0, result={"backend": result.get("backend"), "node": selected})
        return result, {**decision, "selected": selected, "task_id": task_id}
    except Exception as exc:
        compute.update_task(task_id, state="failed", error=str(exc))
        if selected == "cloud_cpu":
            # Cloud is acceleration only. A failure immediately falls back to local.
            if progress: progress(0.0, "Lightning indisponível · continuando localmente")
            local_started = time.monotonic()
            result = local_transcriber(source, language=language, progress_callback=progress, hardware_profile=profile, backend_id=local_backend_id)
            local_node = "local_gpu" if "cuda" in str(result.get("runtime") or "").lower() else "local_cpu"
            compute.record_sample(node_kind=local_node, task_type="asr_segments", units=units, seconds=max(0.001, time.monotonic()-local_started), metadata={"fallback": True})
            return result, {**decision, "selected": local_node, "fallback_from": "cloud_cpu", "task_id": task_id}
        raise


def transcribe_words_adaptive(
    source: Path, start: float, end: float, language: str | None, *, profile: dict[str, Any], local_backend_id: str | None,
    mode: str = "auto", progress: Progress | None = None, cancel_check: Callable[[], bool] | None = None, project_id: str | None = None,
    local_transcriber=None,
) -> tuple[dict, dict]:
    units = max(0.1, float(end) - float(start))
    audio = None; transfer_bytes = 0
    if cloud_client.configured():
        try:
            full_audio = media_transfer.extract_cloud_audio(source)
            # Faster-whisper can transcribe a time window in worker using FFmpeg extraction.
            audio = full_audio; transfer_bytes = full_audio.stat().st_size
        except Exception:
            pass
    task_id = compute.create_task(project_id=project_id, clip_id=None, task_type="asr_words", units=units, input_hash=_identity(source, f"asr_words:{start:.3f}:{end:.3f}"))
    decision = compute.choose_node("asr_words", _nodes(profile), units=units, transfer_bytes=transfer_bytes, mode=mode, prefer_hybrid=mode == "hybrid")
    compute.log_decision(task_id, decision); selected = decision["selected"]
    started = time.monotonic(); compute.update_task(task_id, state="running", node_kind=selected)
    local_transcriber = local_transcriber or transcribe_words
    try:
        if selected == "cloud_cpu" and audio is not None:
            def cb(frac: float, msg: str):
                compute.update_task(task_id, progress=frac)
                if progress: progress(frac, f"Lightning CPU grátis · {msg}")
            result = cloud_client.run_task(
                "asr_words", {"start": float(start), "end": float(end), "language": language, "model": str((profile.get("transcription") or {}).get("model") or "small")},
                media_path=audio, idempotency_key=_identity(source, f"cloud:asr_words:{start:.3f}:{end:.3f}:{language}"), progress=cb, cancel_check=cancel_check,
            )
        else:
            def local_cb(frac: float, backend: str):
                compute.update_task(task_id, progress=frac)
                if progress: progress(frac, backend)
            result = local_transcriber(source, start, end, language=language, progress_callback=local_cb, hardware_profile=profile, backend_id=local_backend_id)
            selected = "local_gpu" if "cuda" in str(result.get("runtime") or "").lower() else "local_cpu"
            compute.update_task(task_id, node_kind=selected)
        compute.record_sample(node_kind=selected, task_type="asr_words", units=units, seconds=max(0.001,time.monotonic()-started))
        compute.update_task(task_id, state="done", progress=1.0, result={"backend": result.get("backend"), "node": selected})
        return result, {**decision, "selected": selected, "task_id": task_id}
    except Exception as exc:
        compute.update_task(task_id, state="failed", error=str(exc))
        if selected == "cloud_cpu":
            if progress: progress(0.0, "Lightning indisponível · refinando legenda localmente")
            result = local_transcriber(source, start, end, language=language, progress_callback=progress, hardware_profile=profile, backend_id=local_backend_id)
            local_node = "local_gpu" if "cuda" in str(result.get("runtime") or "").lower() else "local_cpu"
            return result, {**decision, "selected": local_node, "fallback_from": "cloud_cpu", "task_id": task_id}
        raise


def highlights_adaptive(transcript: dict, settings: dict, *, mode: str = "auto", project_id: str | None = None, local_find=None, local_sequential=None) -> tuple[list[dict], dict]:
    text_size = len(json.dumps(transcript, ensure_ascii=False).encode("utf-8"))
    task_id = compute.create_task(project_id=project_id, clip_id=None, task_type="highlights", units=max(1.0, text_size/1_000_000), metadata={"text_bytes": text_size})
    decision = compute.choose_node("highlights", _nodes(hardware.load_or_build_profile()), units=max(1.0, text_size/1_000_000), transfer_bytes=text_size, mode=mode, prefer_hybrid=mode == "hybrid")
    compute.log_decision(task_id, decision); selected = decision["selected"]; compute.update_task(task_id, state="running", node_kind=selected)
    started = time.monotonic()
    local_find = local_find or find_highlights
    local_sequential = local_sequential or sequential_highlights
    try:
        project_mode = str(settings.get("mode") or "smart")
        if selected == "cloud_cpu":
            result = cloud_client.run_task("highlights", {"transcript": transcript, "settings": settings}, idempotency_key=hashlib.sha256(json.dumps({"t": transcript, "s": settings}, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
            candidates = result.get("candidates") or []
        elif project_mode == "sequential":
            candidates = local_sequential(transcript, float(settings.get("target_duration", 60)))
        else:
            candidates = local_find(transcript, num_clips=int(settings.get("num_clips", 5)), min_duration=float(settings.get("min_duration",20)), max_duration=float(settings.get("max_duration",90)), custom_keywords=settings.get("custom_keywords","") or settings.get("prompt", ""), use_llm=bool(settings.get("use_llm", True)))
        compute.record_sample(node_kind=selected, task_type="highlights", units=max(1.0,text_size/1_000_000), seconds=max(.001,time.monotonic()-started))
        compute.update_task(task_id, state="done", progress=1.0, result={"count": len(candidates), "node": selected})
        return candidates, {**decision, "task_id": task_id}
    except Exception as exc:
        compute.update_task(task_id, state="failed", error=str(exc))
        # Always fallback to the proven local analyzer.
        project_mode = str(settings.get("mode") or "smart")
        if project_mode == "sequential": candidates = local_sequential(transcript, float(settings.get("target_duration",60)))
        else: candidates = local_find(transcript, num_clips=int(settings.get("num_clips",5)), min_duration=float(settings.get("min_duration",20)), max_duration=float(settings.get("max_duration",90)), custom_keywords=settings.get("custom_keywords","") or settings.get("prompt", ""), use_llm=bool(settings.get("use_llm",True)))
        return candidates, {**decision, "selected": "local_cpu", "fallback_from": selected, "task_id": task_id}


def track_window_adaptive(
    source: Path, start: float, end: float, *, out_path: Path, fps: float, analysis_width: int, profile: dict[str, Any], mode: str = "auto",
    progress: Progress | None = None, cancel_check: Callable[[], bool] | None = None, project_id: str | None = None,
    local_tracker=None, detector_backend: str = "auto",
) -> tuple[dict, dict]:
    units = max(.1, float(end)-float(start))
    proxy = None; transfer_bytes = 0
    if cloud_client.configured():
        try:
            proxy = media_transfer.extract_proxy_window(source, start, end, max_width=min(640, analysis_width))
            transfer_bytes = proxy.stat().st_size
        except Exception:
            pass
    task_id = compute.create_task(project_id=project_id, clip_id=None, task_type="tracking", units=units, input_hash=_identity(source, f"tracking:{start}:{end}:{fps}:{analysis_width}"))
    decision = compute.choose_node("tracking", _nodes(profile), units=units, transfer_bytes=transfer_bytes, mode=mode, prefer_hybrid=mode=="hybrid")
    compute.log_decision(task_id, decision); selected=decision["selected"]; compute.update_task(task_id,state="running",node_kind=selected)
    started=time.monotonic()
    local_tracker = local_tracker or face_tracking.analyze_window
    try:
        if selected=="cloud_cpu" and proxy is not None:
            def cb(frac: float, msg: str):
                compute.update_task(task_id, progress=frac)
                if progress: progress(frac, f"Lightning CPU grátis · {msg}")
            data=cloud_client.run_task("tracking", {"fps":fps,"analysis_width":analysis_width}, media_path=proxy, idempotency_key=_identity(proxy,f"tracking:{fps}:{analysis_width}"), progress=cb,cancel_check=cancel_check)
            # Proxy starts at local t=0. Shift samples back to source timeline.
            for tr in data.get("tracks") or []:
                for sample in tr.get("samples") or []:
                    sample["t"] = round(float(sample.get("t") or 0) + float(start), 4)
            data["source_start"] = float(start); data["source_end"] = float(end); data["remote_proxy"] = True
            out_path.parent.mkdir(parents=True,exist_ok=True); out_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        else:
            def local_cb(frac: float, backend: str):
                compute.update_task(task_id, progress=frac)
                if progress: progress(frac, backend)
            data=local_tracker(source,start,end,out_path=out_path,fps=fps,analysis_width=analysis_width,detector_backend=detector_backend,progress_callback=local_cb,cancel_check=cancel_check)
            selected="local_gpu" if str(data.get("backend") or "").lower() in {"yunet-cuda","cuda"} else "local_cpu"
            compute.update_task(task_id,node_kind=selected)
        compute.record_sample(node_kind=selected,task_type="tracking",units=units,seconds=max(.001,time.monotonic()-started))
        compute.update_task(task_id,state="done",progress=1.0,result={"backend":data.get("backend"),"node":selected})
        return data,{**decision,"selected":selected,"task_id":task_id}
    except Exception as exc:
        compute.update_task(task_id,state="failed",error=str(exc))
        if selected=="cloud_cpu":
            if progress: progress(0.0,"Lightning indisponível · tracking local")
            data=local_tracker(source,start,end,out_path=out_path,fps=fps,analysis_width=analysis_width,detector_backend=detector_backend,progress_callback=progress,cancel_check=cancel_check)
            return data,{**decision,"selected":"local_cpu","fallback_from":"cloud_cpu","task_id":task_id}
        raise


def _probe_duration(source: Path) -> float:
    try:
        from .render import probe_video
        return max(0.1, float(probe_video(source).get("duration") or 0.1))
    except Exception:
        return 1.0
