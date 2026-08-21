from __future__ import annotations

import json
import shutil
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from app.config import OUTPUT_DIR, TEMP_DIR, THUMB_DIR, COMPUTE_MODE
from app.db import execute, fetchall, fetchone, now_iso
from . import editor as editor_service
from . import auto_edit as auto_edit_service
from . import timeline_render
from . import face_tracking
from . import hardware
from . import job_store
from . import worker_control
from . import disk_manager
from . import asr_cache
from . import asr_benchmark
from . import projects as project_service
from . import viral_score
from . import studio_templates
from . import brand_kits
from . import compute_fabric
from .analyzer import find_highlights, sequential_highlights
from .captions import cues_from_transcript
from .ingest import ingest_upload, ingest_url
from .render import generate_thumbnail, probe_video, render_edited_clip, render_clean_clip
from .transcriber import save_transcript, transcribe_segments, transcribe_words, transcription_model_name

# The target i5-4590 machine should never run two complete project renders at once.
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="viralclip-project")


def _update(project_id: str, status: str | None = None, progress: int | None = None, message: str | None = None, **extra):
    sets, params = [], []
    for key, value in (("status", status), ("progress", progress), ("message", message)):
        if value is not None:
            sets.append(f"{key}=?")
            params.append(value)
    for key, value in extra.items():
        sets.append(f"{key}=?")
        params.append(value)
    sets.append("updated_at=?")
    params.append(now_iso())
    params.append(project_id)
    execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", params)


def submit(project_id: str) -> str:
    job_id = job_store.create_job("project", project_id, message="Aguardando o Local Worker")
    executor.submit(process_project, project_id, job_id)
    return job_id


def recover_interrupted_projects() -> list[str]:
    """Recover project jobs after an unclean shutdown.

    A project queue belongs to the server, not to the browser. Interrupted
    projects are returned to the queue after discarding only partial outputs;
    uploads remain intact and remote sources are downloaded again.
    """
    rows = fetchall("SELECT id,status,progress FROM projects WHERE status IN ('queued','processing') ORDER BY created_at")
    queued: list[str] = []
    for row in rows:
        project_id = str(row["id"])
        if row["status"] == "processing":
            execute("DELETE FROM clips WHERE project_id=?", (project_id,))
            shutil.rmtree(OUTPUT_DIR / project_id, ignore_errors=True)
            shutil.rmtree(TEMP_DIR / project_id, ignore_errors=True)
        _update(project_id, status="queued", progress=0, message="Retomando automaticamente após reinício.")
        queued.append(project_id)
    return queued


def _manual_candidates(raw: str) -> list[dict]:
    out = []
    for i, part in enumerate(raw.split(","), 1):
        part = part.strip()
        if not part or "-" not in part:
            continue
        a, b = part.split("-", 1)
        try:
            start, end = float(a.strip()), float(b.strip())
        except ValueError:
            continue
        if end > start:
            out.append({"start": start, "end": end, "score": 50, "title": f"Corte manual {i}", "hook": "", "reason": "manual"})
    return out


def _candidate_analysis(candidate: dict) -> dict:
    return viral_score.score_clip_payload({
        "title": candidate.get("title") or "",
        "hook": candidate.get("hook") or "",
        "reason": candidate.get("reason") or "",
        "text": candidate.get("text") or "",
        "duration": max(0.0, float(candidate.get("end") or 0) - float(candidate.get("start") or 0)),
        "score": candidate.get("score") or 0,
    })


def _apply_project_studio_defaults(project_row, clip_id: str) -> None:
    user_id = int(project_row["user_id"])
    template_id = project_row["template_id"] if "template_id" in project_row.keys() else None
    brand_kit_id = project_row["brand_kit_id"] if "brand_kit_id" in project_row.keys() else None
    if template_id:
        studio_templates.apply_template(user_id, str(template_id), [clip_id])
    if brand_kit_id:
        brand_kits.apply_brand_kit(user_id, str(brand_kit_id), [clip_id])


def _apply_source_range(candidates: list[dict], settings: dict, source_duration: float = 0.0) -> list[dict]:
    start_limit = max(0.0, float(settings.get("start_range") or 0.0))
    end_limit = float(settings.get("end_range") or 0.0)
    if end_limit <= 0:
        end_limit = source_duration if source_duration > 0 else float("inf")
    ranged = []
    for candidate in candidates:
        start = max(start_limit, float(candidate.get("start", 0)))
        end = min(end_limit, float(candidate.get("end", start)))
        if end - start < 1.0:
            continue
        item = dict(candidate)
        item["start"], item["end"] = start, end
        ranged.append(item)
    return ranged


def _initial_edit_state(settings: dict) -> dict:
    tracks = deepcopy(editor_service.DEFAULT_TRACKS)
    tracks["captions"]["visible"] = bool(settings.get("captions", True))
    caption_config = dict(settings.get("caption_config") or {})
    if settings.get("caption_font"):
        caption_config.setdefault("fontFamily", settings["caption_font"])
    return {
        "caption_preset_id": settings.get("caption_preset_id") or "green-fresh",
        "layout_preset_id": settings.get("layout_preset_id") or "auto",
        "aspect_ratio": settings.get("aspect_ratio") or "9:16",
        "caption_config": caption_config,
        "layout_config": settings.get("layout_config") or {},
        "overlays": settings.get("overlays") or [],
        "tracks": tracks,
    }


def _state_for_candidate(base_state: dict, candidate: dict) -> dict:
    state = deepcopy(base_state)
    layout_id = state.get("layout_preset_id")
    title = str(candidate.get("title") or "").strip()[:110]
    if not title:
        return state
    if any(o.get("autoLayoutTitle") for o in state.get("overlays") or []):
        return state
    positions = {
        "choquei-movimento": {"x": 55, "y": 728, "width": 970, "height": 170, "fontSize": 48},
        "header-news": {"x": 55, "y": 585, "width": 970, "height": 150, "fontSize": 42},
        "story-documentary": {"x": 45, "y": 720, "width": 990, "height": 190, "fontSize": 44, "background": "#DC2626"},
    }
    if layout_id in positions:
        overlay = {
            "type": "text", "text": title.upper(), "color": "#FFFFFF",
            "fontFamily": "Montserrat", "fontWeight": "900", "align": "center",
            "strokeWidth": 1, "zIndex": 65, "autoLayoutTitle": True,
            **positions[layout_id],
        }
        state.setdefault("overlays", []).append(overlay)
    return state



def _apply_project_auto_edit(
    *, clip_id: str, settings: dict, source: Path, video_out: Path, start: float, end: float,
    edit_state: dict, transcript: dict, tracking: dict,
) -> dict | None:
    if not bool(settings.get("auto_edit_enabled", False)):
        return None
    timeline_data = auto_edit_service.build_auto_edit_plan(
        clip_id,
        style=str(settings.get("auto_edit_style") or "podcast-viral"),
        intensity=str(settings.get("auto_edit_intensity") or "normal"),
        options={"broll": True, "sfx": True, "music": True, "effects": True, "filters": True},
    )
    cues = editor_service.list_caption_cues(clip_id)
    return timeline_render.render_timeline_clip(
        source=source, out_path=video_out, start=float(start), end=float(end),
        edit_state=edit_state, timeline_data=timeline_data, caption_cues=cues,
        transcript=transcript, tracking=tracking,
    )



def _pick_highlights_for_two_pass(transcript: dict, settings: dict, source_duration: float | None = None) -> list[dict]:
    mode = str(settings.get("mode") or settings.get("project_mode") or "smart")
    if mode == "manual":
        candidates = _manual_candidates(str(settings.get("manual_ranges") or ""))
    elif mode == "sequential":
        candidates = sequential_highlights(transcript, float(settings.get("target_duration", 60)))
    else:
        candidates = find_highlights(
            transcript,
            num_clips=int(settings.get("num_clips", 5)),
            min_duration=float(settings.get("min_duration", 20)),
            max_duration=float(settings.get("max_duration", 90)),
            custom_keywords=settings.get("custom_keywords", "") or settings.get("prompt", ""),
            use_llm=bool(settings.get("use_llm", True)),
        )
    duration = float(source_duration if source_duration is not None else transcript.get("duration") or 0.0)
    return _apply_source_range(candidates, settings, duration)


def _merge_refined_window(base: dict, refined: dict, start: float, end: float) -> dict:
    out = dict(base)
    kept = []
    for seg in base.get("segments") or []:
        seg_start = float(seg.get("start") or 0.0)
        seg_end = float(seg.get("end") or seg_start)
        if seg_end <= start or seg_start >= end:
            kept.append(dict(seg))
    additions = [dict(seg) for seg in refined.get("segments") or []]
    merged = kept + additions
    merged.sort(key=lambda item: (float(item.get("start") or 0.0), float(item.get("end") or 0.0)))
    for idx, seg in enumerate(merged):
        seg["id"] = idx
    out["segments"] = merged
    if refined.get("language"):
        out["language"] = refined.get("language")
    return out


def _window_transcript(refined: dict, start: float, end: float) -> dict:
    segments = []
    for seg in refined.get("segments") or []:
        s = float(seg.get("start") or 0.0); e = float(seg.get("end") or s)
        if e <= start or s >= end:
            continue
        item = dict(seg)
        item["words"] = [
            dict(w) for w in (seg.get("words") or [])
            if float(w.get("end") or w.get("start") or 0.0) > start and float(w.get("start") or 0.0) < end
        ]
        segments.append(item)
    return {"language": refined.get("language"), "duration": max(0.0, end - start), "segments": segments, "backend": refined.get("backend")}


def run_two_pass_asr_for_candidates(
    source: str | Path,
    settings: dict,
    *,
    hardware_profile: dict | None = None,
    progress_callback=None,
) -> dict:
    """V3.4 two-pass ASR: segments for discovery, words only for chosen clips."""
    source_path = Path(source)
    language = settings.get("language") or None
    profile = hardware_profile or {}
    backend_id = str((profile.get("asr") or {}).get("selected_backend") or "") or None
    model = transcription_model_name(profile)
    use_cache = source_path.exists()

    segment_key = None
    transcript = None
    if use_cache:
        segment_key = asr_cache.segment_cache_key(source_path, model=model, language=language, vad=True)
        transcript = asr_cache.load_segment_transcript(segment_key)
    if transcript is None:
        transcript = transcribe_segments(source, language, progress_callback=progress_callback, hardware_profile=profile, backend_id=backend_id)
        if segment_key:
            asr_cache.save_segment_transcript(segment_key, transcript)

    candidates = _pick_highlights_for_two_pass(transcript, settings)
    refined_global = dict(transcript)
    memo: dict[tuple[int, int], dict] = {}
    for index, candidate in enumerate(candidates, 1):
        start = float(candidate["start"]); end = float(candidate["end"])
        key_tuple = (int(round(start * 1000)), int(round(end * 1000)))
        refined = memo.get(key_tuple)
        cache_key = None
        if refined is None and use_cache:
            cache_key = asr_cache.word_window_cache_key(source_path, start, end, model=model, language=language)
            refined = asr_cache.load_word_window(cache_key)
        if refined is None:
            if progress_callback:
                progress_callback(0.0, f"Refinando legendas · corte {index}/{len(candidates)} · palavras")
            refined = transcribe_words(source, start, end, language=language, progress_callback=progress_callback, hardware_profile=profile, backend_id=backend_id)
            if cache_key:
                asr_cache.save_word_window(cache_key, refined)
        memo[key_tuple] = refined
        candidate["transcript"] = _window_transcript(refined, start, end)
        refined_global = _merge_refined_window(refined_global, refined, start, end)
    return {"transcript": refined_global, "segment_transcript": transcript, "candidates": candidates}

def process_project(project_id: str, job_id: str | None = None) -> None:
    row = fetchone("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        return
    if not job_id:
        latest = job_store.latest_job("project", project_id)
        job_id = latest["id"] if latest and latest.get("status") in {"queued", "running", "paused", "retrying"} else job_store.create_job("project", project_id)
    try:
        settings = project_service.normalize_project_settings(json.loads(row["settings_json"] or "{}"))
    except Exception:
        settings = project_service.normalize_project_settings({})
    control = worker_control.JobControl(job_id)
    user_pref = fetchone("SELECT compute_mode FROM users WHERE id=?", (row["user_id"],))
    compute_mode = str((user_pref["compute_mode"] if user_pref else None) or COMPUTE_MODE or "auto").lower()
    if compute_mode not in {"auto", "hybrid", "cloud", "local", "cpu-local", "gpu-local"}:
        compute_mode = "auto"
    compute_summary: list[dict] = []
    try:
        control.checkpoint()
        _update(project_id, "processing", 2, "Otimizando para este computador")
        job_store.start_stage(job_id, "hardware", total=1.0, message="Detectando CPU, GPU e aceleradores")
        profile = hardware.load_or_build_profile()
        profile_label = str((profile.get("profile") or {}).get("label") or "AUTOMÁTICO")
        backend_label = str((profile.get("transcription") or {}).get("backend") or "cpu")
        encoder_label = str((profile.get("render") or {}).get("encoder") or "libx264")
        job_store.update_stage(job_id, current=1, total=1, backend=str(profile.get("gpu_vendor") or "cpu"), message=f"Perfil {profile_label} · IA {backend_label} · render {encoder_label}")
        job_store.finish_stage(job_id)
        _update(project_id, progress=5, message=f"PC otimizado · {profile_label} · {encoder_label}", hardware_profile_json=json.dumps(profile, ensure_ascii=False))

        work_dir = TEMP_DIR / project_id
        work_dir.mkdir(parents=True, exist_ok=True)
        job_store.start_stage(job_id, "ingest", total=1.0, message="Preparando a fonte")
        if project_service.is_remote_source_type(row["source_type"]):
            _update(project_id, progress=7, message=f"Baixando vídeo de {row['source_type'].upper()}")
            source = ingest_url(row["source_value"], work_dir, cookie_browser=settings.get("youtube_cookies", ""))
        else:
            source = ingest_upload(row["source_path"], work_dir)
        job_store.update_stage(job_id, current=1.0, total=1.0, message="Fonte pronta")
        job_store.finish_stage(job_id)

        control.checkpoint()
        job_store.start_stage(job_id, "storage", total=1.0, message="Verificando espaço em disco")
        storage = disk_manager.ensure_job_space(source, temp_root=work_dir)
        free_gb = float(storage.get("free_bytes") or 0) / (1024 ** 3)
        job_store.update_stage(job_id, current=1.0, total=1.0, message=f"Espaço em disco OK · {free_gb:.1f} GB livres")
        job_store.finish_stage(job_id)

        media = probe_video(source)
        source_duration = float(media.get("duration") or 0)
        if source_duration > 10 * 60 * 60:
            raise RuntimeError("O vídeo ultrapassa o limite de segurança de 10 horas.")
        source_meta = {"provider": row["source_type"], "size": source.stat().st_size if source.exists() else 0, **media}
        project_thumb = THUMB_DIR / f"{project_id}_source.jpg"
        try:
            generate_thumbnail(source, project_thumb, row["title"] or "")
            project_thumb_path = str(project_thumb)
        except Exception:
            project_thumb_path = None
        source_update = {} if row["source_type"] == "upload" else {"source_path": str(source)}
        _update(
            project_id,
            progress=12,
            message=f"Transcrevendo · {backend_label}",
            duration=source_duration or None,
            channel_label=(row["source_type"] or "VIDEO").upper(),
            source_metadata_json=json.dumps(source_meta, ensure_ascii=False),
            thumbnail_path=project_thumb_path,
            **source_update,
        )

        # V3.4 Pass A: fast segment timestamps for the complete source.
        selected_asr = str((profile.get("asr") or {}).get("selected_backend") or "") or None
        model_name = transcription_model_name(profile)
        language = settings.get("language") or None
        segment_key = asr_cache.segment_cache_key(source, model=model_name, language=language, vad=True)
        transcript = asr_cache.load_segment_transcript(segment_key)
        job_store.start_stage(job_id, "transcribe", total=max(1.0, source_duration), backend=selected_asr or backend_label, message="Transcrevendo rápido · segmentos")
        transcribe_started = __import__("time").monotonic()
        if transcript is None:
            def on_transcribe_progress(fraction: float, backend: str) -> None:
                control.checkpoint()
                fraction = max(0.0, min(1.0, float(fraction)))
                current = fraction * max(1.0, source_duration)
                elapsed = max(0.01, __import__("time").monotonic() - transcribe_started)
                speed = current / elapsed if current > 0 else 0.0
                job_store.update_stage(job_id, current=current, total=max(1.0, source_duration), speed=speed, backend=backend, message=f"Transcrevendo rápido · {backend} · segmentos")
                pct = 12 + int(27 * fraction)
                _update(project_id, progress=min(39, pct), message=f"Transcrevendo rápido · {backend} · segmentos")
            transcript, route = compute_fabric.transcribe_segments_adaptive(
                source, language, profile=profile, local_backend_id=selected_asr, mode=compute_mode,
                progress=on_transcribe_progress, cancel_check=control.should_cancel, project_id=project_id, local_transcriber=transcribe_segments,
            )
            compute_summary.append(route)
            asr_cache.save_segment_transcript(segment_key, transcript)
        else:
            job_store.update_stage(job_id, current=max(1.0, source_duration), total=max(1.0, source_duration), backend="cache", message="Transcrição rápida reutilizada do cache")
            _update(project_id, progress=39, message="Transcrição reutilizada do cache")
        job_store.finish_stage(job_id, message="Passo A concluído")
        _update(project_id, progress=40, message="Encontrando os melhores momentos")

        job_store.start_stage(job_id, "highlights", total=1.0, message="Selecionando cortes")
        highlight_settings = dict(settings)
        highlight_settings["mode"] = row["mode"]
        if str(row["mode"] or "smart") == "manual":
            candidates = _pick_highlights_for_two_pass(transcript, highlight_settings, source_duration)
            route = {"task_type": "highlights", "selected": "local_cpu", "mode": "manual"}
        else:
            candidates, route = compute_fabric.highlights_adaptive(transcript, highlight_settings, mode=compute_mode, project_id=project_id, local_find=find_highlights, local_sequential=sequential_highlights)
            candidates = _apply_source_range(candidates, highlight_settings, source_duration)
        compute_summary.append(route)
        if not candidates:
            raise RuntimeError("Nenhum momento válido foi encontrado. Tente reduzir a duração mínima, ampliar a faixa do vídeo ou usar o modo sequencial/manual.")
        job_store.update_stage(job_id, current=1, total=1, message=f"{len(candidates)} cortes selecionados")
        job_store.finish_stage(job_id)

        # V3.4 Pass B: word timestamps only for selected/merged clip windows.
        refined_transcript = dict(transcript)
        windows: list[tuple[float, float]] = []
        for candidate in sorted(candidates, key=lambda c: float(c["start"])):
            cstart = float(candidate["start"])
            cend = float(candidate["end"])
            if not windows or cstart > windows[-1][1]:
                windows.append((cstart, cend))
            else:
                windows[-1] = (windows[-1][0], max(windows[-1][1], cend))
        job_store.start_stage(job_id, "refine-captions", total=max(1.0, float(len(windows))), backend=selected_asr or backend_label, message="Refinando legendas · palavras")
        for widx, (wstart, wend) in enumerate(windows, 1):
            control.checkpoint()
            word_key = asr_cache.word_window_cache_key(source, wstart, wend, model=model_name, language=language)
            refined = asr_cache.load_word_window(word_key)
            if refined is None:
                def on_word_progress(fraction: float, backend: str, *, clip_idx=widx) -> None:
                    control.checkpoint()
                    current = (clip_idx - 1) + max(0.0, min(1.0, float(fraction)))
                    job_store.update_stage(job_id, current=current, total=max(1.0, float(len(windows))), backend=backend, message=f"Refinando legendas · corte {clip_idx}/{len(windows)} · palavras")
                refined, route = compute_fabric.transcribe_words_adaptive(
                    source, wstart, wend, language, profile=profile, local_backend_id=selected_asr, mode=compute_mode,
                    progress=on_word_progress, cancel_check=control.should_cancel, project_id=project_id, local_transcriber=transcribe_words,
                )
                compute_summary.append(route)
                asr_cache.save_word_window(word_key, refined)
            refined_transcript = _merge_refined_window(refined_transcript, refined, wstart, wend)
            job_store.update_stage(job_id, current=float(widx), total=max(1.0, float(len(windows))), message=f"Refinando legendas · corte {widx}/{len(windows)} · palavras")
            _update(project_id, progress=min(54, 45 + int(9 * widx / max(1, len(windows)))), message=f"Refinando legendas · {widx}/{len(windows)}")
        job_store.finish_stage(job_id, message="Legendas refinadas nos cortes selecionados")
        transcript = refined_transcript
        for candidate in candidates:
            candidate["transcript"] = _window_transcript(transcript, float(candidate["start"]), float(candidate["end"]))
        transcript_path = work_dir / "transcript.json"
        save_transcript(transcript, transcript_path)
        asr_cache.cleanup_lru()
        _update(project_id, progress=55, message="Transcrição V3.4 pronta · iniciando Face Tracking", transcript_path=str(transcript_path))

        # V3.2: track only the windows that will actually become clips. The
        # old full-video analyze_video() call was the source of the 10% stall.
        analysis_cfg = dict(profile.get("analysis") or {})
        tracking_fps = float(analysis_cfg.get("tracking_fps") or settings.get("tracking_fps") or 1.0)
        analysis_width = int(analysis_cfg.get("width") or 640)
        margin = 0.6
        tracking_windows: list[dict] = []
        total_tracking_seconds = sum(max(0.1, float(c["end"]) - float(c["start"]) + margin * 2) for c in candidates)
        tracking_done = 0.0
        job_store.start_stage(job_id, "tracking", total=total_tracking_seconds, backend="auto", message="Face Tracking somente nos cortes")
        _update(project_id, progress=55, message=f"Face Tracking 0/{len(candidates)} · somente trechos úteis")
        for idx, candidate in enumerate(candidates, 1):
            cstart = float(candidate["start"]); cend = float(candidate["end"])
            wstart = max(0.0, cstart - margin); wend = min(source_duration or cend + margin, cend + margin)
            window_duration = max(0.1, wend - wstart)
            window_path = work_dir / f"face_tracks_{idx:02d}.json"
            local_started = __import__('time').monotonic()
            def on_tracking_progress(fraction: float, backend: str, *, base=tracking_done, duration=window_duration, clip_idx=idx):
                fraction = max(0.0, min(1.0, float(fraction)))
                current = base + fraction * duration
                elapsed = max(0.01, __import__('time').monotonic() - local_started)
                speed = (fraction * duration) / elapsed if fraction > 0 else 0.0
                job_store.update_stage(job_id, current=current, total=total_tracking_seconds, speed=speed, backend=backend, message=f"Face Tracking {clip_idx}/{len(candidates)} · {backend}")
                project_fraction = current / max(0.1, total_tracking_seconds)
                _update(project_id, progress=min(69, 55 + int(14 * project_fraction)), message=f"Face Tracking {clip_idx}/{len(candidates)} · {int(fraction*100)}%")
            control.checkpoint()
            window_data = None
            for attempt_no, attempt_cfg in enumerate(worker_control.tracking_attempts(profile), 1):
                timed_out = False
                deadline = __import__('time').monotonic() + max(15.0, window_duration * float(attempt_cfg.get("timeout_factor") or 2.0))
                def tracking_cancel_check():
                    nonlocal timed_out
                    if control.should_cancel():
                        return True
                    if __import__('time').monotonic() > deadline:
                        timed_out = True
                        return True
                    return False
                attempt_path = window_path if attempt_no == 1 else window_path.with_name(f"{window_path.stem}_try{attempt_no}.json")
                window_data, route = compute_fabric.track_window_adaptive(
                    source, wstart, wend, out_path=attempt_path,
                    fps=float(attempt_cfg["fps"]), analysis_width=int(attempt_cfg["width"]), profile=profile, mode=compute_mode,
                    progress=on_tracking_progress, cancel_check=tracking_cancel_check, project_id=project_id, local_tracker=face_tracking.analyze_window,
                    detector_backend=str(attempt_cfg.get("detector_backend") or "auto"),
                )
                compute_summary.append(route)
                if control.should_cancel():
                    raise worker_control.JobCancelled("Job cancelado pelo usuário")
                if not timed_out:
                    break
                job_store.update_stage(job_id, message=f"Tracking lento · tentativa {attempt_no + 1} com análise mais leve", backend=str(window_data.get("backend") or "fallback"))
            if window_data is None or not isinstance(window_data, dict):
                window_data = face_tracking.empty_tracking("Tracking indisponível; safe crop aplicado")
                window_data.update({"source_start": wstart, "source_end": wend, "sampling": "safe-crop"})
            tracking_windows.append(window_data)
            tracking_done += window_duration
        job_store.update_stage(job_id, current=total_tracking_seconds, total=total_tracking_seconds, message="Face Tracking concluído")
        job_store.finish_stage(job_id)
        tracking_data = face_tracking.merge_window_tracks(tracking_windows)
        tracking_path = work_dir / "face_tracks.json"
        tracking_path.write_text(json.dumps(tracking_data, ensure_ascii=False, indent=2), encoding="utf-8")
        tracking_summary = face_tracking.tracking_summary(tracking_data)
        _update(project_id, progress=70, message=f"Renderizando {len(candidates)} cortes", tracking_path=str(tracking_path), tracking_summary_json=json.dumps(tracking_summary, ensure_ascii=False))

        out_dir = OUTPUT_DIR / project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        default_state = _initial_edit_state(settings)
        job_store.start_stage(job_id, "render", total=float(len(candidates)), backend=encoder_label, message="Renderizando cortes")
        for idx, (candidate, window_data) in enumerate(zip(candidates, tracking_windows), 1):
            control.checkpoint()
            clip_id = uuid.uuid4().hex
            video_out = out_dir / f"clip_{idx:02d}.mp4"
            clean_out = out_dir / f"clip_{idx:02d}.clean.mp4"
            clip_tracking = face_tracking.slice_tracks(window_data, float(candidate["start"]), float(candidate["end"]))
            clip_state = _state_for_candidate(default_state, candidate)
            render_clean_clip(
                source=source, out_path=clean_out, start=float(candidate["start"]), end=float(candidate["end"]),
                edit_state=clip_state, tracking=clip_tracking,
            )
            result = render_edited_clip(
                source=source, out_path=video_out, start=float(candidate["start"]), end=float(candidate["end"]),
                edit_state=clip_state, transcript=transcript, tracking=clip_tracking,
            )
            thumb = THUMB_DIR / f"{clip_id}.jpg"
            try:
                generate_thumbnail(video_out, thumb, candidate.get("title", "")); thumb_path = str(thumb)
            except Exception:
                thumb_path = None
            now = now_iso(); size = video_out.stat().st_size if video_out.exists() else None
            execute(
                """
                INSERT INTO clips(id,project_id,title,start_time,end_time,score,hook,reason,video_path,preview_path,clean_path,thumbnail_path,created_at,updated_at,render_status,render_encoder,file_size,analysis_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (clip_id, project_id, candidate.get("title", f"Corte {idx}"), float(candidate["start"]), float(candidate["end"]),
                 float(candidate.get("score", 0)), candidate.get("hook", ""), candidate.get("reason", ""), str(video_out), str(video_out), str(clean_out),
                 thumb_path, now, now, "rendered", result.get("encoder"), size, json.dumps(_candidate_analysis(candidate), ensure_ascii=False)),
            )
            editor_service.save_edit_state(clip_id, clip_state)
            _apply_project_studio_defaults(row, clip_id)
            cues = cues_from_transcript(transcript, float(candidate["start"]), float(candidate["end"]))
            if cues:
                editor_service.replace_caption_cues(clip_id, cues)
            if settings.get("auto_edit_enabled"):
                _update(project_id, message=f"Auto Edit {idx}/{len(candidates)} · B-roll e efeitos")
                auto_result = _apply_project_auto_edit(
                    clip_id=clip_id, settings=settings, source=source, video_out=video_out,
                    start=float(candidate["start"]), end=float(candidate["end"]), edit_state=clip_state,
                    transcript=transcript, tracking=clip_tracking,
                )
                if auto_result:
                    result = auto_result; size = video_out.stat().st_size if video_out.exists() else None
                    try:
                        generate_thumbnail(video_out, thumb, candidate.get("title", "")); thumb_path = str(thumb)
                    except Exception:
                        pass
                    execute("UPDATE clips SET thumbnail_path=?,render_encoder=?,file_size=?,updated_at=? WHERE id=?", (thumb_path, result.get("encoder"), size, now_iso(), clip_id))
            job_store.update_stage(job_id, current=float(idx), total=float(len(candidates)), backend=str(result.get("encoder") or encoder_label), message=f"Corte {idx}/{len(candidates)} pronto")
            pct = 70 + int(28 * idx / len(candidates))
            _update(project_id, progress=min(98, pct), message=f"Corte {idx}/{len(candidates)} pronto")

        job_store.complete_job(job_id, "Projeto concluído")
        _update(project_id, "done", 100, "Projeto concluído", compute_summary_json=json.dumps({"mode": compute_mode, "routes": compute_summary}, ensure_ascii=False))
    except worker_control.JobCancelled as exc:
        job_store.fail_job(job_id, str(exc), status="cancelled")
        _update(project_id, "error", max(0, int(row["progress"] or 0)), "Processamento cancelado pelo usuário")
    except Exception as exc:
        traceback.print_exc()
        try:
            job_store.fail_job(job_id, f"Erro: {exc}")
        except Exception:
            pass
        _update(project_id, "error", 100, f"Erro: {exc}")
