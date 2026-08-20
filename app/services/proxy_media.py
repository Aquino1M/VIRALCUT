from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from pathlib import Path

from app.config import FFMPEG_BIN, FFPROBE_BIN, LOG_DIR, PREVIEW_DIR
from . import cloud_client
from .render import summarize_ffmpeg_error

PROXY_VERSION = "v42-source-aspect-robust-1"
logger = logging.getLogger(__name__)


def _even(value: float) -> int:
    n = max(2, int(round(value)))
    return n if n % 2 == 0 else n + 1


def proxy_geometry(aspect_ratio: str | None) -> tuple[int, int]:
    ratio = (aspect_ratio or "9:16").strip().lower()
    if ratio == "16:9":
        return (854, 480)
    if ratio == "1:1":
        return (480, 480)
    if ratio == "4:5":
        return (384, 480)
    # Vertical 9:16: keep the long edge at 480 for a deliberately light editor proxy.
    return (270, 480)


def proxy_cache_path(clip_id: str, source: Path, start: float, end: float, aspect_ratio: str | None, target_height: int = 480) -> Path:
    stat = source.stat()
    target_height = max(240, min(1080, int(target_height or 480)))
    token = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{start:.3f}|{end:.3f}|{aspect_ratio}|{target_height}|{PROXY_VERSION}"
    digest = hashlib.sha256(token.encode()).hexdigest()[:20]
    folder = PREVIEW_DIR / f"proxy{target_height}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{clip_id}_{digest}.mp4"


def source_proxy_geometry(source: Path, target_height: int = 480) -> tuple[int, int]:
    target_height = max(240, min(1080, int(target_height or 480)))
    try:
        proc = subprocess.run([FFPROBE_BIN, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(source)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        w, h = [int(x) for x in (proc.stdout or "").strip().split("x")[:2]]
        if w > 0 and h > 0:
            if w >= h:
                return (_even(target_height * w / h), target_height)
            return (target_height, _even(target_height * h / w))
    except Exception:
        pass
    return (_even(target_height * 9 / 16), target_height)


def valid_proxy(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 4096:
        return False
    try:
        proc = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height:format=duration", "-of", "default=nw=1", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        output = (proc.stdout or "").lower()
        return proc.returncode == 0 and all(key in output for key in ("codec_name=", "width=", "height=", "duration="))
    except Exception:
        return False


def _run_attempt(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return int(proc.returncode), proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return 124, f"{stderr}\nViralClip: timeout após {timeout}s"
    except Exception as exc:
        return 125, f"ViralClip: {type(exc).__name__}: {exc}"


def _write_proxy_log(clip_id: str, source: Path, attempts: list[tuple[list[str], int, str]]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_clip = "".join(ch for ch in clip_id if ch.isalnum() or ch in "-_")[:64] or "clip"
    path = LOG_DIR / f"proxy_{safe_clip}_{time.strftime('%Y%m%d_%H%M%S')}.log"
    parts = [f"SOURCE: {source}\n"]
    for index, (cmd, code, stderr) in enumerate(attempts, 1):
        parts.append(f"\n=== ATTEMPT {index} / EXIT {code} ===\n{subprocess.list2cmdline(cmd)}\n\n{stderr}\n")
    path.write_text("".join(parts), encoding="utf-8", errors="replace")
    return path


def ensure_editor_proxy(
    clip_id: str,
    source: Path,
    start: float,
    end: float,
    aspect_ratio: str | None = "9:16",
    *,
    target_height: int = 480,
    force_rebuild: bool = False,
    prefer_cloud: bool = True,
) -> Path:
    if not source.exists():
        raise FileNotFoundError(source)
    target_height = max(240, min(1080, int(target_height or 480)))
    out = proxy_cache_path(clip_id, source, start, end, aspect_ratio, target_height)
    if not force_rebuild and valid_proxy(out):
        return out
    out.unlink(missing_ok=True)
    if prefer_cloud and cloud_client.configured() and cloud_client.health(timeout=2.5).get("ok"):
        try:
            job_id = cloud_client.submit_task(
                "editor_proxy",
                {"start": float(start), "end": float(end), "target_height": target_height},
                media_path=source,
                idempotency_key=f"editor-proxy:{out.stem}",
            )
            cloud_client.wait_job(job_id)
            cloud_client.download_result_file(job_id, out)
            if valid_proxy(out):
                return out
            out.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Proxy Cloud indisponível para %s; usando CPU local: %s", clip_id, exc)
    # The editor must receive a neutral proxy with the SAME source aspect ratio.
    # Cropping/layout is composed in the browser, matching the final FFmpeg render.
    # Baking the project aspect ratio into the proxy caused double-cropping/black frames.
    w, h = source_proxy_geometry(source) if target_height == 480 else source_proxy_geometry(source, target_height)
    duration = max(0.05, float(end) - float(start))
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    start = max(0.0, float(start))
    lead = min(2.0, start)
    prefixes = [
        [FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "warning", "-fflags", "+genpts", "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{duration:.3f}"],
        [FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "warning", "-fflags", "+genpts+discardcorrupt", "-err_detect", "ignore_err", "-ss", f"{max(0.0, start-lead):.3f}", "-i", str(source), "-ss", f"{lead:.3f}", "-t", f"{duration:.3f}"],
    ]
    attempts: list[tuple[list[str], int, str]] = []
    for index, prefix in enumerate((*prefixes, prefixes[-1])):
        output_args = [
            "-map", "0:v:0", "-vf", vf, "-r", "30", "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "31", "-pix_fmt", "yuv420p",
            *( ["-map", "0:a?", "-c:a", "aac", "-b:a", "64k", "-ac", "2"] if index < 2 else ["-an"] ),
            "-movflags", "+faststart", "-avoid_negative_ts", "make_zero", str(out),
        ]
        out.unlink(missing_ok=True)
        cmd = prefix + output_args
        code, stderr = _run_attempt(cmd, timeout=180)
        attempts.append((cmd, code, stderr))
        if code == 0 and valid_proxy(out):
            return out

    out.unlink(missing_ok=True)
    log_path = _write_proxy_log(clip_id, source, attempts)
    summary = summarize_ffmpeg_error(attempts[-1][2] if attempts else "")
    logger.error("Falha ao gerar proxy %s. Log: %s. %s", clip_id, log_path, summary)
    raise RuntimeError(f"{summary}. Consulte {log_path.name}")
