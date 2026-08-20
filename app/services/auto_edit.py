from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from . import assets, editor, timeline
from .llm import chat_json, enabled as llm_enabled

INTENSITY = {
    "clean": {"broll_gap": 14.0, "broll_len": 2.8, "sfx_gap": 18.0, "effect_gap": 14.0, "max_broll_ratio": 0.24},
    "normal": {"broll_gap": 9.0, "broll_len": 3.4, "sfx_gap": 12.0, "effect_gap": 9.0, "max_broll_ratio": 0.36},
    "viral": {"broll_gap": 6.0, "broll_len": 3.8, "sfx_gap": 7.0, "effect_gap": 6.0, "max_broll_ratio": 0.48},
    "hyper": {"broll_gap": 4.0, "broll_len": 4.2, "sfx_gap": 4.5, "effect_gap": 3.5, "max_broll_ratio": 0.58},
}

STYLE_HINTS = {
    "podcast-viral": "podcast conversation speaker reaction social media",
    "noticias": "news journalism headline city government",
    "politica": "politics government congress election brasilia",
    "financas": "money finance economy market business dollar",
    "fofoca": "reaction social media phone surprise people",
    "documentario": "documentary cinematic context history city nature",
    "gaming": "gaming computer controller technology reaction",
    "storytelling": "story people city travel emotion cinematic",
    "mrbeast-like": "fast energetic challenge reaction money surprise",
}

STRONG_TERMS = {
    "absurdo", "inacreditavel", "inacreditável", "recorde", "maior", "menor", "segredo", "verdade", "chocante",
    "explodiu", "caiu", "subiu", "crise", "morreu", "crime", "preso", "milhao", "milhão", "bilhao", "bilhão",
    "nunca", "sempre", "alerta", "urgente", "surpresa", "revelou", "confessou", "polemica", "polêmica",
}


def _segments(cues: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    if not cues:
        return []
    out: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for cue in cues:
        if current and float(cue["start_time"]) - float(current[-1]["end_time"]) > 1.25:
            out.append(_merge(current))
            current = []
        current.append(cue)
        span = float(current[-1]["end_time"]) - float(current[0]["start_time"])
        text = " ".join(str(x.get("text") or "") for x in current)
        if span >= 3.6 or re.search(r"[.!?][\"')\]]?$", text.strip()):
            out.append(_merge(current))
            current = []
    if current:
        out.append(_merge(current))
    # Keep only valid clip-local times.
    return [s for s in out if s["start"] < duration and s["end"] > 0]


def _merge(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "start": max(0.0, float(items[0]["start_time"])),
        "end": max(float(items[0]["start_time"]) + 0.05, float(items[-1]["end_time"])),
        "text": " ".join(str(x.get("text") or "").strip() for x in items).strip(),
    }


def _strong(text: str) -> bool:
    low = text.lower()
    return any(term in low for term in STRONG_TERMS) or bool(re.search(r"\b\d+[,.]?\d*\s*%", low))


def _asset_ref(data: dict[str, Any], asset: dict[str, Any]) -> str:
    aid = str(asset.get("id") or timeline.new_item_id("asset"))
    data.setdefault("assets", {})[aid] = {
        "id": aid,
        "type": asset.get("kind") or "asset",
        "path": asset.get("local_path") or "",
        "name": asset.get("name") or aid,
        "provider": asset.get("provider") or "local",
        "license": asset.get("license") or "unknown",
        "attribution": asset.get("attribution") or "",
        "sourceUrl": asset.get("source_url") or "",
        "duration": asset.get("duration"),
        "metadata": asset.get("metadata") or {},
    }
    return aid


def _clear_previous_auto_items(data: dict[str, Any]) -> None:
    for kind in {"broll", "sfx", "music", "effects"}:
        tr = timeline.track(data, kind)
        tr["items"] = [i for i in tr.get("items", []) if i.get("generatedBy") != "auto-edit"]
    data["markers"] = [m for m in data.get("markers", []) if m.get("generatedBy") != "auto-edit"]




def _director_scenes(cues: list[dict[str, Any]], duration: float, style: str, intensity: str) -> list[dict[str, Any]]:
    """Build editable scene-level camera/layout decisions from speaker cues.

    The rules are deterministic and local. They do not replace face tracking; they
    simply decide which existing layout preset should be active for a time range.
    """
    if duration <= 0:
        return []
    valid = [c for c in cues if str(c.get("text") or "").strip() and float(c.get("end_time") or 0) > 0]
    speakers = [str(c.get("speaker_id") or "").strip() for c in valid]
    unique_speakers = [x for i, x in enumerate(speakers) if x and x not in speakers[:i]]
    scenes: list[dict[str, Any]] = []
    if not valid:
        return [{"start": 0.0, "end": duration, "speaker": None, "layout": "single", "reason": "fallback"}]

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_speaker = None
    for cue in valid:
        speaker = str(cue.get("speaker_id") or "").strip() or None
        cue_start = max(0.0, float(cue.get("start_time") or 0))
        if current and (speaker != current_speaker or cue_start - float(current[-1].get("end_time") or 0) > 1.1):
            groups.append(current)
            current = []
        current.append(cue)
        current_speaker = speaker
    if current:
        groups.append(current)

    for idx, group in enumerate(groups):
        start = max(0.0, float(group[0].get("start_time") or 0))
        end = min(duration, max(start + 0.25, float(group[-1].get("end_time") or start + 0.25)))
        text = " ".join(str(c.get("text") or "") for c in group)
        speaker = str(group[0].get("speaker_id") or "").strip() or None
        strong = _strong(text) or any(bool(c.get("highlight")) for c in group)
        if len(unique_speakers) >= 2:
            if idx == 0 and style in {"podcast-viral", "fofoca", "storytelling"}:
                layout = "podcast-dynamic"
            elif strong and intensity in {"viral", "hyper"}:
                layout = "react"
            else:
                layout = "single"
        else:
            layout = "center" if style in {"noticias", "documentario"} and not strong else "single"
        scenes.append({"start": start, "end": end, "speaker": speaker, "layout": layout, "reason": "emphasis" if strong else "speaker"})

    # Fill long silent gaps with the context-friendly current layout rather than
    # creating tiny camera jumps. Adjacent identical scenes are merged.
    merged: list[dict[str, Any]] = []
    cursor = 0.0
    fallback = "podcast-dynamic" if len(unique_speakers) >= 2 else scenes[0]["layout"]
    for scene in scenes:
        start = min(duration, max(cursor, scene["start"]))
        if start - cursor > 0.4:
            merged.append({"start": cursor, "end": start, "speaker": None, "layout": fallback, "reason": "gap"})
        end = min(duration, max(start + 0.05, scene["end"]))
        candidate = {**scene, "start": start, "end": end}
        if merged and merged[-1]["layout"] == candidate["layout"] and merged[-1].get("speaker") == candidate.get("speaker") and abs(merged[-1]["end"] - candidate["start"]) < 0.45:
            merged[-1]["end"] = candidate["end"]
        else:
            merged.append(candidate)
        cursor = end
    if cursor < duration:
        merged.append({"start": cursor, "end": duration, "speaker": None, "layout": fallback, "reason": "tail"})
    return [x for x in merged if x["end"] - x["start"] >= 0.05]


def _llm_keywords(segments: list[dict[str, Any]], style: str) -> dict[int, str]:
    if not llm_enabled() or not segments:
        return {}
    sample = [{"i": i, "text": s["text"]} for i, s in enumerate(segments[:30])]
    result = chat_json(
        "Você é um diretor de edição. Para cada trecho, gere apenas uma consulta curta em inglês/português para procurar B-roll visual literal e seguro. Não invente fatos. Responda JSON {\"queries\":[{\"i\":0,\"query\":\"...\"}]}",
        f"Estilo: {style}\nTrechos: {sample}",
    )
    out: dict[int, str] = {}
    if result:
        for item in result.get("queries") or []:
            try:
                out[int(item["i"])] = str(item["query"]).strip()
            except Exception:
                pass
    return out


def build_auto_edit_plan(
    clip_id: str,
    *,
    style: str = "podcast-viral",
    intensity: str = "normal",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    profile = INTENSITY.get(intensity, INTENSITY["normal"])
    intensity = intensity if intensity in INTENSITY else "normal"
    data = timeline.get_or_create_timeline(clip_id)
    data = deepcopy(data)
    _clear_previous_auto_items(data)
    duration = float(data["composition"]["duration"])
    cues = editor.list_caption_cues(clip_id)
    segments = _segments(cues, duration)
    llm_queries = _llm_keywords(segments, style) if options.get("use_llm") else {}
    style_hint = STYLE_HINTS.get(style, STYLE_HINTS["podcast-viral"])
    orientation = "vertical" if data["composition"]["height"] >= data["composition"]["width"] else "horizontal"

    broll_track = timeline.track(data, "broll")
    sfx_track = timeline.track(data, "sfx")
    effects_track = timeline.track(data, "effects")
    music_track = timeline.track(data, "music")
    decisions: list[dict[str, Any]] = []
    last_broll = -999.0
    last_sfx = -999.0
    last_effect = -999.0
    broll_covered = 0.0
    max_broll = duration * float(profile["max_broll_ratio"])

    director_scenes: list[dict[str, Any]] = []
    if options.get("director", True):
        director_scenes = _director_scenes(cues, duration, style, intensity)
        for scene in director_scenes:
            effects_track["items"].append({
                "id": timeline.new_item_id("director"), "type": "director-layout",
                "from": round(float(scene["start"]), 3), "duration": round(float(scene["end"] - scene["start"]), 3),
                "layoutPresetId": scene["layout"], "speakerId": scene.get("speaker"),
                "reason": scene.get("reason"), "generatedBy": "auto-edit", "zIndex": 1,
            })
            decisions.append({"action": "layout", "time": scene["start"], "duration": scene["end"]-scene["start"], "layout": scene["layout"], "speaker": scene.get("speaker"), "reason": scene.get("reason")})

    # First frame gets a restrained hook treatment except in clean mode.
    if intensity != "clean" and duration > 1.0:
        effects_track["items"].append({
            "id": timeline.new_item_id("fx"), "type": "effect", "effectId": "zoom-punch", "from": 0.05,
            "duration": min(0.4, duration), "config": {"type": "zoom", "scale": 1.10 if intensity == "normal" else 1.14},
            "generatedBy": "auto-edit", "zIndex": 90,
        })
        data.setdefault("markers", []).append({"id": timeline.new_item_id("marker"), "time": 0.05, "type": "hook", "label": "Hook / punch zoom", "generatedBy": "auto-edit"})
        decisions.append({"action": "effect", "time": 0.05, "effect": "zoom-punch", "reason": "hook"})
        last_effect = 0.05

    for idx, seg in enumerate(segments):
        start, end, text = seg["start"], min(duration, seg["end"]), seg["text"]
        if end <= start:
            continue
        query = llm_queries.get(idx) or text
        query_for_search = f"{query} {style_hint}".strip()
        is_strong = _strong(text)

        eligible_broll = start - last_broll >= float(profile["broll_gap"])
        if is_strong and intensity in {"viral", "hyper"}:
            eligible_broll = eligible_broll or start - last_broll >= float(profile["broll_gap"]) * 0.65
        if eligible_broll and broll_covered < max_broll and options.get("broll", True):
            matches = assets.search_assets(query_for_search, kind="broll", limit=3, orientation=orientation)
            if matches:
                match = matches[0]
                length = min(float(profile["broll_len"]), max(1.2, end - start + 0.6), max(0.0, max_broll - broll_covered), max(0.0, duration - start))
                if length >= 1.0:
                    aid = _asset_ref(data, match)
                    broll_track["items"].append({
                        "id": timeline.new_item_id("broll"), "type": "broll", "assetId": aid, "from": start,
                        "duration": length, "sourceStart": 0.0, "mode": "cover", "opacity": 1.0,
                        "transitionIn": "fade" if intensity == "clean" else "cut", "generatedBy": "auto-edit", "zIndex": 30,
                        "query": query, "kenBurns": bool(str(match.get("kind") or "").lower() in {"image", "photo"}),
                    })
                    broll_covered += length
                    last_broll = start
                    decisions.append({"action": "broll", "time": start, "duration": length, "query": query, "asset": match.get("name"), "score": match.get("score")})
                    data["markers"].append({"id": timeline.new_item_id("marker"), "time": start, "type": "broll", "label": match.get("name") or "B-roll", "generatedBy": "auto-edit"})

        if options.get("sfx", True) and (is_strong or idx == 0) and start - last_sfx >= float(profile["sfx_gap"]):
            matches = assets.search_assets("impact hook dramatic" if is_strong or idx == 0 else "whoosh transition", kind="sfx", limit=2)
            if matches:
                match = matches[0]
                aid = _asset_ref(data, match)
                sfx_track["items"].append({
                    "id": timeline.new_item_id("sfx"), "type": "sfx", "assetId": aid, "from": max(0.0, start),
                    "duration": min(float(match.get("duration") or 0.8), max(0.1, duration - start)), "volumeDb": -5 if intensity == "hyper" else -8,
                    "generatedBy": "auto-edit", "zIndex": 80,
                })
                last_sfx = start
                decisions.append({"action": "sfx", "time": start, "asset": match.get("name"), "reason": "strong phrase" if is_strong else "hook"})

        if options.get("effects", True) and (is_strong or (intensity == "hyper" and idx % 2 == 0)) and start - last_effect >= float(profile["effect_gap"]):
            effect_id = "shake" if is_strong and intensity == "hyper" else "smart-zoom"
            effects_track["items"].append({
                "id": timeline.new_item_id("fx"), "type": "effect", "effectId": effect_id, "from": start,
                "duration": 0.30 if effect_id == "shake" else min(1.2, max(0.2, duration - start)),
                "config": {"type": "shake", "amount": 7} if effect_id == "shake" else {"type": "zoom", "scale": 1.06},
                "generatedBy": "auto-edit", "zIndex": 90,
            })
            last_effect = start
            decisions.append({"action": "effect", "time": start, "effect": effect_id, "reason": "emphasis"})

    # One global filter is enough; stacking LUT-like filters is visually destructive.
    if options.get("filters", True):
        filter_query = {
            "financas": "cool technology news contrast",
            "noticias": "cool news contrast",
            "documentario": "cinematic film",
            "fofoca": "high contrast viral",
        }.get(style, "cinematic contrast")
        match = (assets.search_assets(filter_query, kind="filter", limit=1) or [None])[0]
        if match:
            effects_track["items"].append({
                "id": timeline.new_item_id("filter"), "type": "filter", "effectId": match.get("id"), "from": 0.0,
                "duration": duration, "config": match.get("metadata") or {}, "generatedBy": "auto-edit", "zIndex": 5,
            })
            decisions.append({"action": "filter", "time": 0.0, "effect": match.get("name")})

    if options.get("music", True):
        music = assets.search_assets(f"{style_hint} background subtle", kind="music", limit=1)
        if music:
            match = music[0]
            aid = _asset_ref(data, match)
            music_track["items"].append({
                "id": timeline.new_item_id("music"), "type": "music", "assetId": aid, "from": 0.0,
                "duration": duration, "sourceStart": 0.0, "volumeDb": -24 if intensity in {"clean", "normal"} else -20,
                "ducking": True, "loop": True, "generatedBy": "auto-edit", "zIndex": 10,
            })
            decisions.append({"action": "music", "time": 0.0, "asset": match.get("name")})

    if options.get("progress", True) and duration >= 8.0:
        effects_track["items"].append({
            "id": timeline.new_item_id("progress"), "type": "effect", "effectId": "progress-bar", "from": 0.0,
            "duration": duration, "config": {"type": "progress-bar", "height": 10, "segments": 24, "color": "white@0.90"},
            "generatedBy": "auto-edit", "zIndex": 98,
        })
        decisions.append({"action": "progress-bar", "time": 0.0, "duration": duration})

    data.setdefault("metadata", {})["autoEdit"] = {
        "version": 2,
        "style": style,
        "intensity": intensity,
        "decisions": decisions,
        "brollCoverageSeconds": round(broll_covered, 3),
        "brollCoverageRatio": round(broll_covered / duration, 4) if duration else 0.0,
        "directorScenes": len(director_scenes),
        "editable": True,
    }
    return timeline.save_timeline(clip_id, data)
