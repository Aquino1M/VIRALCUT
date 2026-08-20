from __future__ import annotations

import math
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app.config import FFMPEG_BIN, FFPROBE_BIN, TEMP_DIR
from . import render as render_engine
from . import face_tracking
from . import captions as caption_engine


def _track_items(data: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    for track in data.get("tracks") or []:
        if track.get("type") == kind and not track.get("hidden"):
            return list(track.get("items") or [])
    return []


def director_layout_segments(data: dict[str, Any] | None, duration: float, *, default_layout: str = "single") -> list[dict[str, Any]]:
    """Return non-overlapping layout segments covering the complete duration."""
    duration = max(0.01, float(duration or 0.01))
    directives = []
    for item in _track_items(data or {}, "effects"):
        if item.get("type") != "director-layout":
            continue
        start = max(0.0, min(duration, float(item.get("from") or 0.0)))
        end = max(start, min(duration, start + max(0.05, float(item.get("duration") or 0.05))))
        if end <= start:
            continue
        directives.append({"start": start, "end": end, "layout_preset_id": str(item.get("layoutPresetId") or default_layout)})
    directives.sort(key=lambda x: (x["start"], x["end"]))
    if not directives:
        return []
    out: list[dict[str, Any]] = []
    cursor = 0.0
    for item in directives:
        start = max(cursor, item["start"])
        if start > cursor:
            out.append({"start": round(cursor, 6), "end": round(start, 6), "layout_preset_id": default_layout})
        end = max(start, item["end"])
        if end > start:
            out.append({"start": round(start, 6), "end": round(end, 6), "layout_preset_id": item["layout_preset_id"]})
            cursor = end
        if cursor >= duration:
            break
    if cursor < duration:
        out.append({"start": round(cursor, 6), "end": round(duration, 6), "layout_preset_id": default_layout})
    return out


def _window_cues(cues: list[dict[str, Any]] | None, offset: float, duration: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    end_window = offset + duration
    for cue in cues or []:
        a = float(cue.get("start_time") or 0.0)
        b = float(cue.get("end_time") or a + 0.05)
        if b <= offset or a >= end_window:
            continue
        c = dict(cue)
        c["start_time"] = max(0.0, a - offset)
        c["end_time"] = min(duration, max(c["start_time"] + 0.01, b - offset))
        out.append(c)
    return out


def _segment_cues(cues: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    return _window_cues(cues, start, max(0.01, end - start))


def _render_director_base(
    source: Path, out_path: Path, source_start: float, duration: float, edit_state: dict[str, Any], timeline_data: dict[str, Any],
    *, caption_cues: list[dict[str, Any]], tracking: dict[str, Any] | None, preview: bool, progress: Callable[[int, str], None],
) -> dict[str, Any]:
    segments = director_layout_segments(timeline_data, duration, default_layout=str((edit_state or {}).get("layout_preset_id") or "single"))
    if not segments:
        raise ValueError("director_segments_missing")
    token = f"director_{out_path.stem}_{int(time.time()*1000)}"
    files: list[Path] = []
    last_result: dict[str, Any] = {}
    try:
        for idx, seg in enumerate(segments):
            seg_len = max(0.05, float(seg["end"]) - float(seg["start"]))
            seg_path = TEMP_DIR / f"{token}_{idx:03d}.mp4"
            seg_state = deepcopy(edit_state or {})
            seg_state["layout_preset_id"] = seg["layout_preset_id"]
            seg_tracking = face_tracking.slice_tracks(tracking, float(seg["start"]), float(seg["end"])) if tracking else tracking
            seg_cues = _segment_cues(caption_cues, float(seg["start"]), float(seg["end"]))
            base_pct = 5 + int((idx / max(1, len(segments))) * 62)
            progress(base_pct, f"Director AI · cena {idx+1}/{len(segments)}")
            last_result = render_engine.render_edited_clip(
                source, seg_path, source_start + float(seg["start"]), source_start + float(seg["end"]), seg_state,
                caption_cues=seg_cues, transcript=None, tracking=seg_tracking, preview=preview, preview_offset=0.0,
                preview_duration=seg_len, progress_callback=lambda _p, _m: None,
            )
            files.append(seg_path)
        list_path = TEMP_DIR / f"{token}.concat.txt"
        lines = []
        for f in files:
            normalized = str(f.resolve()).replace('\\', '/').replace("'", "'\''")
            lines.append(f"file '{normalized}'")
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        proc = subprocess.run(
            [render_engine.FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", "-movflags", "+faststart", str(out_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "Director concat falhou")[-1600:])
        list_path.unlink(missing_ok=True)
        result = dict(last_result or {})
        result.update({"path": str(out_path), "director": True})
        return result
    finally:
        for f in files:
            f.unlink(missing_ok=True)


def has_timeline_media(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    return any(_track_items(data, kind) for kind in ("broll", "sfx", "music", "effects"))


def _linear_volume(db: float | int | None) -> float:
    return round(10 ** (float(db or 0) / 20.0), 5)


def _asset(data: dict[str, Any], asset_id: str | None) -> dict[str, Any] | None:
    if not asset_id:
        return None
    item = (data.get("assets") or {}).get(asset_id)
    return dict(item) if isinstance(item, dict) else None


def compile_postprocess_plan(
    data: dict[str, Any], *, width: int, height: int, base_has_audio: bool = True
) -> dict[str, Any]:
    duration = max(0.01, float((data.get("composition") or {}).get("duration") or 0.01))
    inputs: list[dict[str, Any]] = []
    input_for_item: dict[str, int] = {}
    next_index = 1

    for kind in ("broll", "sfx", "music"):
        for item in _track_items(data, kind):
            asset = _asset(data, item.get("assetId"))
            path = str((asset or {}).get("path") or "")
            if not path:
                continue
            idx = next_index
            next_index += 1
            input_for_item[str(item.get("id"))] = idx
            inputs.append({
                "index": idx,
                "kind": kind,
                "path": path,
                "loop": bool(kind in {"broll", "music"} or item.get("loop")),
                "source_start": max(0.0, float(item.get("sourceStart") or 0.0)),
                "duration": max(0.05, float(item.get("duration") or duration)),
                "item_id": str(item.get("id") or ""),
            })

    filters: list[str] = ["[0:v]setpts=PTS-STARTPTS[v0]"]
    vcur = "[v0]"
    vseq = 1

    # Global filters first so B-roll is not unintentionally recolored unless desired.
    for item in _track_items(data, "effects"):
        if item.get("type") != "filter":
            continue
        eq = str((item.get("config") or {}).get("eq") or "").strip()
        if not eq:
            continue
        label = f"[v{vseq}]"; vseq += 1
        filters.append(f"{vcur}eq={eq}{label}")
        vcur = label

    for item in _track_items(data, "effects"):
        if item.get("type") == "filter":
            continue
        start = max(0.0, float(item.get("from") or 0.0))
        end = min(duration, start + max(0.05, float(item.get("duration") or 0.3)))
        if end <= start:
            continue
        config = item.get("config") or {}
        kind = str(config.get("type") or item.get("effectId") or "").lower()
        if kind == "zoom" or "zoom" in str(item.get("effectId") or ""):
            scale = max(1.01, min(1.35, float(config.get("scale") or 1.08)))
            sw = int(math.ceil(width * scale / 2) * 2)
            sh = int(math.ceil(height * scale / 2) * 2)
            base_label = f"[vzbase{vseq}]"; src_label = f"[vzsrc{vseq}]"; fx_label = f"[vzfx{vseq}]"; out_label = f"[v{vseq}]"
            filters.append(f"{vcur}split=2{base_label}{src_label}")
            filters.append(f"{src_label}scale={sw}:{sh},crop={width}:{height}:(iw-{width})/2:(ih-{height})/2{fx_label}")
            filters.append(f"{base_label}{fx_label}overlay=0:0:eof_action=pass:enable='between(t,{start:.3f},{end:.3f})'{out_label}")
            vcur = out_label; vseq += 1
        elif kind == "shake" or "shake" in str(item.get("effectId") or ""):
            amount = max(2, min(20, int(config.get("amount") or 7)))
            pad = amount + 8
            sw, sh = width + pad * 2, height + pad * 2
            base_label = f"[vsbase{vseq}]"; src_label = f"[vssrc{vseq}]"; fx_label = f"[vsfx{vseq}]"; out_label = f"[v{vseq}]"
            filters.append(f"{vcur}split=2{base_label}{src_label}")
            filters.append(f"{src_label}scale={sw}:{sh}{fx_label}")
            filters.append(
                f"{base_label}{fx_label}overlay=x='-{pad}+{amount}*sin(t*48)':y='-{pad}+{amount}*cos(t*53)':eof_action=pass:enable='between(t,{start:.3f},{end:.3f})'{out_label}"
            )
            vcur = out_label; vseq += 1
        elif kind == "flash" or "flash" in str(item.get("effectId") or ""):
            out_label = f"[v{vseq}]"; vseq += 1
            filters.append(f"{vcur}eq=brightness=0.22:enable='between(t,{start:.3f},{end:.3f})'{out_label}")
            vcur = out_label
        elif kind == "blur" or "blur" in str(item.get("effectId") or ""):
            radius = max(1.0, min(20.0, float(config.get("radius") or 6)))
            out_label = f"[v{vseq}]"; vseq += 1
            filters.append(f"{vcur}gblur=sigma={radius:.2f}:enable='between(t,{start:.3f},{end:.3f})'{out_label}")
            vcur = out_label
        elif kind == "progress-bar" or "progress-bar" in str(item.get("effectId") or ""):
            # FFmpeg's drawbox width is not reliably time-evaluated on all Windows builds.
            # Use 24 small segments that become visible progressively; this is robust
            # across the bundled/stock FFmpeg versions and still looks continuous.
            bar_h = max(4, min(30, int(config.get("height") or max(6, height * 0.007))))
            y = max(0, min(height - bar_h, int(config.get("y") or (height - bar_h))))
            color = str(config.get("color") or "white@0.92").replace("'", "")
            segments = max(8, min(48, int(config.get("segments") or 24)))
            for seg_i in range(segments):
                seg_x = int(round(width * seg_i / segments))
                seg_w = max(1, int(round(width / segments)) + 1)
                reveal = start + (end - start) * (seg_i / segments)
                out_label = f"[v{vseq}]"; vseq += 1
                filters.append(f"{vcur}drawbox=x={seg_x}:y={y}:w={seg_w}:h={bar_h}:color={color}:t=fill:enable='between(t,{reveal:.3f},{end:.3f})'{out_label}")
                vcur = out_label

    for item in _track_items(data, "broll"):
        idx = input_for_item.get(str(item.get("id")))
        if idx is None:
            continue
        start = max(0.0, float(item.get("from") or 0.0))
        length = max(0.05, float(item.get("duration") or 1.0))
        end = min(duration, start + length)
        if end <= start:
            continue
        b_label = f"[broll{vseq}]"
        out_label = f"[v{vseq}]"
        ken = bool(item.get("kenBurns") or (item.get("config") or {}).get("kenBurns"))
        if ken:
            # Gentle Ken Burns motion for still/low-motion B-roll. zoompan also works
            # on video inputs and keeps the timeline item fully editable.
            frames = max(2, int(round(length * 30)))
            filters.append(
                f"[{idx}:v]trim=duration={length:.3f},setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},zoompan=z='min(zoom+0.0008,1.08)':d={frames}:s={width}x{height}:fps=30,setpts=PTS-STARTPTS+{start:.3f}/TB{b_label}"
            )
        else:
            filters.append(
                f"[{idx}:v]trim=duration={length:.3f},setpts=PTS-STARTPTS+{start:.3f}/TB,scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}{b_label}"
            )
        filters.append(f"{vcur}{b_label}overlay=0:0:eof_action=pass:enable='between(t,{start:.3f},{end:.3f})'{out_label}")
        vcur = out_label; vseq += 1

    # Audio graph. A generated silent base keeps the graph valid for silent source clips.
    if base_has_audio:
        filters.append("[0:a]aresample=async=1:first_pts=0[abase]")
    else:
        filters.append(f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={duration:.3f}[abase]")
    audio_labels = ["[abase]"]
    aseq = 0
    for kind in ("sfx", "music"):
        for item in _track_items(data, kind):
            idx = input_for_item.get(str(item.get("id")))
            if idx is None:
                continue
            start = max(0.0, float(item.get("from") or 0.0))
            length = min(max(0.05, float(item.get("duration") or duration)), max(0.05, duration - start))
            delay = int(round(start * 1000))
            volume = _linear_volume(item.get("volumeDb", -8 if kind == "sfx" else -24))
            label = f"[a{aseq}]"; aseq += 1
            filters.append(f"[{idx}:a]atrim=duration={length:.3f},asetpts=PTS-STARTPTS,volume={volume},adelay={delay}|{delay}{label}")
            audio_labels.append(label)
    if len(audio_labels) > 1:
        filters.append(f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:duration=first:dropout_transition=0[aout]")
        audio_map = "[aout]"
    else:
        audio_map = "[abase]"

    return {
        "inputs": inputs,
        "filter_complex": ";".join(filters),
        "video_map": vcur,
        "audio_map": audio_map,
        "duration": duration,
    }


def _has_audio(path: Path) -> bool:
    try:
        p = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
        )
        return p.returncode == 0 and bool((p.stdout or "").strip())
    except Exception:
        return True


def _existing_media_only(data: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(data)
    assets = out.get("assets") or {}
    for track in out.get("tracks") or []:
        if track.get("type") not in {"broll", "sfx", "music"}:
            continue
        kept = []
        for item in track.get("items") or []:
            asset = assets.get(item.get("assetId")) or {}
            p = str(asset.get("path") or "")
            if p and Path(p).exists():
                kept.append(item)
        track["items"] = kept
    return out


def render_timeline_clip(
    source: Path,
    out_path: Path,
    start: float,
    end: float,
    edit_state: dict[str, Any] | None,
    timeline_data: dict[str, Any] | None,
    *,
    caption_cues: list[dict[str, Any]] | None = None,
    transcript: dict[str, Any] | None = None,
    tracking: dict[str, Any] | None = None,
    preview: bool = False,
    preview_offset: float = 0.0,
    preview_duration: float = 8.0,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    progress = progress_callback or (lambda _pct, _msg: None)
    if not has_timeline_media(timeline_data):
        return render_engine.render_edited_clip(
            source, out_path, start, end, edit_state, caption_cues=caption_cues, transcript=transcript,
            tracking=tracking, preview=preview, preview_offset=preview_offset, preview_duration=preview_duration,
            progress_callback=progress,
        )

    clip_duration = max(0.1, float(end) - float(start))
    offset = max(0.0, min(float(preview_offset), max(0.0, clip_duration - 0.1))) if preview else 0.0
    window_duration = min(float(preview_duration), clip_duration - offset) if preview else clip_duration
    usable = _existing_media_only(timeline_data or {})
    if preview and offset > 0:
        usable = deepcopy(usable)
        usable.setdefault("composition", {})["duration"] = window_duration
        for tr in usable.get("tracks") or []:
            shifted = []
            for item in tr.get("items") or []:
                item = dict(item)
                a = float(item.get("from") or 0.0) - offset
                b = a + float(item.get("duration") or 0.0)
                if b <= 0 or a >= window_duration:
                    continue
                trim_left = max(0.0, -a)
                item["from"] = max(0.0, a)
                item["duration"] = min(window_duration - item["from"], max(0.05, b - max(0.0, a)))
                if item.get("sourceStart") is not None:
                    item["sourceStart"] = float(item.get("sourceStart") or 0.0) + trim_left
                shifted.append(item)
            tr["items"] = shifted
    else:
        usable.setdefault("composition", {})["duration"] = window_duration

    effective_cues = caption_cues
    if effective_cues is None and transcript:
        effective_cues = caption_engine.cues_from_transcript(transcript, float(start), float(end))
    effective_cues = _window_cues(effective_cues or [], offset, window_duration)
    effective_tracking = face_tracking.slice_tracks(tracking, offset, offset + window_duration) if (preview and tracking) else tracking

    token = f"timeline_{out_path.stem}_{int(time.time()*1000)}"
    base = TEMP_DIR / f"{token}.base.mp4"
    progress(4, "Montando base do editor")
    director_segments = director_layout_segments(
        usable, window_duration, default_layout=str((edit_state or {}).get("layout_preset_id") or "single")
    )
    if director_segments:
        base_result = _render_director_base(
            source, base, float(start) + offset, window_duration, edit_state or {}, usable,
            caption_cues=effective_cues, tracking=effective_tracking, preview=preview, progress=progress,
        )
    else:
        base_result = render_engine.render_edited_clip(
            source, base, start, end, edit_state, caption_cues=caption_cues, transcript=transcript,
            tracking=tracking, preview=preview, preview_offset=preview_offset, preview_duration=preview_duration,
            progress_callback=lambda pct, msg: progress(min(72, max(4, int(pct * .72))), msg),
        )
    try:
        width, height = [int(x) for x in str(base_result.get("resolution") or "1080x1920").lower().split("x", 1)]
    except Exception:
        width, height = (540, 960) if preview else (1080, 1920)

    if not has_timeline_media(usable) or not any(
        item.get("type") != "director-layout" for kind in ("broll", "sfx", "music", "effects") for item in _track_items(usable, kind)
    ):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        base.replace(out_path)
        return base_result

    plan = compile_postprocess_plan(usable, width=width, height=height, base_has_audio=_has_audio(base))
    prefix: list[str] = [render_engine.FFMPEG_BIN, "-y", "-i", str(base)]
    for inp in plan["inputs"]:
        if inp["loop"]:
            prefix += ["-stream_loop", "-1"]
        if inp["source_start"] > 0:
            prefix += ["-ss", f"{inp['source_start']:.3f}"]
        prefix += ["-i", inp["path"]]
    prefix += ["-filter_complex", plan["filter_complex"], "-map", plan["video_map"], "-map", plan["audio_map"]]
    suffix = ["-c:a", "aac", "-b:a", "128k" if preview else "160k", "-movflags", "+faststart", "-shortest", str(out_path)]
    progress(78, "Aplicando B-roll, áudio e efeitos")
    encoder = render_engine._run_encoded(prefix, suffix, preview=preview, log_name=token)
    progress(97, "Auto Edit composto")
    base.unlink(missing_ok=True)
    return {
        "path": str(out_path), "encoder": encoder, "resolution": f"{width}x{height}",
        "fallback": encoder != render_engine.select_video_encoder(), "timeline": True,
        "director": bool(director_segments),
    }
