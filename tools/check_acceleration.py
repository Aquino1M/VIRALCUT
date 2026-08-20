from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import FFMPEG_BIN, VIDEO_ENCODER, WHISPER_BACKEND
from app.services.render import select_video_encoder
from app.services.transcriber import resolve_backend


def main() -> int:
    print("=== ViralClip - Diagnóstico de aceleração ===")
    print(f"Python: {sys.version.split()[0]}")
    print(f"WHISPER_BACKEND configurado: {WHISPER_BACKEND}")
    print(f"Backend resolvido: {resolve_backend()}")

    try:
        import torch_directml

        device = torch_directml.device(torch_directml.default_device())
        print(f"DirectML: OK ({device})")
    except Exception as exc:
        print(f"DirectML: não disponível ({exc})")

    try:
        proc = subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
        )
        has_amf = "h264_amf" in (proc.stdout or "")
        print(f"FFmpeg h264_amf: {'OK' if has_amf else 'NÃO ENCONTRADO'}")
    except Exception as exc:
        print(f"FFmpeg: erro ({exc})")

    print(f"VIDEO_ENCODER configurado: {VIDEO_ENCODER}")
    print(f"Encoder resolvido: {select_video_encoder()}")
    print("===========================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
