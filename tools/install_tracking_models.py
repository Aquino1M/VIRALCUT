from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "data" / "models" / "tracking"
MODEL = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
URLS = [
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
]


def main() -> int:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if MODEL.exists() and MODEL.stat().st_size > 100_000:
        print(f"YuNet ja instalado: {MODEL}")
        return 0
    for url in URLS:
        try:
            print(f"Baixando YuNet do OpenCV Zoo: {url}")
            tmp = MODEL.with_suffix(".tmp")
            urllib.request.urlretrieve(url, tmp)
            if tmp.stat().st_size < 100_000:
                raise RuntimeError("arquivo recebido parece invalido")
            tmp.replace(MODEL)
            print(f"YuNet instalado: {MODEL}")
            return 0
        except Exception as exc:
            print(f"Tentativa falhou: {exc}")
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
    print("Aviso: YuNet nao foi baixado. O ViralClip usara o fallback Haar do OpenCV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
