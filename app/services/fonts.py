from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import FONT_DIR

FONT_REGISTRY = [
    {"family": "Bangers", "file": "Bangers-Regular.ttf", "open": True, "category": "viral"},
    {"family": "Anton", "file": "Anton-Regular.ttf", "open": True, "category": "viral"},
    {"family": "Montserrat", "file": "Montserrat-Variable.ttf", "open": True, "category": "clean"},
    {"family": "Bebas Neue", "file": "BebasNeue-Regular.ttf", "open": True, "category": "viral"},
    {"family": "Oswald", "file": "Oswald-Variable.ttf", "open": True, "category": "clean"},
    {"family": "Roboto Condensed", "file": "RobotoCondensed-Variable.ttf", "open": True, "category": "clean"},
    {"family": "Archivo Black", "file": "ArchivoBlack-Regular.ttf", "open": True, "category": "viral"},
    {"family": "League Spartan", "file": "LeagueSpartan-Variable.ttf", "open": True, "category": "viral"},
    {"family": "Permanent Marker", "file": "PermanentMarker-Regular.ttf", "open": True, "category": "hand"},
    {"family": "Arial", "file": "arial.ttf", "open": False, "category": "system"},
    {"family": "Arial Black", "file": "ariblk.ttf", "open": False, "category": "system"},
    {"family": "Impact", "file": "impact.ttf", "open": False, "category": "system"},
    {"family": "Comic Sans MS", "file": "comic.ttf", "open": False, "category": "system"},
    {"family": "DejaVu Sans", "file": "DejaVuSans.ttf", "open": True, "category": "fallback"},
]
_BY_FAMILY = {f["family"].lower(): f for f in FONT_REGISTRY}


def list_fonts() -> list[dict[str, Any]]:
    fonts = deepcopy(FONT_REGISTRY)
    for item in fonts:
        resolved = _resolve_path_for_entry(item)
        item["available"] = bool(resolved)
        item["path"] = str(resolved) if resolved else None
    return fonts


def _windows_font_candidates(family: str) -> list[Path]:
    windir = Path(os.environ.get("WINDIR", "C:/Windows"))
    font_dir = windir / "Fonts"
    entry = _BY_FAMILY.get(family.lower())
    names = []
    if entry:
        names.append(entry["file"])
    aliases = {
        "arial": ["arial.ttf", "arialbd.ttf"],
        "arial black": ["ariblk.ttf"],
        "impact": ["impact.ttf"],
        "comic sans ms": ["comic.ttf", "comicbd.ttf"],
    }
    names.extend(aliases.get(family.lower(), []))
    return [font_dir / n for n in dict.fromkeys(names)]


def _resolve_path_for_entry(entry: dict[str, Any]) -> Path | None:
    local = FONT_DIR / entry["file"]
    if local.exists() and local.stat().st_size > 0:
        return local
    for candidate in _windows_font_candidates(entry["family"]):
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    # Common Linux fallback used by tests/dev; Windows users normally resolve above.
    if entry["family"] == "DejaVu Sans":
        for p in (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/dejavu/DejaVuSans.ttf")):
            if p.exists():
                return p
    return None


def resolve_font(family: str | None) -> dict[str, Any]:
    wanted = (family or "Arial").strip()
    entry = _BY_FAMILY.get(wanted.lower())
    if entry:
        path = _resolve_path_for_entry(entry)
        if path:
            source = "local" if Path(path).parent.resolve() == FONT_DIR.resolve() else "system"
            return {"family": entry["family"], "path": str(path), "source": source, "fallback": False}

    # Try system entry with the literal family name.
    for candidate in _windows_font_candidates(wanted):
        if candidate.exists():
            return {"family": wanted, "path": str(candidate), "source": "system", "fallback": False}

    for fallback_family in ("Arial", "DejaVu Sans"):
        fallback_entry = _BY_FAMILY[fallback_family.lower()]
        path = _resolve_path_for_entry(fallback_entry)
        if path:
            return {"family": fallback_family, "path": str(path), "source": "system", "fallback": True}
    return {"family": "Arial", "path": None, "source": "logical", "fallback": True}


def write_font_metadata() -> dict[str, Any]:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "fonts": list_fonts()}
    path = FONT_DIR / "fonts.json"
    rendered = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    if not path.exists() or path.read_text(encoding="utf-8") != rendered:
        path.write_text(rendered, encoding="utf-8")
    return data


def browser_font_css() -> str:
    lines = []
    for item in FONT_REGISTRY:
        path = FONT_DIR / item["file"]
        if path.exists() and path.stat().st_size > 0:
            family = item["family"].replace("'", "\\'")
            lines.append(f"@font-face{{font-family:'{family}';src:url('/font-files/{item['file']}') format('truetype');font-display:swap;font-style:normal;font-weight:100 900;}}")
    return "\n".join(lines)


def allowed_local_font(filename: str) -> Path | None:
    allowed = {item["file"] for item in FONT_REGISTRY if item.get("open")}
    if filename not in allowed:
        return None
    path = FONT_DIR / filename
    return path if path.exists() and path.is_file() else None
