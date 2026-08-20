from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import struct
import unicodedata
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from app.config import ASSET_DIR as CONFIG_ASSET_DIR

ASSET_DIR = CONFIG_ASSET_DIR
ASSET_CATALOG = ASSET_DIR / "catalog.json"
ASSET_PACK_MARKER = ASSET_DIR / ".lite_complete"
LITE_PACK_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
CATALOG_VERSION = 1

KIND_DIRS = {
    "broll": "broll",
    "sfx": "sfx",
    "music": "music",
    "overlay": "overlays",
    "effect": "effects",
    "filter": "filters",
    "transition": "transitions",
    "background": "backgrounds",
    "user": "user",
}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ogv", ".ogg"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

CONCEPTS = {
    "money": {"money", "cash", "dollar", "dolar", "dinheiro", "economia", "economy", "market", "mercado", "bolsa", "stock", "finance", "financas", "banco", "bank", "inflacao", "inflation", "preco", "price", "wealth"},
    "politics": {"politics", "politica", "government", "governo", "president", "presidente", "election", "eleicao", "congress", "congresso", "senate", "senado", "brasilia", "vote", "voto"},
    "technology": {"technology", "tecnologia", "computer", "computador", "phone", "celular", "smartphone", "internet", "ai", "ia", "software", "code", "codigo", "social", "rede", "digital"},
    "work": {"work", "trabalho", "job", "emprego", "office", "escritorio", "business", "negocio", "empresa", "worker", "trabalhador", "meeting", "reuniao"},
    "food": {"food", "comida", "restaurant", "restaurante", "supermarket", "supermercado", "meal", "refeicao", "coffee", "cafe", "kitchen", "cozinha"},
    "travel": {"travel", "viagem", "plane", "aviao", "airport", "aeroporto", "road", "estrada", "city", "cidade", "hotel", "beach", "praia", "tourism", "turismo"},
    "nature": {"nature", "natureza", "forest", "floresta", "tree", "arvore", "mountain", "montanha", "ocean", "mar", "river", "rio", "rain", "chuva", "sun", "sol"},
    "health": {"health", "saude", "hospital", "medical", "medico", "medicine", "remedio", "doctor", "exercise", "exercicio", "fitness", "academia"},
    "crime": {"crime", "police", "policia", "law", "lei", "court", "tribunal", "justice", "justica", "prison", "prisao", "security", "seguranca"},
    "emotion": {"happy", "feliz", "sad", "triste", "angry", "raiva", "fear", "medo", "shock", "choque", "surprise", "surpresa", "laugh", "risada", "cry", "choro"},
    "news": {"news", "noticia", "headline", "manchete", "journalism", "jornalismo", "report", "reportagem", "breaking"},
    "sports": {"sports", "esporte", "football", "futebol", "soccer", "stadium", "estadio", "game", "jogo", "athlete", "atleta"},
}
STOP = set("a o e de da do das dos um uma uns umas para por com sem em no na nos nas que se eu voce você ele ela nos nós voces vocês eles elas this that the and or to of in on for with is are was were be been".split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dir(kind: str) -> Path:
    return ASSET_DIR / KIND_DIRS.get(kind, kind)


def ensure_asset_dirs() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for dirname in KIND_DIRS.values():
        (ASSET_DIR / dirname).mkdir(parents=True, exist_ok=True)
    if not ASSET_CATALOG.exists():
        save_catalog({"version": CATALOG_VERSION, "assets": [], "updated_at": _now()})


def load_catalog() -> dict[str, Any]:
    ensure_asset_dirs()
    try:
        data = json.loads(ASSET_CATALOG.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("assets"), list):
            return data
    except Exception:
        pass
    return {"version": CATALOG_VERSION, "assets": [], "updated_at": _now()}


def save_catalog(data: dict[str, Any]) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["version"] = CATALOG_VERSION
    data["updated_at"] = _now()
    ASSET_CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _norm(text).split() if len(t) > 1 and t not in STOP}


def expanded_tokens(text: str) -> set[str]:
    toks = _tokens(text)
    expanded = set(toks)
    for canonical, terms in CONCEPTS.items():
        normalized_terms = {_norm(t) for t in terms}
        if toks & normalized_terms:
            expanded.add(canonical)
            expanded.update(normalized_terms)
    return expanded


def _virtual_path(value: str | Path) -> str | None:
    raw = str(value or "").strip().replace("\\", "/")
    match = re.match(r"^(effect|filter|transition):/{1,2}(.*)$", raw, flags=re.I)
    if not match:
        return None
    return f"{match.group(1).lower()}://{match.group(2).lstrip('/')}"


def _path_key(path: str | Path) -> str:
    virtual = _virtual_path(path)
    if virtual:
        return virtual.lower()
    try:
        return str(Path(path).resolve()).lower()
    except Exception:
        return str(path).lower()


def register_asset(
    kind: str,
    path: str | Path,
    *,
    name: str | None = None,
    tags: Iterable[str] | None = None,
    provider: str = "local",
    source_url: str = "",
    license_name: str = "local/user",
    attribution: str = "",
    orientation: str = "any",
    duration: float | None = None,
    asset_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_asset_dirs()
    virtual = _virtual_path(path)
    p = Path(path) if not virtual else None
    local_path = virtual or str(p)
    catalog = load_catalog()
    key = _path_key(local_path)
    existing = next((a for a in catalog["assets"] if _path_key(a.get("local_path", "")) == key), None)
    size = p.stat().st_size if p is not None and p.exists() and p.is_file() else 0
    record = {
        "id": asset_id or (existing or {}).get("id") or uuid.uuid4().hex[:16],
        "kind": kind,
        "name": name or (p.stem if p is not None else local_path.rsplit("/", 1)[-1]),
        "local_path": local_path,
        "tags": sorted({_norm(t) for t in (tags or []) if _norm(t)}),
        "provider": provider,
        "source_url": source_url,
        "license": license_name,
        "attribution": attribution,
        "orientation": orientation,
        "duration": duration,
        "size_bytes": size,
        "metadata": metadata or {},
        "updated_at": _now(),
    }
    if existing:
        catalog["assets"][catalog["assets"].index(existing)] = record
    else:
        catalog["assets"].append(record)
    save_catalog(catalog)
    return record


def scan_assets() -> list[dict[str, Any]]:
    ensure_asset_dirs()
    catalog = load_catalog()
    known = {_path_key(a.get("local_path", "")) for a in catalog["assets"]}
    for kind, dirname in KIND_DIRS.items():
        root = ASSET_DIR / dirname
        for path in root.rglob("*"):
            if not path.is_file() or path.name in {"catalog.json", "presets.json"}:
                continue
            if path.suffix.lower() not in VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS:
                continue
            if _path_key(path) in known:
                continue
            guessed_kind = kind
            register_asset(guessed_kind, path, tags=[path.stem.replace("_", " ")])
            known.add(_path_key(path))
    return load_catalog()["assets"]


def _record_score(record: dict[str, Any], query_tokens: set[str]) -> float:
    name_tokens = expanded_tokens(str(record.get("name") or ""))
    tag_tokens = set(record.get("tags") or [])
    meta_tokens = expanded_tokens(json.dumps(record.get("metadata") or {}, ensure_ascii=False))
    hay = name_tokens | tag_tokens | meta_tokens
    if not query_tokens:
        return 0.1
    direct = len(query_tokens & hay)
    score = direct * 3.0
    # Canonical concepts are high-value semantic-ish signals.
    canonical_hits = len((query_tokens & set(CONCEPTS)) & hay)
    score += canonical_hits * 2.5
    normalized_name = _norm(str(record.get("name") or ""))
    for token in query_tokens:
        if token and token in normalized_name:
            score += 0.8
    if record.get("provider") == "user":
        score += 0.2
    return score


def search_assets(query: str, *, kind: str | None = None, limit: int = 8, orientation: str | None = None) -> list[dict[str, Any]]:
    scan_assets()
    q = expanded_tokens(query)
    out = []
    for record in load_catalog()["assets"]:
        if kind and record.get("kind") != kind:
            continue
        if orientation and record.get("orientation") not in {orientation, "any", None, ""}:
            continue
        path = str(record.get("local_path") or "")
        if not _virtual_path(path) and path and not Path(path).exists():
            continue
        score = _record_score(record, q)
        if score <= 0:
            continue
        item = dict(record)
        item["score"] = round(score, 3)
        out.append(item)
    out.sort(key=lambda x: (x["score"], x.get("updated_at") or ""), reverse=True)
    return out[: max(1, min(100, int(limit)))]


def _tree_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and path != ASSET_CATALOG:
                total += path.stat().st_size
        except OSError:
            pass
    return total


def user_size_bytes() -> int:
    ensure_asset_dirs()
    return _tree_size(_dir("user"))


def current_size_bytes() -> int:
    """Size of the managed starter pack, excluding user-owned imports."""
    ensure_asset_dirs()
    total = 0
    user_root = _dir("user").resolve()
    for path in ASSET_DIR.rglob("*"):
        try:
            if not path.is_file() or path == ASSET_CATALOG:
                continue
            resolved = path.resolve()
            if user_root == resolved or user_root in resolved.parents:
                continue
            total += path.stat().st_size
        except OSError:
            pass
    return total


def get_asset(asset_id: str) -> dict[str, Any] | None:
    asset_id = str(asset_id or "")
    return next((dict(a) for a in load_catalog().get("assets", []) if str(a.get("id")) == asset_id), None)


def can_add_bytes(incoming_bytes: int, *, current_bytes: int | None = None, limit_bytes: int = LITE_PACK_LIMIT_BYTES) -> bool:
    current = current_size_bytes() if current_bytes is None else int(current_bytes)
    return current + max(0, int(incoming_bytes)) <= int(limit_bytes)


def starter_pack_status() -> dict[str, Any]:
    ensure_asset_dirs()
    catalog = load_catalog()
    size = current_size_bytes()
    counts: dict[str, int] = {}
    for a in catalog["assets"]:
        counts[a.get("kind", "unknown")] = counts.get(a.get("kind", "unknown"), 0) + 1
    return {
        "preset": "lite",
        "limit_bytes": LITE_PACK_LIMIT_BYTES,
        "size_bytes": size,
        "percent": round(min(100.0, size / LITE_PACK_LIMIT_BYTES * 100), 2),
        "initialized": ASSET_PACK_MARKER.exists(),
        "counts": counts,
        "user_size_bytes": user_size_bytes(),
    }


def _write_wav(path: Path, samples: list[float], rate: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = bytearray()
        for value in samples:
            v = max(-1.0, min(1.0, float(value)))
            frames += struct.pack("<h", int(v * 32767))
        wf.writeframes(bytes(frames))


def _tone(kind: str, duration: float, rate: int = 44100) -> list[float]:
    n = max(1, int(duration * rate))
    rnd = random.Random(1337 + len(kind))
    out: list[float] = []
    for i in range(n):
        t = i / rate
        x = i / max(1, n - 1)
        if kind == "click":
            val = math.sin(2 * math.pi * 1500 * t) * math.exp(-35 * t)
        elif kind == "pop":
            freq = 650 - 350 * x
            val = math.sin(2 * math.pi * freq * t) * math.exp(-9 * t)
        elif kind == "impact":
            val = (0.72 * math.sin(2 * math.pi * 62 * t) + 0.22 * (rnd.random() * 2 - 1)) * math.exp(-4.2 * t)
        elif kind == "whoosh":
            noise = rnd.random() * 2 - 1
            env = math.sin(math.pi * x) ** 1.8
            val = noise * env * 0.55
        elif kind == "riser":
            freq = 180 + 1200 * x * x
            val = math.sin(2 * math.pi * freq * t) * (x ** 1.6) * 0.5
        else:
            val = 0.0
        out.append(val)
    return out


def _music_wave(style: str, duration: float = 12.0, rate: int = 22050) -> list[float]:
    n = max(1, int(duration * rate))
    chords = {
        "ambient": (110.0, 164.81, 220.0),
        "suspense": (73.42, 110.0, 155.56),
        "upbeat": (130.81, 196.0, 261.63),
    }
    freqs = chords.get(style, chords["ambient"])
    out: list[float] = []
    for i in range(n):
        t = i / rate
        phase = (t % 4.0) / 4.0
        fade = min(1.0, t / 1.0, max(0.0, (duration - t) / 1.0))
        pad = sum(math.sin(2 * math.pi * f * t) for f in freqs) / len(freqs)
        if style == "suspense":
            pulse = math.sin(2 * math.pi * 2.0 * t) * 0.08
        elif style == "upbeat":
            beat_phase = t % 0.5
            pulse = math.exp(-18 * beat_phase) * math.sin(2 * math.pi * 70 * t) * 0.16
        else:
            pulse = math.sin(2 * math.pi * 0.25 * t) * 0.03
        out.append((pad * 0.12 + pulse) * fade)
    return out


def generate_offline_core() -> dict[str, int]:
    ensure_asset_dirs()
    sfx_specs = {
        "click": (0.16, ["click", "ui", "subtle"]),
        "pop": (0.34, ["pop", "word", "caption", "fun"]),
        "impact": (0.75, ["impact", "boom", "dramatic", "hook"]),
        "whoosh": (0.65, ["whoosh", "transition", "motion"]),
        "riser": (1.2, ["riser", "suspense", "build", "transition"]),
    }
    sfx_count = 0
    for name, (duration, tags) in sfx_specs.items():
        path = _dir("sfx") / f"viralclip_{name}.wav"
        if not path.exists():
            _write_wav(path, _tone(name, duration))
        register_asset("sfx", path, name=f"ViralClip {name.title()}", tags=tags, provider="viralclip", license_name="generated-by-viralclip", duration=duration)
        sfx_count += 1

    music_specs = {
        "ambient": ["ambient", "background", "subtle", "documentary", "podcast"],
        "suspense": ["suspense", "dramatic", "news", "politics", "crime"],
        "upbeat": ["upbeat", "viral", "gaming", "positive", "social"],
    }
    music_count = 0
    for name, tags in music_specs.items():
        duration = 12.0
        path = _dir("music") / f"viralclip_{name}_loop.wav"
        if not path.exists():
            _write_wav(path, _music_wave(name, duration, rate=22050), rate=22050)
        register_asset("music", path, name=f"ViralClip {name.title()} Loop", tags=tags, provider="viralclip", license_name="generated-by-viralclip", duration=duration)
        music_count += 1

    effects = [
        {"id": "zoom-punch", "name": "Zoom Punch", "kind": "effect", "tags": ["zoom", "hook", "impact"], "config": {"type": "zoom", "scale": 1.12, "duration": 0.35}},
        {"id": "smart-zoom", "name": "Smart Zoom", "kind": "effect", "tags": ["zoom", "speaker", "focus"], "config": {"type": "zoom", "scale": 1.06, "duration": 1.2}},
        {"id": "shake", "name": "Shake", "kind": "effect", "tags": ["shake", "impact", "shock"], "config": {"type": "shake", "amount": 8, "duration": 0.28}},
        {"id": "flash", "name": "Flash", "kind": "effect", "tags": ["flash", "transition"], "config": {"type": "flash", "duration": 0.12}},
        {"id": "blur-in", "name": "Blur In", "kind": "effect", "tags": ["blur", "transition"], "config": {"type": "blur", "radius": 8, "duration": 0.35}},
        {"id": "cinematic", "name": "Cinematic", "kind": "filter", "tags": ["cinematic", "contrast", "film"], "config": {"eq": "contrast=1.08:saturation=0.92:gamma=0.98"}},
        {"id": "warm", "name": "Warm", "kind": "filter", "tags": ["warm", "food", "people"], "config": {"eq": "contrast=1.03:saturation=1.08:gamma_r=1.04:gamma_b=0.97"}},
        {"id": "cool", "name": "Cool", "kind": "filter", "tags": ["cool", "technology", "news"], "config": {"eq": "contrast=1.04:saturation=0.96:gamma_b=1.05"}},
        {"id": "bw", "name": "Black & White", "kind": "filter", "tags": ["black white", "serious", "dramatic"], "config": {"eq": "saturation=0"}},
        {"id": "high-contrast", "name": "High Contrast", "kind": "filter", "tags": ["contrast", "viral", "news"], "config": {"eq": "contrast=1.16:saturation=1.06"}},
    ]
    effect_path = _dir("effect") / "presets.json"
    effect_path.write_text(json.dumps(effects, ensure_ascii=False, indent=2), encoding="utf-8")
    catalog = load_catalog()
    # Remove stale virtual presets before re-registering.
    catalog["assets"] = [a for a in catalog["assets"] if not _virtual_path(str(a.get("local_path", "")))]
    save_catalog(catalog)
    for preset in effects:
        kind = preset["kind"]
        register_asset(kind, f"{kind}://{preset['id']}", name=preset["name"], tags=preset["tags"], provider="viralclip", license_name="generated", metadata=preset["config"])

    transitions = [
        {"id": "cut", "name": "Cut", "tags": ["clean", "fast"]},
        {"id": "fade", "name": "Fade", "tags": ["soft", "documentary"]},
        {"id": "whip", "name": "Whip", "tags": ["fast", "viral", "whoosh"]},
        {"id": "slide", "name": "Slide", "tags": ["motion", "clean"]},
        {"id": "flash-cut", "name": "Flash Cut", "tags": ["flash", "impact"]},
    ]
    transition_path = _dir("transition") / "presets.json"
    transition_path.write_text(json.dumps(transitions, ensure_ascii=False, indent=2), encoding="utf-8")
    catalog = load_catalog()
    catalog["assets"] = [a for a in catalog["assets"] if not str(a.get("local_path", "")).startswith("transition://")]
    save_catalog(catalog)
    for preset in transitions:
        register_asset("transition", f"transition://{preset['id']}", name=preset["name"], tags=preset["tags"], provider="viralclip", license_name="generated")
    return {"sfx": sfx_count, "music": music_count, "effects": len(effects), "transitions": len(transitions)}


def _safe_name(value: str, fallback: str = "asset") -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", value or "").strip("._")
    return (name[:100] or fallback)


def _download(candidate: dict[str, Any], *, client: httpx.Client, limit_bytes: int = LITE_PACK_LIMIT_BYTES) -> dict[str, Any] | None:
    url = candidate.get("download_url") or candidate.get("url")
    if not url:
        return None
    current = current_size_bytes()
    try:
        with client.stream("GET", url, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            expected = int(response.headers.get("content-length") or 0)
            if expected and not can_add_bytes(expected, current_bytes=current, limit_bytes=limit_bytes):
                return None
            content_type = response.headers.get("content-type", "")
            suffix = Path(httpx.URL(str(response.url)).path).suffix.lower()
            if suffix not in VIDEO_EXTS:
                suffix = ".mp4" if "video" in content_type else ".bin"
            filename = _safe_name(f"{candidate.get('provider','stock')}_{candidate.get('id') or uuid.uuid4().hex[:8]}") + suffix
            path = _dir("broll") / filename
            written = 0
            with path.open("wb") as fh:
                for chunk in response.iter_bytes(1024 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if not can_add_bytes(written, current_bytes=current, limit_bytes=limit_bytes):
                        fh.close(); path.unlink(missing_ok=True); return None
                    fh.write(chunk)
        return register_asset(
            "broll", path, name=candidate.get("name") or path.stem, tags=candidate.get("tags") or [],
            provider=candidate.get("provider") or "stock", source_url=candidate.get("source_url") or "",
            license_name=candidate.get("license") or "provider-license", attribution=candidate.get("attribution") or "",
            orientation=candidate.get("orientation") or "any", duration=candidate.get("duration"), metadata=candidate.get("metadata") or {},
        )
    except Exception:
        return None


def search_pexels(query: str, *, api_key: str, limit: int = 6, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if not api_key:
        return []
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        r = client.get("https://api.pexels.com/v1/videos/search", headers={"Authorization": api_key}, params={"query": query, "per_page": min(20, limit), "orientation": "portrait"})
        r.raise_for_status()
        out = []
        for video in r.json().get("videos", []):
            files = sorted(video.get("video_files") or [], key=lambda f: (f.get("width") or 99999) * (f.get("height") or 99999))
            chosen = next((f for f in files if (f.get("width") or 0) >= 720 and (f.get("height") or 0) >= 720), files[-1] if files else None)
            if not chosen or not chosen.get("link"):
                continue
            out.append({"id": str(video.get("id")), "provider": "pexels", "name": query, "tags": list(expanded_tokens(query)), "download_url": chosen["link"], "source_url": video.get("url") or "", "license": "Pexels Content License", "attribution": f"Pexels / {video.get('user',{}).get('name','contributor')}", "duration": video.get("duration"), "orientation": "vertical" if (video.get("height") or 0) > (video.get("width") or 0) else "horizontal"})
        return out[:limit]
    finally:
        if own:
            client.close()


def search_pixabay(query: str, *, api_key: str, limit: int = 6, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if not api_key:
        return []
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        r = client.get("https://pixabay.com/api/videos/", params={"key": api_key, "q": query, "per_page": min(20, max(3, limit)), "safesearch": "true"})
        r.raise_for_status()
        out = []
        for hit in r.json().get("hits", []):
            videos = hit.get("videos") or {}
            chosen = videos.get("medium") or videos.get("small") or videos.get("large") or videos.get("tiny") or {}
            if not chosen.get("url"):
                continue
            tags = [t.strip() for t in str(hit.get("tags") or query).split(",") if t.strip()]
            out.append({"id": str(hit.get("id")), "provider": "pixabay", "name": hit.get("tags") or query, "tags": tags, "download_url": chosen["url"], "source_url": hit.get("pageURL") or "", "license": "Pixabay Content License", "attribution": f"Pixabay / {hit.get('user','contributor')}", "duration": hit.get("duration"), "orientation": "vertical" if (chosen.get("height") or 0) > (chosen.get("width") or 0) else "horizontal"})
        return out[:limit]
    finally:
        if own:
            client.close()


def search_wikimedia(query: str, *, limit: int = 6, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    own = client is None
    client = client or httpx.Client(timeout=30, headers={"User-Agent": "ViralClip/3.1 local-video-editor"})
    try:
        params = {
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{query} filetype:video", "gsrlimit": min(20, max(6, limit * 2)),
            "prop": "imageinfo", "iiprop": "url|mime|extmetadata|size",
        }
        r = client.get("https://commons.wikimedia.org/w/api.php", params=params)
        r.raise_for_status()
        out = []
        for page in (r.json().get("query", {}).get("pages", {}) or {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            mime = str(info.get("mime") or "")
            url = info.get("url") or ""
            if not mime.startswith("video/") and Path(httpx.URL(url).path).suffix.lower() not in VIDEO_EXTS:
                continue
            meta = info.get("extmetadata") or {}
            license_name = str((meta.get("LicenseShortName") or {}).get("value") or "Wikimedia Commons")
            allowed = any(key in license_name.lower() for key in ("cc0", "public domain", "cc by", "cc-by", "cc by-sa", "cc-by-sa"))
            if not allowed:
                continue
            artist = re.sub(r"<[^>]+>", "", str((meta.get("Artist") or {}).get("value") or "Wikimedia contributor"))
            tags = list(expanded_tokens(query))
            out.append({"id": str(page.get("pageid")), "provider": "wikimedia", "name": str(page.get("title") or query).replace("File:", ""), "tags": tags, "download_url": url, "source_url": info.get("descriptionurl") or "", "license": license_name, "attribution": artist, "orientation": "any", "metadata": {"width": info.get("width"), "height": info.get("height")}})
        return out[:limit]
    except Exception:
        return []
    finally:
        if own:
            client.close()


STARTER_QUERIES = [
    "business office", "money finance market", "technology computer phone", "city traffic", "nature landscape",
    "people walking", "supermarket food", "travel airplane", "news journalism", "education classroom",
    "health hospital", "sports football", "factory industry", "construction", "social media phone",
    "shopping store", "police justice", "government building", "rain storm", "celebration crowd",
]


def install_starter_pack(*, online: bool = True, queries: Iterable[str] | None = None, limit_bytes: int = LITE_PACK_LIMIT_BYTES, force: bool = False) -> dict[str, Any]:
    ensure_asset_dirs()
    generate_offline_core()
    if ASSET_PACK_MARKER.exists() and not force:
        return starter_pack_status()
    pexels_key = os.getenv("PEXELS_API_KEY", "").strip()
    pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()
    downloaded = 0
    if online:
        with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "ViralClip/3.1"}) as client:
            for query in list(queries or STARTER_QUERIES):
                if current_size_bytes() >= limit_bytes:
                    break
                candidates: list[dict[str, Any]] = []
                if pexels_key:
                    candidates += search_pexels(query, api_key=pexels_key, limit=2, client=client)
                if pixabay_key:
                    candidates += search_pixabay(query, api_key=pixabay_key, limit=2, client=client)
                # Commons requires no API key and is the out-of-box fallback.
                if not candidates:
                    candidates += search_wikimedia(query, limit=2, client=client)
                for candidate in candidates[:2]:
                    if current_size_bytes() >= limit_bytes:
                        break
                    if _download(candidate, client=client, limit_bytes=limit_bytes):
                        downloaded += 1
    ASSET_PACK_MARKER.write_text(json.dumps({"preset": "lite", "target_bytes": limit_bytes, "downloaded": downloaded, "created_at": _now()}, ensure_ascii=False), encoding="utf-8")
    status = starter_pack_status()
    status["downloaded_now"] = downloaded
    return status
