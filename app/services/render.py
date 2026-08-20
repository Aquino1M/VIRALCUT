from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from app.config import FFMPEG_BIN, FFPROBE_BIN, FONT_DIR, LOG_DIR, TEMP_DIR, VIDEO_ENCODER
from . import captions as caption_engine
from . import layouts
from .fonts import resolve_font
from .overlays import compose_static_overlay
from . import hardware

_encoder_cache: str | None = None


def resolve_output_geometry(aspect_ratio: str | None, *, preview: bool = False) -> tuple[int, int]:
    ratio = (aspect_ratio or "9:16").strip()
    final = {
        "9:16": (1080, 1920),
        "4:5": (1080, 1350),
        "1:1": (1080, 1080),
        "16:9": (1920, 1080),
    }.get(ratio, (1080, 1920))
    if not preview:
        return final
    # V3.3 preview is intentionally light: longest preview edge is ~480 px.
    preview_map = {
        "9:16": (270, 480),
        "4:5": (384, 480),
        "1:1": (480, 480),
        "16:9": (854, 480),
    }
    return preview_map.get(ratio, (270, 480))


def video_encoder_args(encoder: str, *, preview: bool = False) -> list[str]:
    encoder = (encoder or "libx264").strip().lower()
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p1" if preview else "p4", "-tune", "hq", "-rc", "vbr", "-cq", "28" if preview else "21", "-b:v", "0", "-g", "60"]
    if encoder == "h264_amf":
        if preview:
            return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "27", "-qp_p", "29", "-g", "60"]
        return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "22", "-qp_p", "24", "-g", "60"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "veryfast" if preview else "medium", "-global_quality", "28" if preview else "21", "-look_ahead", "0", "-g", "60"]
    return ["-c:v", "libx264", "-preset", "ultrafast" if preview else "veryfast", "-crf", "27" if preview else "20"]


def _ffmpeg_has_encoder(name: str) -> bool:
    try:
        proc = subprocess.run([FFMPEG_BIN, "-hide_banner", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
        return proc.returncode == 0 and name.lower() in (proc.stdout or "").lower()
    except Exception:
        return False


def select_video_encoder() -> str:
    global _encoder_cache
    requested = (VIDEO_ENCODER or "auto").strip().lower()
    if requested in {"libx264", "h264_amf", "h264_nvenc", "h264_qsv"}:
        return requested
    if _encoder_cache is None:
        try:
            candidate = str((hardware.load_or_build_profile().get("render") or {}).get("encoder") or "libx264")
        except Exception:
            candidate = "libx264"
        _encoder_cache = candidate if candidate == "libx264" or _ffmpeg_has_encoder(candidate) else "libx264"
    return _encoder_cache


def summarize_ffmpeg_error(stderr: str) -> str:
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    useful = []
    skip_prefixes = ("ffmpeg version", "configuration:", "libavutil", "libavcodec", "libavformat", "libavdevice", "libavfilter", "libswscale", "libswresample")
    for ln in lines:
        low = ln.lower()
        if low.startswith(skip_prefixes):
            continue
        if any(key in low for key in ("error", "invalid", "failed", "no such", "cannot", "unable", "not found", "filter")):
            useful.append(ln)
    chosen = useful[-6:] if useful else lines[-4:]
    return " | ".join(chosen)[-1400:] or "FFmpeg falhou"


def _write_log(name: str, cmd: list[str], stderr: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{name}.log"
    path.write_text("COMMAND:\n" + " ".join(cmd) + "\n\nSTDERR:\n" + (stderr or ""), encoding="utf-8", errors="replace")
    return path


def _run(cmd: list[str], *, log_name: str = "ffmpeg") -> None:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        _write_log(log_name, cmd, proc.stderr)
        raise RuntimeError(summarize_ffmpeg_error(proc.stderr))


def _run_encoded(command_prefix: list[str], command_suffix: list[str], *, preview: bool = False, log_name: str = "render") -> str:
    preferred = select_video_encoder()
    encoders = [preferred] + (["libx264"] if preferred != "libx264" else [])
    last: Exception | None = None
    for encoder in encoders:
        try:
            _run([*command_prefix, *video_encoder_args(encoder, preview=preview), *command_suffix], log_name=f"{log_name}_{encoder}")
            return encoder
        except Exception as exc:
            last = exc
    raise last or RuntimeError("Renderização falhou")


def _escape_sub_path(path: Path) -> str:
    s = str(path.resolve()).replace("\\", "/")
    return s.replace(":", r"\:").replace("'", r"\'")


def _face_center_x(video_path: Path, start: float, end: float) -> float | None:
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        xs = []
        for ratio in (0.2, 0.4, 0.6, 0.8):
            t = start + max(0.0, end - start) * ratio
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(gray, 1.1, 5, minSize=(50, 50))
            if len(faces):
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                xs.append((x + w / 2) / frame.shape[1])
        cap.release()
        return sum(xs) / len(xs) if xs else None
    except Exception:
        return None


def _crop_filter(face_x: float | None) -> str:
    if face_x is None:
        return "scale=-2:1920,crop=1080:1920:(iw-1080)/2:0"
    xexpr = f"max(0\\,min(iw-1080\\,iw*{face_x:.5f}-540))"
    return f"scale=-2:1920,crop=1080:1920:{xexpr}:0"


def build_srt(transcript: dict, clip_start: float, clip_end: float, out_path: Path, words_per_caption: int = 5) -> Path:
    cues = caption_engine.cues_from_transcript(transcript, clip_start, clip_end)
    chunks = []
    for i in range(0, len(cues), max(1, words_per_caption)):
        g = cues[i:i + max(1, words_per_caption)]
        if g:
            chunks.append((g[0]["start_time"], g[-1]["end_time"], " ".join(x["text"] for x in g)))

    def ts(sec: float) -> str:
        sec = max(0.0, sec); h = int(sec // 3600); sec -= h * 3600; m = int(sec // 60); sec -= m * 60
        s = int(sec); ms = int(round((sec - s) * 1000)); return f"{h:02}:{m:02}:{s:02},{ms:03}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for idx, (a, b, text) in enumerate(chunks, 1):
            f.write(f"{idx}\n{ts(a)} --> {ts(b)}\n{text}\n\n")
    return out_path


def build_render_plan(edit_state: dict[str, Any] | None, *, preview: bool = False) -> dict[str, Any]:
    state = edit_state or {}
    layout_id = state.get("layout_preset_id") or "single"
    caption_preset_id = state.get("caption_preset_id") or "green-fresh"
    caption_config = caption_engine.resolve_caption_config(caption_preset_id, state.get("caption_config") or {})
    aspect_ratio = str(state.get("aspect_ratio") or "9:16")
    return {
        "layout_id": layout_id,
        "layout_config": state.get("layout_config") or {},
        "caption_preset_id": caption_preset_id,
        "caption_config": caption_config,
        "overlays": state.get("overlays") or [],
        "tracks": state.get("tracks") or {},
        "audio_config": state.get("audio_config") or {},
        "aspect_ratio": aspect_ratio,
        "output_size": resolve_output_geometry(aspect_ratio, preview=preview),
    }


def _shift_cues(cues: list[dict[str, Any]], offset: float, duration: float) -> list[dict[str, Any]]:
    out = []
    for cue in cues:
        a = float(cue.get("start_time", 0)) - offset
        b = float(cue.get("end_time", 0)) - offset
        if b < 0 or a > duration:
            continue
        c = dict(cue); c["start_time"] = max(0.0, a); c["end_time"] = min(duration, max(0.01, b)); out.append(c)
    return out


def _scale_caption_config_for_output(config: dict[str, Any], output_size: tuple[int, int]) -> dict[str, Any]:
    cfg = dict(config or {})
    w, h = output_size
    sx, sy = w / 1080.0, h / 1920.0
    scale = min(sx, sy)
    cfg["fontSize"] = max(10, int(round(float(cfg.get("fontSize", 68)) * scale)))
    cfg["positionX"] = int(round(float(cfg.get("positionX", 540)) * sx))
    cfg["positionY"] = int(round(float(cfg.get("positionY", 1280)) * sy))
    cfg["maxWidth"] = max(80, int(round(float(cfg.get("maxWidth", 900)) * sx)))
    cfg["strokeWidth"] = max(0, int(round(float(cfg.get("strokeWidth", 5)) * scale)))
    cfg["shadowDepth"] = max(0, int(round(float(cfg.get("shadowDepth", 2)) * scale)))
    cfg["backgroundRadius"] = max(0, int(round(float(cfg.get("backgroundRadius", 0)) * scale)))
    return cfg


def _scale_overlays_for_output(items: list[dict[str, Any]], output_size: tuple[int, int]) -> list[dict[str, Any]]:
    w, h = output_size
    sx, sy = w / 1080.0, h / 1920.0
    scale = min(sx, sy)
    out = []
    for item in items or []:
        x = dict(item)
        for key in ("x", "width"):
            if key in x:
                x[key] = int(round(float(x[key]) * sx))
        for key in ("y", "height"):
            if key in x:
                x[key] = int(round(float(x[key]) * sy))
        for key in ("fontSize", "strokeWidth", "borderRadius"):
            if key in x:
                x[key] = max(0, int(round(float(x[key]) * scale)))
        out.append(x)
    return out


def render_edited_clip(
    source: Path,
    out_path: Path,
    start: float,
    end: float,
    edit_state: dict[str, Any] | None = None,
    *,
    caption_cues: list[dict[str, Any]] | None = None,
    transcript: dict[str, Any] | None = None,
    tracking: dict[str, Any] | None = None,
    preview: bool = False,
    preview_offset: float = 0.0,
    preview_duration: float = 8.0,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    source = Path(source); out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    progress = progress_callback or (lambda _pct, _msg: None)
    progress(8, "Preparando render")
    plan = build_render_plan(edit_state, preview=preview)
    clip_duration = max(0.1, float(end) - float(start))
    offset = max(0.0, min(float(preview_offset), max(0.0, clip_duration - 0.1))) if preview else 0.0
    duration = min(float(preview_duration), clip_duration - offset) if preview else clip_duration
    source_start = float(start) + offset
    token = f"{out_path.stem}_{int(time.time() * 1000)}"
    base = TEMP_DIR / f"{token}.layout.mp4"

    layout_graph = layouts.build_layout_filter(
        plan["layout_id"], config=plan["layout_config"], tracking=tracking, output_size=plan["output_size"], clip_duration=duration
    )
    prefix = [FFMPEG_BIN, "-y", "-ss", f"{source_start:.3f}", "-t", f"{duration:.3f}", "-i", str(source), "-filter_complex", layout_graph, "-map", "[vout]", "-map", "0:a?"]
    suffix = []
    audio_cfg = plan.get("audio_config") or {}
    if bool(audio_cfg.get("loudness_normalize")):
        suffix += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    suffix += ["-c:a", "aac", "-b:a", "128k" if preview else "160k", "-movflags", "+faststart", str(base)]
    encoder = _run_encoded(prefix, suffix, preview=preview, log_name=f"{token}_layout")
    progress(55, "Layout processado")

    tracks = plan.get("tracks") or {}
    captions_visible = tracks.get("captions", {}).get("visible", True)
    overlay_visible = tracks.get("overlays", {}).get("visible", True) or tracks.get("cta", {}).get("visible", True) or tracks.get("text", {}).get("visible", True)

    if caption_cues is None and transcript:
        caption_cues = caption_engine.cues_from_transcript(transcript, float(start), float(end))
    shifted_cues = _shift_cues(caption_cues or [], offset, duration)

    ass_path: Path | None = None
    if captions_visible and shifted_cues:
        ass_path = TEMP_DIR / f"{token}.ass"
        caption_cfg = _scale_caption_config_for_output(plan["caption_config"], plan["output_size"])
        caption_engine.build_ass(
            shifted_cues, caption_cfg, ass_path, width=plan["output_size"][0], height=plan["output_size"][1]
        )

    overlay_path: Path | None = None
    overlay_items = plan["overlays"] if overlay_visible else []
    if overlay_items:
        overlay_path = TEMP_DIR / f"{token}.overlay.png"
        scaled_overlays = _scale_overlays_for_output(overlay_items, plan["output_size"])
        compose_static_overlay(scaled_overlays, overlay_path, width=plan["output_size"][0], height=plan["output_size"][1])

    progress(75, "Legendas e camadas preparadas")
    if not ass_path and not overlay_path:
        base.replace(out_path)
        progress(98, "Finalizando arquivo")
        return {"path": str(out_path), "encoder": encoder, "resolution": f"{plan['output_size'][0]}x{plan['output_size'][1]}", "fallback": encoder != select_video_encoder()}

    prefix = [FFMPEG_BIN, "-y", "-i", str(base)]
    if overlay_path:
        prefix += ["-loop", "1", "-i", str(overlay_path)]
    filters = []
    current = "[0:v]"
    if overlay_path:
        filters.append(f"{current}[1:v]overlay=0:0:format=auto[v1]")
        current = "[v1]"
    if ass_path:
        ass = _escape_sub_path(ass_path)
        fontsdir = _escape_sub_path(FONT_DIR)
        filters.append(f"{current}ass='{ass}':fontsdir='{fontsdir}'[vcap]")
        current = "[vcap]"
    filters.append(f"{current}null[vout]")
    prefix += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "0:a?"]
    suffix = ["-c:a", "aac", "-b:a", "128k" if preview else "160k", "-movflags", "+faststart", "-shortest", str(out_path)]
    encoder = _run_encoded(prefix, suffix, preview=preview, log_name=f"{token}_final")
    progress(96, "Composição final pronta")
    base.unlink(missing_ok=True)
    if overlay_path: overlay_path.unlink(missing_ok=True)
    if ass_path: ass_path.unlink(missing_ok=True)
    return {"path": str(out_path), "encoder": encoder, "resolution": f"{plan['output_size'][0]}x{plan['output_size'][1]}", "fallback": encoder != select_video_encoder()}


def render_clean_clip(
    source: Path,
    out_path: Path,
    start: float,
    end: float,
    edit_state: dict[str, Any] | None = None,
    *,
    tracking: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render a layout-only clip for the interactive editor.

    Captions and visual overlays are deliberately disabled so the browser can
    draw editable layers exactly once.
    """
    state = dict(edit_state or {})
    tracks = dict(state.get("tracks") or {})
    tracks["captions"] = {**tracks.get("captions", {}), "visible": False}
    tracks["overlays"] = {**tracks.get("overlays", {}), "visible": False}
    tracks["text"] = {**tracks.get("text", {}), "visible": False}
    tracks["cta"] = {**tracks.get("cta", {}), "visible": False}
    state["tracks"] = tracks
    state["overlays"] = []
    return render_edited_clip(source, out_path, start, end, state, caption_cues=[], transcript=None, tracking=tracking, preview=False)


def render_clip(
    source: Path,
    out_path: Path,
    start: float,
    end: float,
    transcript: dict | None = None,
    crop_style: str = "blur",
    captions: bool = True,
    caption_style: str = "bold",
    overlay_text: str = "",
) -> Path:
    # Backward-compatible wrapper used by the existing generation pipeline.
    layout_id = "center" if crop_style == "blur" else "single"
    preset = {"bold": "green-fresh", "large": "mrbeast", "minimal": "minimal-clean"}.get(caption_style, caption_style or "green-fresh")
    tracks = {"captions": {"visible": bool(captions)}, "overlays": {"visible": True}, "text": {"visible": True}, "cta": {"visible": True}}
    overlays = []
    if overlay_text:
        overlays.append({"type": "text", "text": overlay_text, "x": 70, "y": 100, "width": 940, "height": 160, "fontSize": 58, "fontFamily": "Montserrat", "strokeWidth": 3})
    state = {"layout_preset_id": layout_id, "caption_preset_id": preset, "caption_config": {}, "overlays": overlays, "tracks": tracks}
    render_edited_clip(source, out_path, start, end, state, transcript=transcript, preview=False)
    return Path(out_path)


def probe_video(path: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run([FFPROBE_BIN, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name:format=duration,size", "-of", "json", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        data = json.loads(proc.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]; fmt = data.get("format") or {}
        return {"width": stream.get("width"), "height": stream.get("height"), "codec": stream.get("codec_name"), "duration": float(fmt.get("duration") or 0), "size": int(fmt.get("size") or 0)}
    except Exception:
        return {}


def generate_thumbnail(video_path: Path, out_path: Path, title: str = "") -> Path:
    """Thumbnail Brain V4.2: choose the strongest sampled frame, then add title.

    Scoring is fully local and deterministic: sharpness, usable brightness and
    face presence when OpenCV is available. Falls back to the legacy 1s frame.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = 0.0
    try:
        duration = float(probe_video(video_path).get("duration") or 0.0)
    except Exception:
        pass
    sample_times = [1.0] if duration <= 2 else [max(.2, duration*r) for r in (.08,.25,.45,.65,.82)]
    candidates: list[tuple[float, Path]] = []
    try:
        import cv2
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    except Exception:
        cv2 = None; detector = None
    for idx, stamp in enumerate(sample_times):
        temp = TEMP_DIR / f"{out_path.stem}.candidate{idx}.jpg"
        try:
            _run([FFMPEG_BIN, "-y", "-ss", f"{stamp:.3f}", "-i", str(video_path), "-frames:v", "1", "-q:v", "2", str(temp)], log_name=f"thumb_{out_path.stem}_{idx}")
            score = 0.0
            if cv2 is not None:
                frame = cv2.imread(str(temp))
                if frame is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                    mean = float(gray.mean())
                    brightness = max(0.0, 100.0 - abs(mean - 135.0) * .65)
                    faces = detector.detectMultiScale(gray, 1.1, 5, minSize=(45,45)) if detector is not None else []
                    face_bonus = 60.0 if len(faces) else 0.0
                    score = min(220.0, sharp/6.0) + brightness + face_bonus
            candidates.append((score,temp))
        except Exception:
            temp.unlink(missing_ok=True)
    if not candidates:
        raise RuntimeError("Não foi possível extrair frame para thumbnail")
    candidates.sort(key=lambda x:x[0], reverse=True)
    selected=candidates[0][1]
    im = Image.open(selected).convert("RGB"); draw = ImageDraw.Draw(im)
    resolved = resolve_font("Montserrat")
    try:
        font = ImageFont.truetype(resolved.get("path") or "arialbd.ttf", max(28, im.width // 22))
    except Exception:
        font = ImageFont.load_default()
    if title:
        text = title[:70]; box = draw.textbbox((0, 0), text, font=font, stroke_width=2); tw, th = box[2] - box[0], box[3] - box[1]
        x = max(20, (im.width - tw) // 2); y = max(20, im.height - th - 70)
        draw.rounded_rectangle((x - 20, y - 14, x + tw + 20, y + th + 14), radius=16, fill=(0, 0, 0, 180))
        draw.text((x, y), text, font=font, fill="white", stroke_width=2, stroke_fill="black")
    im.save(out_path, quality=90)
    for _,candidate in candidates:
        candidate.unlink(missing_ok=True)
    return out_path
