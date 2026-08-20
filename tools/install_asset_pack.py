from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.assets import LITE_PACK_LIMIT_BYTES, install_starter_pack, starter_pack_status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Instala a biblioteca local do ViralClip")
    parser.add_argument("--preset", default="lite", choices=["lite"])
    parser.add_argument("--offline", action="store_true", help="gera somente SFX/efeitos locais, sem baixar B-roll")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--target-gb", type=float, default=2.0)
    args = parser.parse_args(argv)
    limit = min(LITE_PACK_LIMIT_BYTES, max(64 * 1024 * 1024, int(args.target_gb * 1024**3)))
    before = starter_pack_status()
    print(f"Biblioteca ViralClip {args.preset}: {before['size_bytes']/1024**2:.1f} MB / {limit/1024**3:.1f} GB")
    result = install_starter_pack(online=not args.offline, limit_bytes=limit, force=args.refresh)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.offline and result.get("counts", {}).get("broll", 0) == 0:
        print("[AVISO] Nenhum B-roll de stock foi baixado. O ViralClip continua funcionando com assets locais; configure PEXELS_API_KEY/PIXABAY_API_KEY para ampliar a biblioteca.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
