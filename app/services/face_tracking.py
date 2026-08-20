from __future__ import annotations

import json
import math
import hashlib
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config import TRACK_DIR, TRACK_MODEL_DIR

TRACK_VERSION = 2
YUNET_MODEL = TRACK_MODEL_DIR / "face_detection_yunet_2023mar.onnx"


def sample_frame_indices(native_fps: float, sample_fps: float, frame_count: int) -> list[int]:
    native = max(0.001, float(native_fps or 30.0))
    target = max(0.001, min(native, float(sample_fps or 1.0)))
    count = max(0, int(frame_count or 0))
    if count <= 0:
        return []
    step = native / target
    out: list[int] = []
    pos = 0.0
    while int(round(pos)) < count:
        idx = min(count - 1, int(round(pos)))
        if not out or idx != out[-1]:
            out.append(idx)
        pos += step
    return out


def iter_sampled_frames(cap: cv2.VideoCapture, native_fps: float, sample_fps: float, frame_count: int):
    """Read the stream sequentially and yield only requested samples.

    Random `CAP_PROP_POS_MSEC` seeks are especially slow on inter-frame codecs; this
    keeps the decoder moving forward once and only runs face detection on samples.
    """
    targets = sample_frame_indices(native_fps, sample_fps, frame_count)
    if not targets:
        return
    target_pos = 0
    frame_idx = 0
    while target_pos < len(targets):
        ok, frame = cap.read()
        if not ok:
            break
        target = targets[target_pos]
        if frame_idx >= target:
            yield frame_idx / max(0.001, float(native_fps or 30.0)), frame
            target_pos += 1
        frame_idx += 1


def track_activity_at(track: dict[str, Any], t: float, window: float = 1.0) -> float:
    samples = track.get("samples") or []
    if not samples:
        return 0.0
    half = max(0.05, float(window)) / 2.0
    local = [float(s.get("activity") or 0.0) for s in samples if abs(float(s.get("t") or 0.0) - float(t)) <= half]
    if local:
        return sum(local) / len(local)
    nearest = min(samples, key=lambda s: abs(float(s.get("t") or 0.0) - float(t)))
    return float(nearest.get("activity") or 0.0)


def rank_tracks_at(tracking: dict[str, Any] | None, t: float, window: float = 1.0) -> list[dict[str, Any]]:
    tracks = [x for x in ((tracking or {}).get("tracks") or []) if x.get("samples")]
    return sorted(tracks, key=lambda tr: (track_activity_at(tr, t, window), len(tr.get("samples") or [])), reverse=True)


def _round_box(values: list[float]) -> list[float]:
    return [round(max(0.0, min(1.0, float(v))), 6) for v in values]


def normalize_box(box: tuple[float, float, float, float] | list[float], width: int, height: int) -> list[float]:
    x, y, w, h = [float(v) for v in box]
    if width <= 0 or height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    return _round_box([x / width, y / height, w / width, h / height])


def box_center(box: list[float]) -> list[float]:
    x, y, w, h = box
    return [round(x + w / 2, 6), round(y + h / 2, 6)]


def iou(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _center_distance(a: list[float], b: list[float]) -> float:
    ac, bc = box_center(a), box_center(b)
    return math.hypot(ac[0] - bc[0], ac[1] - bc[1])


def smooth_box(previous: list[float], current: list[float], alpha: float = 0.35) -> list[float]:
    alpha = max(0.0, min(1.0, float(alpha)))
    return [round(previous[i] * (1 - alpha) + current[i] * alpha, 6) for i in range(4)]


def associate_detections(
    previous: dict[str, dict[str, Any]],
    detections: list[dict[str, Any]],
    *,
    next_id: int = 1,
    min_iou: float = 0.12,
    max_distance: float = 0.28,
) -> tuple[list[tuple[str, dict[str, Any]]], int]:
    """Greedily associate current detections with previous stable track boxes."""
    candidates: list[tuple[float, str, int]] = []
    for track_id, prev in previous.items():
        pbox = prev.get("box") or [0, 0, 0, 0]
        for idx, det in enumerate(detections):
            dbox = det.get("box") or [0, 0, 0, 0]
            overlap = iou(pbox, dbox)
            dist = _center_distance(pbox, dbox)
            if overlap >= min_iou or dist <= max_distance:
                score = overlap * 2.0 + max(0.0, 1.0 - dist / max_distance)
                candidates.append((score, track_id, idx))
    candidates.sort(reverse=True)
    used_tracks: set[str] = set(); used_det: set[int] = set(); mapping: dict[int, str] = {}
    for _, tid, idx in candidates:
        if tid in used_tracks or idx in used_det:
            continue
        used_tracks.add(tid); used_det.add(idx); mapping[idx] = tid
    out: list[tuple[str, dict[str, Any]]] = []
    for idx, det in enumerate(detections):
        tid = mapping.get(idx)
        if tid is None:
            tid = f"face_{next_id}"
            next_id += 1
        out.append((tid, det))
    return out, next_id



def _track_mean_center(track: dict[str, Any]) -> tuple[float, float]:
    samples = track.get("samples") or []
    if not samples:
        return (0.5, 0.5)
    xs = [float((s.get("center") or [0.5, 0.5])[0]) for s in samples]
    ys = [float((s.get("center") or [0.5, 0.5])[1]) for s in samples]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def merge_tracklets(tracks: list[dict[str, Any]], max_center_distance: float = 0.12) -> list[dict[str, Any]]:
    """Merge short, non-overlapping track fragments that occupy the same region.

    Haar/YuNet may briefly miss a face. Without this pass the same seated person
    can become many IDs and split layouts may accidentally pick that person twice.
    Overlapping tracklets are never merged, which protects two nearby people.
    """
    ordered = sorted(
        [dict(t) for t in tracks if t.get("samples")],
        key=lambda t: float((t.get("samples") or [{}])[0].get("t", 0)),
    )
    groups: list[dict[str, Any]] = []
    for track in ordered:
        samples = sorted([dict(x) for x in track.get("samples") or []], key=lambda x: float(x.get("t", 0)))
        t0 = float(samples[0].get("t", 0)); t1 = float(samples[-1].get("t", 0))
        cx, cy = _track_mean_center({"samples": samples})
        best = None; best_dist = 999.0
        for group in groups:
            gs = group.get("samples") or []
            g0 = float(gs[0].get("t", 0)); g1 = float(gs[-1].get("t", 0))
            # Do not collapse two faces visible at the same time.
            overlaps = not (g1 < t0 - 0.05 or t1 < g0 - 0.05)
            if overlaps:
                continue
            gx, gy = _track_mean_center(group)
            dist = math.hypot(cx - gx, cy - gy)
            if dist <= max_center_distance and dist < best_dist:
                best = group; best_dist = dist
        if best is None:
            item = {k: v for k, v in track.items() if k != "samples"}
            item["samples"] = samples
            groups.append(item)
        else:
            best["samples"] = sorted((best.get("samples") or []) + samples, key=lambda x: float(x.get("t", 0)))
    return groups

def empty_tracking(reason: str = "Nenhum rosto analisado") -> dict[str, Any]:
    return {
        "version": TRACK_VERSION,
        "backend": "none",
        "source": {},
        "sample_fps": 0.0,
        "analyzed_frames": 0,
        "total_samples": 0,
        "frames_with_faces": 0,
        "tracks": [],
        "fallback_reason": reason,
    }


def _save(data: dict[str, Any], out_path: Path) -> dict[str, Any]:
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_tracks(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return empty_tracking("Arquivo de tracking ausente")
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else empty_tracking("Tracking inválido")
    except Exception:
        return empty_tracking("Tracking inválido")


def slice_tracks(data: dict[str, Any] | None, start: float, end: float) -> dict[str, Any]:
    data = data or empty_tracking()
    start = max(0.0, float(start)); end = max(start, float(end))
    out = {k: v for k, v in data.items() if k != "tracks"}
    out["source_start"] = start
    out["duration"] = end - start
    out_tracks = []
    for track in data.get("tracks") or []:
        samples = []
        for sample in track.get("samples") or []:
            t = float(sample.get("t", 0))
            if start <= t <= end:
                item = dict(sample); item["t"] = round(t - start, 4); samples.append(item)
        if samples:
            item = {k: v for k, v in track.items() if k != "samples"}; item["samples"] = samples; out_tracks.append(item)
    out["tracks"] = out_tracks
    return out


def tracking_summary(data: dict[str, Any] | None) -> dict[str, Any]:
    data = data or empty_tracking()
    total = int(data.get("total_samples") or data.get("analyzed_frames") or 0)
    with_faces = int(data.get("frames_with_faces") or 0)
    ranked = sorted(data.get("tracks") or [], key=lambda t: len(t.get("samples") or []), reverse=True)
    return {
        "backend": data.get("backend") or "none",
        "track_count": len(ranked),
        "analyzed_frames": int(data.get("analyzed_frames") or 0),
        "coverage_percent": round((with_faces / total * 100.0) if total else 0.0, 1),
        "dominant_tracks": [t.get("id") for t in ranked[:4] if t.get("id")],
        "fallback_reason": data.get("fallback_reason"),
        "model_available": YUNET_MODEL.exists(),
        "sampling": data.get("sampling") or "sequential",
    }


class _Detector:
    backend = "none"
    def detect(self, frame: np.ndarray) -> list[dict[str, Any]]:
        return []


class _YuNetDetector(_Detector):
    backend = "yunet"
    def __init__(self, model_path: Path):
        self.detector = cv2.FaceDetectorYN.create(str(model_path), "", (320, 320), score_threshold=0.65, nms_threshold=0.3, top_k=100)

    def detect(self, frame: np.ndarray) -> list[dict[str, Any]]:
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []
        out = []
        for row in faces:
            x, y, bw, bh = row[:4]
            out.append({"box": normalize_box((x, y, bw, bh), w, h), "confidence": round(float(row[-1]), 4)})
        return out


class _HaarDetector(_Detector):
    backend = "haar"
    def __init__(self):
        path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        self.cascade = cv2.CascadeClassifier(str(path))

    def detect(self, frame: np.ndarray) -> list[dict[str, Any]]:
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = self.cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(36, 36))
        return [{"box": normalize_box((x, y, bw, bh), w, h), "confidence": 0.7} for x, y, bw, bh in faces]


def _build_detector(preferred: str | None = None) -> _Detector:
    preferred = str(preferred or "auto").lower()
    if preferred != "haar" and YUNET_MODEL.exists() and hasattr(cv2, "FaceDetectorYN"):
        try:
            return _YuNetDetector(YUNET_MODEL)
        except Exception:
            pass
    try:
        return _HaarDetector()
    except Exception:
        return _Detector()


def _lower_face_activity(frame: np.ndarray, box: list[float], previous_roi: np.ndarray | None) -> tuple[float, np.ndarray | None]:
    h, w = frame.shape[:2]
    x, y, bw, bh = box
    x1 = max(0, min(w - 1, int(x * w)))
    y1 = max(0, min(h - 1, int((y + bh * 0.52) * h)))
    x2 = max(x1 + 1, min(w, int((x + bw) * w)))
    y2 = max(y1 + 1, min(h, int((y + bh) * h)))
    roi = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if roi.size == 0:
        return 0.0, None
    roi = cv2.resize(roi, (48, 24), interpolation=cv2.INTER_AREA)
    if previous_roi is None:
        return 0.0, roi
    diff = cv2.absdiff(roi, previous_roi)
    return round(float(np.mean(diff)) / 255.0, 4), roi


def analyze_video(video_path: str | Path, out_path: str | Path | None = None, fps: float = 4.0) -> dict[str, Any]:
    video_path = Path(video_path)
    if out_path is None:
        out_path = TRACK_DIR / f"{video_path.stem}.json"
    out_path = Path(out_path)
    if not video_path.exists():
        return _save(empty_tracking("Vídeo de origem não encontrado"), out_path)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return _save(empty_tracking("OpenCV não conseguiu abrir o vídeo"), out_path)
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0); height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0); frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = (frame_count / native_fps) if native_fps > 0 and frame_count > 0 else 0.0
        sample_fps = max(0.5, min(8.0, float(fps or 4.0)))
        detector = _build_detector()
        tracks: dict[str, dict[str, Any]] = {}
        previous: dict[str, dict[str, Any]] = {}
        previous_roi: dict[str, np.ndarray] = {}
        next_id = 1; analyzed = 0; with_faces = 0

        # Decode forward once. Random seeking on H.264/AV1 repeatedly re-decodes
        # GOPs and was the largest tracking bottleneck on the target i5-4590.
        for t, frame in iter_sampled_frames(cap, native_fps, sample_fps, frame_count):
            fh, fw = frame.shape[:2]
            if fw > 720:
                ratio = 720.0 / fw
                detect_frame = cv2.resize(frame, (720, max(2, int(fh * ratio))), interpolation=cv2.INTER_AREA)
            else:
                detect_frame = frame
            detections = detector.detect(detect_frame)
            assignments, next_id = associate_detections(previous, detections, next_id=next_id)
            current: dict[str, dict[str, Any]] = {}
            if assignments:
                with_faces += 1
            for tid, det in assignments:
                raw = det["box"]
                prev = previous.get(tid, {}).get("box")
                box = smooth_box(prev, raw, 0.38) if prev else raw
                activity, roi = _lower_face_activity(frame, box, previous_roi.get(tid))
                if roi is not None:
                    previous_roi[tid] = roi
                sample = {
                    "t": round(t, 4), "box": box, "center": box_center(box),
                    "confidence": round(float(det.get("confidence", 0.0)), 4), "activity": activity,
                }
                track = tracks.setdefault(tid, {"id": tid, "samples": []})
                track["samples"].append(sample)
                current[tid] = {"box": box}
            previous = current
            analyzed += 1
        merged_tracks = merge_tracklets(list(tracks.values()))
        ranked = sorted(merged_tracks, key=lambda x: len(x["samples"]), reverse=True)
        for rank, track in enumerate(ranked, 1):
            track["rank"] = rank
            samples = track.get("samples") or []
            track["mean_activity"] = round(sum(float(s.get("activity", 0)) for s in samples) / max(1, len(samples)), 4)
        fallback = None if ranked else "Nenhum rosto detectado; layouts usarão crop de segurança"
        data = {
            "version": TRACK_VERSION,
            "backend": detector.backend,
            "source": {"width": width, "height": height, "duration": round(duration, 3), "fps": round(native_fps, 3)},
            "sample_fps": sample_fps,
            "sampling": "sequential",
            "analyzed_frames": analyzed,
            "total_samples": analyzed,
            "frames_with_faces": with_faces,
            "tracks": ranked,
            "fallback_reason": fallback,
        }
        return _save(data, out_path)
    except Exception as exc:
        return _save(empty_tracking(f"Falha no tracking: {exc}"), out_path)
    finally:
        cap.release()



def _window_cache_key(video_path: Path, start: float, end: float, fps: float, analysis_width: int) -> str:
    try:
        stat = video_path.stat()
        identity = f"{video_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except Exception:
        identity = str(video_path)
    raw = f"v{TRACK_VERSION + 1}|{identity}|{float(start):.3f}|{float(end):.3f}|{float(fps):.3f}|{int(analysis_width)}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def analyze_window(
    video_path: str | Path,
    start: float,
    end: float,
    *,
    out_path: str | Path | None = None,
    fps: float = 2.0,
    analysis_width: int = 640,
    progress_callback=None,
    cancel_check=None,
    detector_backend: str | None = None,
) -> dict[str, Any]:
    """Analyze faces only inside one source window.

    Timestamps remain absolute so existing slice/layout code can reuse the result.
    A single seek is used to enter the window, then decoding proceeds forward only
    until ``end``. This avoids the V3.1 full-video decode bottleneck.
    """
    video_path = Path(video_path)
    start = max(0.0, float(start or 0.0))
    end = max(start + 0.05, float(end or start + 0.05))
    sample_fps = max(0.25, min(8.0, float(fps or 1.0)))
    analysis_width = max(240, min(1280, int(analysis_width or 640)))
    cache_key = _window_cache_key(video_path, start, end, sample_fps, analysis_width)
    if out_path is None:
        out_path = TRACK_DIR / f"{video_path.stem}_{cache_key}.json"
    out_path = Path(out_path)
    if out_path.exists():
        try:
            cached = json.loads(out_path.read_text(encoding="utf-8"))
            if cached.get("cache_key") == cache_key:
                if progress_callback:
                    progress_callback(1.0, str(cached.get("backend") or "cache"))
                return cached
        except Exception:
            pass
    if not video_path.exists():
        data = empty_tracking("Vídeo de origem não encontrado")
        data.update({"cache_key": cache_key, "source_start": start, "source_end": end})
        return _save(data, out_path)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        data = empty_tracking("OpenCV não conseguiu abrir o vídeo")
        data.update({"cache_key": cache_key, "source_start": start, "source_end": end})
        return _save(data, out_path)
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = (frame_count / native_fps) if native_fps > 0 and frame_count > 0 else end
        end = min(end, duration) if duration > 0 else end
        start_frame = max(0, int(math.floor(start * native_fps)))
        end_frame = max(start_frame + 1, int(math.ceil(end * native_fps)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        sample_step = max(1, int(round(native_fps / sample_fps)))
        detector = _build_detector() if str(detector_backend or "auto").lower() == "auto" else _build_detector(detector_backend)
        tracks: dict[str, dict[str, Any]] = {}
        previous: dict[str, dict[str, Any]] = {}
        previous_roi: dict[str, np.ndarray] = {}
        next_id = 1
        analyzed = 0
        with_faces = 0
        frame_idx = start_frame
        total_frames = max(1, end_frame - start_frame)
        next_sample = start_frame

        while frame_idx <= end_frame:
            if cancel_check and cancel_check():
                raise RuntimeError("tracking_cancelled")
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx >= next_sample:
                fh, fw = frame.shape[:2]
                if fw > analysis_width:
                    ratio = analysis_width / float(fw)
                    detect_frame = cv2.resize(frame, (analysis_width, max(2, int(fh * ratio))), interpolation=cv2.INTER_AREA)
                else:
                    detect_frame = frame
                detections = detector.detect(detect_frame)
                assignments, next_id = associate_detections(previous, detections, next_id=next_id)
                current: dict[str, dict[str, Any]] = {}
                if assignments:
                    with_faces += 1
                t = min(end, frame_idx / max(0.001, native_fps))
                for tid, det in assignments:
                    raw = det["box"]
                    prev = previous.get(tid, {}).get("box")
                    box = smooth_box(prev, raw, 0.38) if prev else raw
                    activity, roi = _lower_face_activity(frame, box, previous_roi.get(tid))
                    if roi is not None:
                        previous_roi[tid] = roi
                    tracks.setdefault(tid, {"id": tid, "samples": []})["samples"].append({
                        "t": round(t, 4), "box": box, "center": box_center(box),
                        "confidence": round(float(det.get("confidence", 0.0)), 4), "activity": activity,
                    })
                    current[tid] = {"box": box}
                previous = current
                analyzed += 1
                next_sample += sample_step
            if progress_callback:
                progress_callback(min(0.999, max(0.0, (frame_idx - start_frame + 1) / total_frames)), detector.backend)
            frame_idx += 1

        merged_tracks = merge_tracklets(list(tracks.values()))
        ranked = sorted(merged_tracks, key=lambda x: len(x.get("samples") or []), reverse=True)
        for rank, track in enumerate(ranked, 1):
            track["rank"] = rank
            samples = track.get("samples") or []
            track["mean_activity"] = round(sum(float(x.get("activity", 0)) for x in samples) / max(1, len(samples)), 4)
        data = {
            "version": TRACK_VERSION + 1,
            "cache_key": cache_key,
            "backend": detector.backend,
            "source": {"width": width, "height": height, "duration": round(duration, 3), "fps": round(native_fps, 3)},
            "source_start": round(start, 4),
            "source_end": round(end, 4),
            "sample_fps": sample_fps,
            "analysis_width": analysis_width,
            "sampling": "window-sequential",
            "analyzed_frames": analyzed,
            "total_samples": analyzed,
            "frames_with_faces": with_faces,
            "tracks": ranked,
            "fallback_reason": None if ranked else "Nenhum rosto detectado nesta janela; safe crop será usado",
        }
        if progress_callback:
            progress_callback(1.0, detector.backend)
        return _save(data, out_path)
    except Exception as exc:
        data = empty_tracking(f"Falha no tracking da janela: {exc}")
        data.update({"version": TRACK_VERSION + 1, "cache_key": cache_key, "source_start": start, "source_end": end, "sampling": "window-sequential"})
        if progress_callback:
            progress_callback(1.0, "fallback")
        return _save(data, out_path)
    finally:
        cap.release()


def merge_window_tracks(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate window analysis for project diagnostics without changing clip-local IDs."""
    valid = [w for w in windows if isinstance(w, dict)]
    tracks: list[dict[str, Any]] = []
    analyzed = total = faces = 0
    backends: list[str] = []
    for idx, window in enumerate(valid, 1):
        analyzed += int(window.get("analyzed_frames") or 0)
        total += int(window.get("total_samples") or 0)
        faces += int(window.get("frames_with_faces") or 0)
        backend = str(window.get("backend") or "none")
        if backend not in backends:
            backends.append(backend)
        for track in window.get("tracks") or []:
            item = {k: v for k, v in track.items() if k != "id"}
            item["id"] = f"w{idx}_{track.get('id') or 'face'}"
            tracks.append(item)
    return {
        "version": TRACK_VERSION + 1,
        "backend": "+".join(backends) if backends else "none",
        "sampling": "clip-windows",
        "analyzed_frames": analyzed,
        "total_samples": total,
        "frames_with_faces": faces,
        "tracks": tracks,
        "fallback_reason": None if tracks else "Nenhum rosto detectado nos cortes selecionados",
        "windows": len(valid),
    }
