from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run_tool(name: str) -> None:
    path = ROOT / 'tools' / name
    proc = subprocess.run([sys.executable, str(path)], cwd=ROOT, text=True)
    if proc.returncode:
        print(f'[AVISO] {name} encontrou itens opcionais ausentes.')


def main() -> int:
    print('=== ViralClip Studio V3 - Diagnostico do sistema ===')
    version = sys.version_info[:2]
    compatible = (3, 10) <= version <= (3, 12)
    print(f'Python: {sys.version.split()[0]}')
    print(f"Python compativel com DirectML: {'SIM' if compatible else 'NAO'}")


    print('\n--- Hardware Manager V3 / Hardware Auto 2.0 ---')
    try:
        from app.services.hardware import load_or_build_profile
        caps = load_or_build_profile()
        profile = caps.get('profile') or {}
        render = caps.get('render') or {}
        transcription = caps.get('transcription') or {}
        analysis = caps.get('analysis') or {}
        print(f"GPU: {caps.get('gpu_name')} ({str(caps.get('gpu_vendor')).upper()})")
        print(f"Render verificado: {render.get('encoder')} ({'SIM' if render.get('verified') else 'FALLBACK'})")
        print(f"Backend IA ativo: {transcription.get('backend')} · Whisper {transcription.get('model')}")
        print(f"Face Tracking: {analysis.get('tracking_fps')} fps em {analysis.get('width')}px · por janela")
        print(f"Perfil: {profile.get('label') or profile.get('name') or '-'}")
    except Exception as exc:
        print(f'[AVISO] Hardware Auto 2.0: {exc}')

    print('\n--- Biblioteca Leve / Asset Brain ---')
    try:
        from app.services.assets import starter_pack_status
        assets = starter_pack_status()
        size_mb = float(assets.get('size_bytes') or 0) / 1024 / 1024
        limit_mb = float(assets.get('limit_bytes') or 1) / 1024 / 1024
        print(f"Biblioteca Leve: {size_mb:.1f} MB / {limit_mb:.0f} MB ({assets.get('percent', 0)}%)")
        print('Assets:', ', '.join(f"{k}={v}" for k,v in (assets.get('counts') or {}).items()) or 'nenhum indexado')
    except Exception as exc:
        print(f'[AVISO] Biblioteca Leve: {exc}')

    print('\n--- Aceleracao / Whisper / FFmpeg ---')
    _run_tool('check_acceleration.py')  # check_acceleration

    print('\n--- YouTube / yt-dlp ---')
    _run_tool('check_youtube.py')  # check_youtube

    print('\n--- Fontes ---')
    try:
        from app.services.fonts import list_fonts
        fonts = list_fonts()
        available = sum(1 for item in fonts if item.get('available'))
        print(f'Fontes: {available}/{len(fonts)} disponiveis')
        missing = [item.get('family', '?') for item in fonts if not item.get('available')]
        if missing:
            print('Opcionais ausentes:', ', '.join(missing))
    except Exception as exc:
        print(f'[AVISO] Nao foi possivel verificar Fontes: {exc}')

    print('\n--- Face Tracking ---')
    try:
        from app.services.face_tracking import YUNET_MODEL, _build_detector
        detector = _build_detector()
        print(f'Face Tracking backend: {detector.backend}')
        print(f"YuNet: {'OK' if YUNET_MODEL.exists() else 'nao instalado; Haar fallback ativo'}")
    except Exception as exc:
        print(f'[AVISO] Face Tracking: {exc}')

    try:
        print('yt-dlp package:', importlib.metadata.version('yt-dlp'))
    except importlib.metadata.PackageNotFoundError:
        print('[AVISO] yt-dlp nao instalado')

    print('\nDiagnostico concluido. AVISOS opcionais nao impedem o app de abrir.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
