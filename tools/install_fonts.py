from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import FONT_DIR
from app.services.fonts import write_font_metadata

# Open-license Google Fonts binaries from the official google/fonts repository.
FONT_DOWNLOADS = {
    "Bangers-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/bangers/Bangers-Regular.ttf",
    "Anton-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    "Montserrat-Variable.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
    "BebasNeue-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
    "Oswald-Variable.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/Oswald%5Bwght%5D.ttf",
    "RobotoCondensed-Variable.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/robotocondensed/RobotoCondensed%5Bwght%5D.ttf",
    "ArchivoBlack-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/archivoblack/ArchivoBlack-Regular.ttf",
    "LeagueSpartan-Variable.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/leaguespartan/LeagueSpartan%5Bwght%5D.ttf",
    "PermanentMarker-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/apache/permanentmarker/PermanentMarker-Regular.ttf",
}


def download(url: str, target: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ViralClipAI/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
        if len(data) < 10_000:
            raise RuntimeError("arquivo de fonte inesperadamente pequeno")
        target.write_bytes(data)
        return True
    except Exception as exc:
        print(f"[AVISO] Nao foi possivel baixar {target.name}: {exc}")
        return False


def main() -> int:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for filename, url in FONT_DOWNLOADS.items():
        target = FONT_DIR / filename
        if target.exists() and target.stat().st_size > 10_000:
            print(f"[OK] {filename} ja instalado")
            ok += 1
            continue
        print(f"[DOWNLOAD] {filename}")
        if download(url, target):
            ok += 1
            print(f"[OK] {filename}")
    write_font_metadata()
    print(f"Fontes abertas disponiveis: {ok}/{len(FONT_DOWNLOADS)}")
    print("Fontes opcionais que falharem nao impedem o ViralClip de iniciar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
