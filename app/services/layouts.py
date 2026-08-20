from __future__ import annotations

from copy import deepcopy
from typing import Any

LAYOUT_PRESETS = [
    {"id": "auto", "name": "Auto Inteligente", "description": "Escolhe o layout usando rostos detectados", "icon": "✨"},
    {"id": "single", "name": "Single", "description": "Uma pessoa acompanhada em tela cheia", "icon": "▯"},
    {"id": "center", "name": "Center", "description": "Vídeo central com fundo desfocado", "icon": "▭"},
    {"id": "split", "name": "Split", "description": "Dois participantes empilhados", "icon": "▤"},
    {"id": "split-vertical", "name": "Split Vertical", "description": "Dois participantes lado a lado", "icon": "▥"},
    {"id": "tri-split", "name": "Tri-Split", "description": "Três faixas com crops diferentes", "icon": "☷"},
    {"id": "tri-split-top", "name": "Tri-Split Top", "description": "Dois no topo e um painel principal", "icon": "▦"},
    {"id": "quad", "name": "Quad", "description": "Grade 2x2 com enquadramentos distintos", "icon": "▦"},
    {"id": "six-split", "name": "Six-Split", "description": "Grade de seis enquadramentos", "icon": "▦"},
    {"id": "react", "name": "React 30/70", "description": "Reação no topo e conteúdo principal", "icon": "◫"},
    {"id": "brainrot", "name": "Brainrot", "description": "Close + contexto em tela dividida", "icon": "▤"},
    {"id": "talking-broll", "name": "Talking Head + B-roll", "description": "Falante principal e contexto visual", "icon": "▱"},
    {"id": "podcast-top-bottom", "name": "Top/Bottom Podcast", "description": "Dois participantes em 50/50", "icon": "▤"},
    {"id": "podcast-dynamic", "name": "Podcast Dinâmico", "description": "Dois participantes com prioridade de atividade", "icon": "◧"},
    {"id": "choquei-movimento", "name": "Choquei + Movimento", "description": "Contexto, tarja central e close do falante", "icon": "▰"},
    {"id": "header-news", "name": "Header / Notícias", "description": "Cabeçalho visual, tarja e falante abaixo", "icon": "▱"},
    {"id": "story-documentary", "name": "Story / Documentário", "description": "Contexto principal com narrador em apoio", "icon": "▥"},
]
_LAYOUT_IDS = {p["id"] for p in LAYOUT_PRESETS}
_CONTEXT_ROLES = ["context", "left", "right", "wide", "upper", "lower"]


def list_layout_presets() -> list[dict[str, Any]]:
    return deepcopy(LAYOUT_PRESETS)


def _tracks(tracking: dict[str, Any] | None) -> list[dict[str, Any]]:
    tracks = [t for t in ((tracking or {}).get("tracks") or []) if t.get("samples")]
    return sorted(tracks, key=lambda t: (len(t.get("samples") or []), float(t.get("mean_activity") or 0)), reverse=True)


def _activity_tracks(tracking: dict[str, Any] | None) -> list[dict[str, Any]]:
    return sorted(_tracks(tracking), key=lambda t: (float(t.get("mean_activity") or _mean_activity(t)), len(t.get("samples") or [])), reverse=True)


def _mean_activity(track: dict[str, Any]) -> float:
    samples = track.get("samples") or []
    return sum(float(s.get("activity") or 0) for s in samples) / max(1, len(samples))


def resolve_layout_id(layout_id: str | None, speaker_count: int = 0, tracking: dict[str, Any] | None = None) -> str:
    layout_id = layout_id or "auto"
    if layout_id != "auto":
        return layout_id if layout_id in _LAYOUT_IDS else "single"
    if tracking is not None:
        count = len(_tracks(tracking))
        if count >= 3:
            return "tri-split"
        if count == 2:
            return "podcast-dynamic"
        return "single"
    if speaker_count >= 3:
        return "tri-split"
    if speaker_count == 2:
        return "split"
    return "single"


def _sample_points(track: dict[str, Any], axis: int, max_points: int = 10) -> list[tuple[float, float]]:
    samples = track.get("samples") or []
    if not samples:
        return []
    if len(samples) > max_points:
        step = (len(samples) - 1) / (max_points - 1)
        samples = [samples[round(i * step)] for i in range(max_points)]
    pts = []
    for s in samples:
        center = s.get("center") or [0.5, 0.5]
        pts.append((round(float(s.get("t") or 0), 3), round(float(center[axis]), 4)))
    return pts


def _piecewise_expr(track: dict[str, Any] | None, axis: int, default: float) -> str:
    if not track:
        return f"{default:.4f}"
    pts = _sample_points(track, axis)
    if not pts:
        return f"{default:.4f}"
    if len(pts) == 1:
        return f"{pts[0][1]:.4f}"
    # Piecewise-linear interpolation follows the tracked face without abrupt jumps.
    expr = f"{pts[-1][1]:.4f}"
    for idx in range(len(pts) - 2, -1, -1):
        t0, v0 = pts[idx]; t1, v1 = pts[idx + 1]
        span = max(0.001, t1 - t0)
        delta = v1 - v0
        segment = f"({v0:.4f}+({delta:.4f})*max(0,min(1,(t-{t0:.3f})/{span:.3f})))"
        expr = f"if(lt(t,{t1:.3f}),{segment},{expr})"
    return expr


def _activity_at(track: dict[str, Any], t: float, window: float = 1.2) -> float:
    samples = track.get("samples") or []
    if not samples:
        return 0.0
    half = max(0.05, window / 2.0)
    vals = [float(x.get("activity") or 0.0) for x in samples if abs(float(x.get("t") or 0.0) - t) <= half]
    if vals:
        return sum(vals) / len(vals)
    nearest = min(samples, key=lambda x: abs(float(x.get("t") or 0.0) - t))
    return float(nearest.get("activity") or 0.0)


def _dynamic_roles(tracking: dict[str, Any] | None, clip_duration: float | None) -> tuple[Any, Any]:
    tracks = _tracks(tracking)
    if len(tracks) < 2:
        roles = _panel_roles(tracking, 2)
        return roles[0], roles[1]
    duration = float(clip_duration or 0.0)
    if duration <= 0:
        duration = max((float(s.get("t") or 0) for tr in tracks for s in (tr.get("samples") or [])), default=1.0)
    step = 0.75
    raw = []
    t = 0.0
    while t < duration + 1e-6:
        ranked = sorted(tracks, key=lambda tr: (_activity_at(tr, t), len(tr.get("samples") or [])), reverse=True)
        raw.append((t, ranked[0], ranked[1] if len(ranked) > 1 else ranked[0]))
        t += step
    def compress(rank_idx: int):
        segments = []
        start = raw[0][0]
        current = raw[0][rank_idx]
        for i in range(1, len(raw)):
            candidate = raw[i][rank_idx]
            if candidate.get("id") != current.get("id"):
                segments.append({"start": start, "end": raw[i][0], "track": current})
                start = raw[i][0]; current = candidate
        segments.append({"start": start, "end": duration + step, "track": current})
        return {"dynamic_segments": segments}
    return compress(1), compress(2)


def ensure_layout_overlays(state: dict[str, Any], title: str) -> dict[str, Any]:
    out = deepcopy(state or {})
    lid = out.get("layout_preset_id") or "auto"
    recipes = {
        "choquei-movimento": {"x":55,"y":728,"width":970,"height":170,"fontSize":48,"background":"#DC2626"},
        "header-news": {"x":55,"y":585,"width":970,"height":150,"fontSize":42,"background":"#FF665A"},
        "story-documentary": {"x":45,"y":720,"width":990,"height":190,"fontSize":44,"background":"#DC2626"},
    }
    overlays = [dict(x) for x in (out.get("overlays") or []) if not x.get("autoLayoutTitle")]
    if lid in recipes and str(title or "").strip():
        overlays.append({
            "type":"text", "text":str(title).strip().upper()[:120], "color":"#FFFFFF",
            "fontFamily":"Montserrat", "fontWeight":"900", "align":"center",
            "strokeWidth":1, "zIndex":65, "autoLayoutTitle":True, **recipes[lid],
        })
    out["overlays"] = overlays
    return out


def _role_center(role: Any, axis: int) -> str:
    if isinstance(role, dict) and role.get("dynamic_segments"):
        segments = role["dynamic_segments"]
        expr = _piecewise_expr(segments[-1]["track"], axis, 0.5 if axis == 0 else 0.42)
        for seg in reversed(segments[:-1]):
            part = _piecewise_expr(seg["track"], axis, 0.5 if axis == 0 else 0.42)
            expr = f"if(lt(t,{float(seg['end']):.3f}),{part},{expr})"
        return expr
    if isinstance(role, dict):
        return _piecewise_expr(role, axis, 0.5 if axis == 0 else 0.42)
    centers = {
        "context": (0.5, 0.5), "wide": (0.5, 0.5), "left": (0.28, 0.48),
        "right": (0.72, 0.48), "upper": (0.5, 0.30), "lower": (0.5, 0.70),
    }
    return f"{centers.get(str(role), (0.5, 0.5))[axis]:.4f}"


def _panel(label: str, w: int, h: int, role: Any = "context", *, zoom: float = 1.0) -> str:
    # Preserve aspect ratio, cover the panel, then follow the selected face/context center.
    # A mild zoom is achieved by asking scale to cover a slightly larger crop target.
    zoom = max(1.0, min(1.5, float(zoom)))
    target_w = max(2, int(round(w * zoom)) // 2 * 2)
    target_h = max(2, int(round(h * zoom)) // 2 * 2)
    cx = _role_center(role, 0); cy = _role_center(role, 1)
    x = f"max(0,min(iw-{w},({cx})*iw-{w}/2))"
    # Keep faces slightly above vertical center to leave subtitle room.
    y = f"max(0,min(ih-{h},({cy})*ih-{h}*0.42))"
    return (
        f"[{label}]setpts=PTS-STARTPTS,scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}:x='{x}':y='{y}'"
    )


def _split_input(n: int) -> tuple[str, list[str]]:
    labels = [f"s{i}" for i in range(n)]
    return f"[0:v]split={n}" + "".join(f"[{x}]" for x in labels), labels


def _panel_roles(tracking: dict[str, Any] | None, n: int, *, activity_first: bool = False) -> list[Any]:
    tracks = _activity_tracks(tracking) if activity_first else _tracks(tracking)
    roles: list[Any] = tracks[:n]
    i = 0
    while len(roles) < n:
        roles.append(_CONTEXT_ROLES[i % len(_CONTEXT_ROLES)])
        i += 1
    return roles


def _grid(n: int, panel_w: int, panel_h: int, positions: list[tuple[int, int]], tracking: dict[str, Any] | None = None, *, output_size: tuple[int, int] = (1080, 1920)) -> str:
    split, labels = _split_input(n)
    roles = _panel_roles(tracking, n)
    chains = [split]; out_labels = []
    for idx, label in enumerate(labels):
        out = f"p{idx}"
        chains.append(_panel(label, panel_w, panel_h, roles[idx], zoom=1.08 if isinstance(roles[idx], dict) else 1.0) + f"[{out}]")
        out_labels.append(f"[{out}]")
    layout = "|".join(f"{x}_{y}" for x, y in positions)
    chains.append("".join(out_labels) + f"xstack=inputs={n}:layout={layout}:fill=black[stacked]")
    chains.append(f"[stacked]scale={output_size[0]}:{output_size[1]}[vout]")
    return ";".join(chains)


def build_layout_filter(
    layout_id: str | None,
    face_centers: list[float] | None = None,
    config: dict[str, Any] | None = None,
    *,
    tracking: dict[str, Any] | None = None,
    output_size: tuple[int, int] = (1080, 1920),
    clip_duration: float | None = None,
) -> str:
    # Backward compatibility: older tests/callers pass face_centers only.
    if tracking is None and face_centers:
        tracking = {"tracks": [{"id": f"legacy_{i}", "samples": [{"t": 0.0, "center": [float(x), 0.42]}]} for i, x in enumerate(face_centers)]}
    config = config or {}
    W, H = (max(2, int(output_size[0])), max(2, int(output_size[1])))
    lid = resolve_layout_id(layout_id, speaker_count=len(face_centers or []), tracking=tracking if tracking is not None else None)

    if lid == "single":
        split, labels = _split_input(1)
        role = _panel_roles(tracking, 1)[0]
        return ";".join([split, _panel(labels[0], W, H, role, zoom=1.08 if isinstance(role, dict) else 1.0) + "[vout]"])

    if lid == "center":
        blur = max(0, min(40, int(float(config.get("backgroundBlur", 24) or 0))))
        return (
            "[0:v]split=2[bg0][fg0];"
            f"[bg0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma={blur}[bg];"
            f"[fg0]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
        )

    if lid in {"split", "podcast-top-bottom", "brainrot"}:
        half=H//2; return _grid(2, W, half, [(0, 0), (0, half)], tracking, output_size=(W,H))

    if lid == "podcast-dynamic":
        split, labels = _split_input(2); primary, secondary = _dynamic_roles(tracking, clip_duration)
        top_h=max(2,int(H*0.54)//2*2); bottom_h=max(2,H-top_h)
        return ";".join([
            split,
            _panel(labels[0], W, top_h, primary, zoom=1.1) + "[p0]",
            _panel(labels[1], W, bottom_h, secondary, zoom=1.05) + "[p1]",
            "[p0][p1]vstack=inputs=2[stacked]",
            f"[stacked]scale={W}:{H}[vout]",
        ])

    if lid == "split-vertical":
        half=W//2; return _grid(2, half, H, [(0, 0), (half, 0)], tracking, output_size=(W,H))

    if lid == "tri-split":
        third=H//3; return _grid(3, W, third, [(0, 0), (0, third), (0, third*2)], tracking, output_size=(W,H))

    if lid == "tri-split-top":
        split, labels = _split_input(3); roles = _panel_roles(tracking, 3)
        return ";".join([
            split,
            _panel(labels[0], W//2, int(H*0.375), roles[0]) + "[p0]",
            _panel(labels[1], W-W//2, int(H*0.375), roles[1]) + "[p1]",
            _panel(labels[2], W, H-int(H*0.375), roles[2]) + "[p2]",
            f"[p0][p1][p2]xstack=inputs=3:layout=0_0|{W//2}_0|0_{int(H*0.375)}:fill=black[stacked]",
            f"[stacked]scale={W}:{H}[vout]",
        ])

    if lid == "quad":
        pw=W//2; ph=H//2; return _grid(4, pw, ph, [(0,0),(pw,0),(0,ph),(pw,ph)], tracking, output_size=(W,H))

    if lid == "six-split":
        pw=W//3; ph=H//2; return _grid(6, pw, ph, [(0,0),(pw,0),(pw*2,0),(0,ph),(pw,ph),(pw*2,ph)], tracking, output_size=(W,H))

    if lid == "react":
        split, labels = _split_input(2); roles = _panel_roles(tracking, 2)
        return ";".join([
            split,
            _panel(labels[0], W, int(H*0.30), roles[1] if len(roles) > 1 else "context") + "[p0]",
            _panel(labels[1], W, H-int(H*0.30), roles[0], zoom=1.08) + "[p1]",
            "[p0][p1]vstack=inputs=2[stacked]",
            f"[stacked]scale={W}:{H}[vout]",
        ])

    if lid == "talking-broll":
        split, labels = _split_input(2); roles = _panel_roles(tracking, 2)
        return ";".join([
            split,
            _panel(labels[0], W, int(H*0.70), roles[0], zoom=1.08) + "[p0]",
            _panel(labels[1], W, H-int(H*0.70), roles[1] if isinstance(roles[1], dict) else "context") + "[p1]",
            "[p0][p1]vstack=inputs=2[stacked]",
            f"[stacked]scale={W}:{H}[vout]",
        ])

    if lid == "choquei-movimento":
        split, labels = _split_input(3); roles = _panel_roles(tracking, 2, activity_first=True)
        return ";".join([
            split,
            _panel(labels[0], W, int(H*0.365), "context") + "[top]",
            f"[s1]setpts=PTS-STARTPTS,scale={W}:{max(2,int(H*0.125))},drawbox=x=0:y=0:w=iw:h=ih:color=0xDC2626:t=fill[bar]",
            _panel(labels[2], W, H-int(H*0.365)-max(2,int(H*0.125)), roles[0], zoom=1.14) + "[bottom]",
            "[top][bar][bottom]vstack=inputs=3[stacked]",
            f"[stacked]scale={W}:{H}[vout]",
        ])

    if lid == "header-news":
        split, labels = _split_input(3); roles = _panel_roles(tracking, 1)
        return ";".join([
            split,
            _panel(labels[0], W, int(H*0.292), "context") + "[head]",
            f"[s1]setpts=PTS-STARTPTS,scale={W}:{max(2,int(H*0.115))},drawbox=x=0:y=0:w=iw:h=ih:color=0xFF665A:t=fill[bar]",
            _panel(labels[2], W, H-int(H*0.292)-max(2,int(H*0.115)), roles[0], zoom=1.1) + "[body]",
            "[head][bar][body]vstack=inputs=3[stacked]",
            f"[stacked]scale={W}:{H}[vout]",
        ])

    if lid == "story-documentary":
        split, labels = _split_input(2); roles = _panel_roles(tracking, 1)
        return ";".join([
            split,
            _panel(labels[0], W, int(H*0.688), "context") + "[main]",
            _panel(labels[1], W, H-int(H*0.688), roles[0], zoom=1.12) + "[speaker]",
            "[main][speaker]vstack=inputs=2[stacked]",
            f"[stacked]scale={W}:{H}[vout]",
        ])

    return build_layout_filter("single", tracking=tracking, config=config, output_size=(W,H), clip_duration=clip_duration)


def layout_preview_panels(layout_id: str) -> list[dict[str, int]]:
    lid = resolve_layout_id(layout_id, 0) if layout_id != "auto" else "single"
    mapping = {
        "single": [(0, 0, 100, 100)], "center": [(0, 32, 100, 36)],
        "split": [(0, 0, 100, 50), (0, 50, 100, 50)],
        "podcast-top-bottom": [(0, 0, 100, 50), (0, 50, 100, 50)],
        "podcast-dynamic": [(0, 0, 100, 54), (0, 54, 100, 46)],
        "brainrot": [(0, 0, 100, 50), (0, 50, 100, 50)],
        "split-vertical": [(0, 0, 50, 100), (50, 0, 50, 100)],
        "tri-split": [(0, 0, 100, 33), (0, 33, 100, 34), (0, 67, 100, 33)],
        "tri-split-top": [(0, 0, 50, 38), (50, 0, 50, 38), (0, 38, 100, 62)],
        "quad": [(0, 0, 50, 50), (50, 0, 50, 50), (0, 50, 50, 50), (50, 50, 50, 50)],
        "six-split": [(0, 0, 33, 50), (33, 0, 34, 50), (67, 0, 33, 50), (0, 50, 33, 50), (33, 50, 34, 50), (67, 50, 33, 50)],
        "react": [(0, 0, 100, 30), (0, 30, 100, 70)], "talking-broll": [(0, 0, 100, 70), (0, 70, 100, 30)],
        "choquei-movimento": [(0, 0, 100, 36), (0, 49, 100, 51)],
        "header-news": [(0, 0, 100, 29), (0, 41, 100, 59)],
        "story-documentary": [(0, 0, 100, 69), (0, 69, 100, 31)],
    }
    return [{"x": x, "y": y, "w": w, "h": h} for x, y, w, h in mapping.get(lid, mapping["single"])]
