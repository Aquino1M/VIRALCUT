from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

BASE_CAPTION = {
    "fontFamily": "Arial",
    "fontSize": 68,
    "fontWeight": "700",
    "textCase": "original",
    "align": "center",
    "positionX": 540,
    "positionY": 1280,
    "maxWidth": 900,
    "maxLines": 2,
    "wordsPerPage": 4,
    "lineHeight": 1.15,
    "letterSpacing": 0,
    "primaryColor": "#ffffff",
    "secondaryColor": "#7c5cff",
    "strokeColor": "#000000",
    "strokeWidth": 5,
    "shadowColor": "#000000",
    "shadowDepth": 2,
    "backgroundColor": "#000000",
    "backgroundOpacity": 0,
    "backgroundRadius": 0,
    "pageDurationMs": 1000,
    "minWordDurationMs": 80,
    "animationType": "none",
    "animationDuration": 0.25,
    "scaleAmount": 0.15,
    "popScalePeak": 1.08,
    "popFontSizeBoost": 0.12,
    "popDurationMs": 220,
    "fadeInMs": 0,
    "fadeOutMs": 0,
    "enableEmojis": True,
}


def _preset(pid: str, name: str, description: str, **cfg: Any) -> dict[str, Any]:
    merged = {**BASE_CAPTION, **cfg}
    return {"id": pid, "name": name, "description": description, "config": merged}


CAPTION_PRESETS = [
    _preset(
        "green-fresh", "Verde Fresco", "Palavra ativa verde com pop forte", fontFamily="Bangers",
        fontSize=75, fontWeight="900", textCase="upper", maxLines=1, wordsPerPage=3,
        primaryColor="#ffffff", secondaryColor="#76FF03", strokeColor="#000000", strokeWidth=10,
        pageDurationMs=900, animationType="scaling-words", animationDuration=2.5,
        scaleAmount=0.4, popScalePeak=1.1, popFontSizeBoost=0.24, popDurationMs=1000,
        positionY=1200,
    ),
    _preset(
        "rainbow-fun", "Rainbow Fun", "Destaque vibrante e rápido", fontFamily="Bangers",
        fontSize=68, fontWeight="900", textCase="upper", maxLines=1, wordsPerPage=3,
        primaryColor="#ffffff", secondaryColor="#FF3D7F", strokeWidth=9, pageDurationMs=500,
        animationType="rainbow", animationDuration=3.0, positionY=1220,
    ),
    _preset(
        "cariani", "Renato Cariani", "Visual amarelo de alta energia", fontFamily="Anton",
        fontSize=78, fontWeight="700", textCase="upper", primaryColor="#ffffff",
        secondaryColor="#FFD600", strokeWidth=9, wordsPerPage=2, maxLines=2,
        animationType="word-pop", popScalePeak=1.12, positionY=1230,
    ),
    _preset(
        "mrbeast", "MrBeast", "Palavras grandes com destaque amarelo", fontFamily="Anton",
        fontSize=82, fontWeight="900", textCase="upper", primaryColor="#ffffff",
        secondaryColor="#FFF200", strokeWidth=10, wordsPerPage=3, maxLines=2,
        animationType="word-pop", popScalePeak=1.13, positionY=1160,
    ),
    _preset(
        "podcast-bold", "Podcast Bold", "Legibilidade para entrevistas e podcasts", fontFamily="Montserrat",
        fontSize=72, fontWeight="900", textCase="upper", primaryColor="#ffffff",
        secondaryColor="#A78BFA", strokeWidth=8, wordsPerPage=4, maxLines=2,
        animationType="word-pop", positionY=1250,
    ),
    _preset(
        "minimal-clean", "Minimal Clean", "Legenda limpa sem distrações", fontFamily="Montserrat",
        fontSize=58, fontWeight="700", primaryColor="#ffffff", secondaryColor="#ffffff",
        strokeWidth=3, wordsPerPage=6, maxLines=2, animationType="none", positionY=1420,
    ),
    _preset(
        "karaoke", "Karaoke", "Destaque contínuo palavra por palavra", fontFamily="Montserrat",
        fontSize=70, fontWeight="900", textCase="upper", primaryColor="#D8D8E2",
        secondaryColor="#20D3B0", strokeWidth=6, wordsPerPage=5, animationType="karaoke", positionY=1270,
    ),
    _preset(
        "word-pop", "Word Pop", "Cada palavra ganha escala ao entrar", fontFamily="Bangers",
        fontSize=76, fontWeight="900", textCase="upper", primaryColor="#ffffff",
        secondaryColor="#FF7A00", strokeWidth=9, wordsPerPage=3, animationType="word-pop",
        popScalePeak=1.15, positionY=1210,
    ),
    _preset(
        "classic", "Classic Subtitle", "Estilo tradicional e acessível", fontFamily="Arial",
        fontSize=54, fontWeight="700", primaryColor="#ffffff", secondaryColor="#ffffff",
        strokeWidth=3, wordsPerPage=8, maxLines=2, animationType="none", positionY=1580,
    ),
    _preset(
        "neon", "Neon", "Visual neon para conteúdo gamer", fontFamily="Bebas Neue",
        fontSize=76, fontWeight="700", textCase="upper", primaryColor="#ffffff",
        secondaryColor="#00F5FF", strokeColor="#3D0078", strokeWidth=8, shadowDepth=4,
        wordsPerPage=3, animationType="word-pop", positionY=1210,
    ),
    _preset(
        "breaking-news", "Breaking / News", "Faixa forte para notícias e política", fontFamily="Montserrat",
        fontSize=64, fontWeight="900", textCase="upper", primaryColor="#ffffff",
        secondaryColor="#FF4444", backgroundColor="#A60000", backgroundOpacity=0.78,
        strokeWidth=2, wordsPerPage=5, maxLines=2, animationType="none", positionY=1450,
    ),
    _preset(
        "clean-box", "Clean Box", "Caixa discreta com leitura confortável", fontFamily="Roboto Condensed",
        fontSize=60, fontWeight="700", primaryColor="#ffffff", secondaryColor="#A78BFA",
        backgroundColor="#080A0F", backgroundOpacity=0.72, strokeWidth=2, wordsPerPage=6,
        maxLines=2, animationType="word-pop", positionY=1420,
    ),
    _preset(
        "after-effects-01", "After Effects 01", "Pop rápido com palavra-chave amarela", fontFamily="Anton",
        fontSize=82, fontWeight="900", textCase="upper", primaryColor="#FFFFFF", secondaryColor="#FFE600",
        strokeColor="#000000", strokeWidth=8, wordsPerPage=3, maxLines=2, animationType="word-pop",
        popScalePeak=1.16, popFontSizeBoost=0.16, popDurationMs=240, positionY=1220,
    ),
    _preset(
        "after-effects-02", "After Effects 02", "Legenda editorial grande com contraste forte", fontFamily="Montserrat",
        fontSize=88, fontWeight="900", textCase="upper", primaryColor="#FFFFFF", secondaryColor="#FFD817",
        strokeColor="#000000", strokeWidth=5, wordsPerPage=4, maxLines=2, animationType="scaling-words",
        popScalePeak=1.10, pageDurationMs=650, positionY=1260,
    ),
    _preset(
        "after-effects-03", "After Effects 03", "Bangers com destaque verde e entrada agressiva", fontFamily="Bangers",
        fontSize=86, fontWeight="900", textCase="upper", primaryColor="#FFFFFF", secondaryColor="#69FF00",
        strokeColor="#000000", strokeWidth=10, wordsPerPage=3, maxLines=2, animationType="word-pop",
        popScalePeak=1.18, popFontSizeBoost=0.20, popDurationMs=210, positionY=1200,
    ),
]

_PRESET_MAP = {p["id"]: p for p in CAPTION_PRESETS}


def list_caption_presets() -> list[dict[str, Any]]:
    return deepcopy(CAPTION_PRESETS)


def _clamp(v: Any, low: float, high: float, default: float) -> float:
    try:
        return max(low, min(high, float(v)))
    except (TypeError, ValueError):
        return default


def _color(value: Any, default: str) -> str:
    s = str(value or "").strip()
    if len(s) == 7 and s.startswith("#"):
        try:
            int(s[1:], 16)
            return s
        except ValueError:
            pass
    return default


def resolve_caption_config(preset_id: str | None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    preset = _PRESET_MAP.get(preset_id or "") or _PRESET_MAP["green-fresh"]
    cfg = deepcopy(preset["config"])
    if overrides:
        cfg.update(overrides)
    if "pageDurationInMilliseconds" in cfg:
        cfg["pageDurationMs"] = cfg.get("pageDurationInMilliseconds")

    cfg["fontSize"] = int(_clamp(cfg.get("fontSize"), 18, 180, 68))
    cfg["strokeWidth"] = int(_clamp(cfg.get("strokeWidth"), 0, 20, 5))
    cfg["shadowDepth"] = int(_clamp(cfg.get("shadowDepth"), 0, 20, 2))
    cfg["positionX"] = int(_clamp(cfg.get("positionX"), 0, 1080, 540))
    cfg["positionY"] = int(_clamp(cfg.get("positionY"), 0, 1920, 1280))
    cfg["maxWidth"] = int(_clamp(cfg.get("maxWidth"), 200, 1080, 900))
    cfg["maxLines"] = int(_clamp(cfg.get("maxLines"), 1, 6, 2))
    cfg["wordsPerPage"] = int(_clamp(cfg.get("wordsPerPage"), 1, 12, 4))
    cfg["lineHeight"] = _clamp(cfg.get("lineHeight"), 0.7, 2.0, 1.15)
    cfg["letterSpacing"] = _clamp(cfg.get("letterSpacing"), -5, 20, 0)
    cfg["pageDurationMs"] = int(_clamp(cfg.get("pageDurationMs"), 100, 4000, 1000))
    cfg["minWordDurationMs"] = int(_clamp(cfg.get("minWordDurationMs"), 30, 2000, 80))
    cfg["popScalePeak"] = _clamp(cfg.get("popScalePeak"), 1.0, 1.7, 1.08)
    cfg["popFontSizeBoost"] = _clamp(cfg.get("popFontSizeBoost"), 0, 0.8, 0.12)
    cfg["popDurationMs"] = int(_clamp(cfg.get("popDurationMs"), 40, 2500, 220))
    cfg["animationDuration"] = _clamp(cfg.get("animationDuration"), 0.05, 5.0, 0.25)
    cfg["scaleAmount"] = _clamp(cfg.get("scaleAmount"), 0.0, 0.8, 0.15)
    cfg["backgroundRadius"] = int(_clamp(cfg.get("backgroundRadius"), 0, 80, 0))
    cfg["fadeInMs"] = int(_clamp(cfg.get("fadeInMs"), 0, 3000, 0))
    cfg["fadeOutMs"] = int(_clamp(cfg.get("fadeOutMs"), 0, 3000, 0))
    cfg["backgroundOpacity"] = _clamp(cfg.get("backgroundOpacity"), 0, 1, 0)
    cfg["primaryColor"] = _color(cfg.get("primaryColor"), "#ffffff")
    cfg["secondaryColor"] = _color(cfg.get("secondaryColor"), "#7c5cff")
    cfg["strokeColor"] = _color(cfg.get("strokeColor"), "#000000")
    cfg["shadowColor"] = _color(cfg.get("shadowColor"), "#000000")
    cfg["backgroundColor"] = _color(cfg.get("backgroundColor"), "#000000")
    cfg["textCase"] = cfg.get("textCase") if cfg.get("textCase") in {"original", "upper", "lower"} else "original"
    cfg["align"] = cfg.get("align") if cfg.get("align") in {"left", "center", "right"} else "center"
    cfg["animationType"] = cfg.get("animationType") if cfg.get("animationType") in {"none", "word-pop", "scaling-words", "karaoke", "rainbow"} else "none"
    cfg["enableEmojis"] = bool(cfg.get("enableEmojis", True))
    return cfg


def hex_to_ass(color: str) -> str:
    color = _color(color, "#ffffff")[1:]
    r, g, b = color[0:2], color[2:4], color[4:6]
    return f"&H{b}{g}{r}&".upper().replace("X", "x")


def _ass_alpha(opacity: float) -> str:
    # ASS alpha is inverted: 00 opaque, FF transparent.
    alpha = 255 - int(max(0.0, min(1.0, opacity)) * 255)
    return f"{alpha:02X}"


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    seconds -= h * 3600
    m = int(seconds // 60)
    seconds -= m * 60
    s = int(seconds)
    cs = int(round((seconds - s) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def escape_ass_text(text: str) -> str:
    return str(text).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _case(text: str, mode: str) -> str:
    if mode == "upper":
        return text.upper()
    if mode == "lower":
        return text.lower()
    return text


def _group_cues(cues: Iterable[dict[str, Any]], words_per_page: int, page_duration_ms: int = 1000) -> list[list[dict[str, Any]]]:
    ordered = sorted((dict(c) for c in cues), key=lambda c: (float(c.get("start_time", 0)), int(c.get("word_index", 0))))
    pages: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    page_start = 0.0
    max_seconds = max(0.1, float(page_duration_ms) / 1000.0)
    for cue in ordered:
        cue_start = float(cue.get("start_time", 0))
        if current and (len(current) >= max(1, words_per_page) or cue_start - page_start >= max_seconds):
            pages.append(current); current = []
        if not current:
            page_start = cue_start
        current.append(cue)
    if current:
        pages.append(current)
    return pages


def _split_page_lines(page: list[dict[str, Any]], max_lines: int) -> list[list[dict[str, Any]]]:
    if not page:
        return []
    lines = max(1, min(int(max_lines or 1), len(page)))
    per_line = max(1, (len(page) + lines - 1) // lines)
    return [page[i:i + per_line] for i in range(0, len(page), per_line)][:lines]


def _line_positions(position_y: int, line_count: int, font_size: int, line_height: float) -> list[int]:
    if line_count <= 1:
        return [int(position_y)]
    spacing = max(1.0, float(font_size) * float(line_height))
    center = (line_count - 1) / 2.0
    return [int(round(position_y + (i - center) * spacing)) for i in range(line_count)]


def _alignment_code(align: str) -> int:
    return {"left": 1, "center": 2, "right": 3}.get(align, 2)


def _word_markup(page: list[dict[str, Any]], active_index: int, cfg: dict[str, Any]) -> str:
    primary = hex_to_ass(cfg["primaryColor"])
    secondary = hex_to_ass(cfg["secondaryColor"])
    rainbow = ["#FF3B30", "#FF9500", "#FFCC00", "#34C759", "#00C7BE", "#0A84FF", "#AF52DE", "#FF2D55"]
    parts = []
    for idx, cue in enumerate(page):
        word = escape_ass_text(_case(cue.get("text", ""), cfg["textCase"]))
        color = secondary if idx == active_index else primary
        if cfg["animationType"] == "rainbow":
            color = hex_to_ass(rainbow[idx % len(rainbow)])
        tags = [f"\\c{color}"]
        if idx == active_index and cfg["animationType"] == "word-pop":
            peak = int(round(float(cfg["popScalePeak"]) * 100))
            dur = int(cfg["popDurationMs"])
            tags.append(f"\\t(0,{dur},\\fscx{peak}\\fscy{peak})")
            tags.append(f"\\t({dur},{dur*2},\\fscx100\\fscy100)")
        elif idx == active_index and cfg["animationType"] == "scaling-words":
            peak = int(round((1.0 + float(cfg["scaleAmount"])) * 100))
            dur = int(cfg["popDurationMs"])
            tags.append(f"\\t(0,{dur},\\fscx{peak}\\fscy{peak})")
            tags.append(f"\\t({dur},{dur*2},\\fscx100\\fscy100)")
        parts.append("{" + "".join(tags) + "}" + word)
    return " ".join(parts)


def _karaoke_markup(line: list[dict[str, Any]], cfg: dict[str, Any]) -> str:
    parts = []
    for cue in line:
        word = escape_ass_text(_case(cue.get("text", ""), cfg["textCase"]))
        duration_cs = max(1, int(round(max(float(cue.get("end_time", 0)) - float(cue.get("start_time", 0)), cfg["minWordDurationMs"] / 1000.0) * 100)))
        parts.append(f"{{\\k{duration_cs}}}{word}")
    return " ".join(parts)


def build_ass(cues: list[dict[str, Any]], config: dict[str, Any], out_path: Path, *, width: int = 1080, height: int = 1920) -> Path:
    cfg = resolve_caption_config(None, config)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    align_code = _alignment_code(cfg["align"])
    primary = hex_to_ass(cfg["primaryColor"])
    stroke = hex_to_ass(cfg["strokeColor"])
    bg = hex_to_ass(cfg["backgroundColor"])
    bg_alpha = _ass_alpha(cfg["backgroundOpacity"])
    border_style = 3 if cfg['backgroundOpacity'] > 0 else 1
    header = f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: ViralClip,{cfg['fontFamily']},{cfg['fontSize']},{primary},{hex_to_ass(cfg['secondaryColor'])},{stroke},&H{bg_alpha}{bg[2:-1]},-1,0,0,0,100,100,{cfg['letterSpacing']},0,{border_style},{cfg['strokeWidth']},{cfg['shadowDepth']},{align_code},20,20,20,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    lines = [header]
    pages = _group_cues(cues, cfg["wordsPerPage"], cfg["pageDurationMs"])
    for page in pages:
        page_lines = _split_page_lines(page, cfg["maxLines"])
        positions = _line_positions(cfg["positionY"], len(page_lines), cfg["fontSize"], cfg["lineHeight"])
        page_start = float(page[0].get("start_time", 0))
        page_end = max(page_start + cfg["minWordDurationMs"] / 1000.0, float(page[-1].get("end_time", page_start + 0.2)))
        for line_idx, line in enumerate(page_lines):
            y = positions[line_idx]
            base_tags = f"{{\\pos({cfg['positionX']},{y})}}"
            if cfg["backgroundOpacity"] > 0:
                base_tags = f"{{\\pos({cfg['positionX']},{y})\\bord{cfg['strokeWidth']}}}"
            fade = f"{{\\fad({cfg['fadeInMs']},{cfg['fadeOutMs']})}}" if (cfg['fadeInMs'] or cfg['fadeOutMs']) else ""
            if cfg["animationType"] == "karaoke":
                markup = _karaoke_markup(line, cfg)
                lines.append(f"Dialogue: 0,{_ass_time(page_start)},{_ass_time(page_end)},ViralClip,,0,0,0,,{base_tags}{fade}{markup}\n")
                continue
            line_global_start = sum(len(x) for x in page_lines[:line_idx])
            for local_idx, cue in enumerate(line):
                global_idx = line_global_start + local_idx
                start = float(cue.get("start_time", 0))
                end = max(start + cfg["minWordDurationMs"] / 1000.0, float(cue.get("end_time", start + 0.2)))
                markup = _word_markup(page, global_idx, cfg)
                # Show only this visual line while retaining page-wide active styling.
                page_words = markup.split(" ")
                line_markup = " ".join(page_words[line_global_start:line_global_start + len(line)])
                lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},ViralClip,,0,0,0,,{base_tags}{fade}{line_markup}\n")
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def cues_from_transcript(transcript: dict[str, Any], clip_start: float, clip_end: float) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    idx = 0
    for seg in transcript.get("segments", []):
        if float(seg.get("end", 0)) < clip_start or float(seg.get("start", 0)) > clip_end:
            continue
        words = seg.get("words") or []
        if words:
            for word in words:
                wstart = float(word.get("start", 0))
                wend = float(word.get("end", wstart + 0.2))
                if wend < clip_start or wstart > clip_end:
                    continue
                cues.append({
                    "start_time": max(0.0, wstart - clip_start),
                    "end_time": max(0.01, wend - clip_start),
                    "text": str(word.get("word", "")).strip(),
                    "word_index": idx,
                    "speaker_id": word.get("speaker") or seg.get("speaker"),
                    "confidence": word.get("probability"),
                })
                idx += 1
        else:
            text = str(seg.get("text", "")).strip()
            if text:
                cues.append({
                    "start_time": max(0.0, float(seg.get("start", 0)) - clip_start),
                    "end_time": max(0.01, float(seg.get("end", 0)) - clip_start),
                    "text": text,
                    "word_index": idx,
                    "speaker_id": seg.get("speaker"),
                    "confidence": None,
                })
                idx += 1
    return cues
