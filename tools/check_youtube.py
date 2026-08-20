from __future__ import annotations

import importlib.metadata
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.ingest import _detect_chromium_browser, _js_runtimes


def version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NAO INSTALADO"


print("yt-dlp:", version("yt-dlp"))
print("yt-dlp-ejs:", version("yt-dlp-ejs"))
print("yt-dlp-getpot-wpc:", version("yt-dlp-getpot-wpc"))
print("Deno no PATH:", shutil.which("deno") or "nao")
print("Node no PATH:", shutil.which("node") or "nao")
print("Runtime JS resolvido:", _js_runtimes() or "NENHUM")
print("Chromium/Brave/Chrome/Edge detectado:", _detect_chromium_browser() or "nao")

missing = []
if version("yt-dlp-ejs") == "NAO INSTALADO":
    missing.append("yt-dlp-ejs")
if not _js_runtimes():
    missing.append("Deno/Node")
if version("yt-dlp-getpot-wpc") == "NAO INSTALADO":
    missing.append("yt-dlp-getpot-wpc")

if missing:
    print("FALTANDO:", ", ".join(missing))
    raise SystemExit(1)
print("Suporte moderno do YouTube: OK")
