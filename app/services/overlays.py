from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .fonts import resolve_font


def _rgba(value: str | None, opacity: float = 1.0) -> tuple[int, int, int, int]:
    try:
        rgb = ImageColor.getrgb(value or "#000000")
    except Exception:
        rgb = (0, 0, 0)
    return (*rgb[:3], int(max(0.0, min(1.0, float(opacity))) * 255))


def _font(family: str | None, size: int) -> ImageFont.ImageFont:
    resolved = resolve_font(family)
    if resolved.get("path"):
        try:
            return ImageFont.truetype(resolved["path"], size)
        except Exception:
            pass
    try:
        return ImageFont.truetype("arialbd.ttf", size)
    except Exception:
        return ImageFont.load_default()


def compose_static_overlay(items: list[dict[str, Any]], out_path: Path, *, width: int = 1080, height: int = 1920) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    for item in sorted(items or [], key=lambda x: int(x.get("zIndex", x.get("z", 0)))):
        if item.get("hidden") or item.get("visible") is False:
            continue
        kind = str(item.get("type", "text"))
        x = int(item.get("x", 40))
        y = int(item.get("y", 80))
        w = int(item.get("width", width - x * 2))
        h = int(item.get("height", 120))
        opacity = float(item.get("opacity", 1.0))
        radius = int(item.get("radius", item.get("borderRadius", 18)))

        if kind in {"logo", "watermark", "image"} and item.get("path"):
            p = Path(item["path"])
            if not p.exists():
                continue
            try:
                im = Image.open(p).convert("RGBA")
                im.thumbnail((max(1, w), max(1, h)), Image.Resampling.LANCZOS)
                if opacity < 1:
                    alpha = im.getchannel("A").point(lambda a: int(a * opacity))
                    im.putalpha(alpha)
                canvas.alpha_composite(im, (x, y))
            except Exception:
                continue
            continue

        background = item.get("background") or item.get("backgroundColor")
        if background or kind in {"cta", "headline", "title-bar"}:
            bg = background or "#6D28D9"
            draw.rounded_rectangle((x, y, x + w, y + h), radius=max(0, radius), fill=_rgba(bg, opacity))

        text = str(item.get("text", "")).strip()
        if text:
            font_size = max(12, int(item.get("fontSize", 48)))
            font = _font(item.get("fontFamily", "Montserrat"), font_size)
            color = _rgba(item.get("color", "#ffffff"), opacity)
            align = item.get("align", "center")
            bbox = draw.multiline_textbbox((0, 0), text, font=font, align=align, stroke_width=int(item.get("strokeWidth", 0)))
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = x + (w - tw) // 2 if align == "center" else x + 20
            ty = y + (h - th) // 2
            draw.multiline_text(
                (tx, ty), text, font=font, fill=color, align=align,
                stroke_width=int(item.get("strokeWidth", 0)),
                stroke_fill=_rgba(item.get("strokeColor", "#000000"), opacity),
            )

    canvas.save(out_path)
    return out_path
