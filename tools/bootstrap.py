from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import webbrowser
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe" if os.name == "nt" else VENV / "bin" / "python"
MODES = {"start", "repair", "diagnose", "update", "safe"}


def run(cmd: list[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    print("$", " ".join(map(str, cmd)))
    return subprocess.run(cmd, cwd=ROOT, check=check, env=env)


def dependency_fingerprint() -> str:
    h = hashlib.sha256()
    for name in ("requirements.txt", "requirements-amd.txt"):
        path = ROOT / name
        if path.exists():
            h.update(name.encode("utf-8"))
            h.update(path.read_bytes())
    h.update(f"py{sys.version_info.major}.{sys.version_info.minor}".encode("ascii"))
    return h.hexdigest()


def compatible_python() -> bool:
    return (3, 10) <= sys.version_info[:2] <= (3, 12)


def ensure_venv(force: bool = False) -> None:
    if not compatible_python():
        raise SystemExit("ViralClip requer Python 3.10-3.12.")
    if force and VENV.exists():
        shutil.rmtree(VENV, ignore_errors=True)
    created = False
    if not VENV_PY.exists():
        run([sys.executable, "-m", "venv", str(VENV)])
        created = True
    stamp = VENV / ".viralclip_requirements.sha256"
    fingerprint = dependency_fingerprint()
    installed = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""
    if force or created or installed != fingerprint:
        run([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip"])
        run([str(VENV_PY), "-m", "pip", "install", "--upgrade", "-r", "requirements.txt"])
        stamp.write_text(fingerprint + "\n", encoding="utf-8")
    else:
        print("[OK] Dependências já instaladas; inicialização rápida.")
    if not (ROOT / ".env").exists() and (ROOT / ".env.example").exists():
        shutil.copy2(ROOT / ".env.example", ROOT / ".env")


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    if os.name == "nt" and shutil.which("winget"):
        run(["winget", "install", "-e", "--id", "Gyan.FFmpeg", "--accept-source-agreements", "--accept-package-agreements", "--silent"], check=False)


def setup_acceleration() -> None:
    script = ROOT / "tools" / "setup_acceleration.py"
    if script.exists():
        run([str(VENV_PY), str(script)], check=False)


def install_optional_assets() -> None:
    env = os.environ.copy()
    env.setdefault("VIRALCLIP_ASSET_PACK", "lite")
    script = ROOT / "tools" / "install_asset_pack.py"
    if script.exists():
        run([str(VENV_PY), str(script), "--preset", env["VIRALCLIP_ASSET_PACK"]], check=False, env=env)


def install_models_and_fonts() -> None:
    for script_name in ("install_fonts.py", "install_tracking_models.py"):
        script = ROOT / "tools" / script_name
        if script.exists():
            run([str(VENV_PY), str(script)], check=False)


def diagnose() -> int:
    if not VENV_PY.exists():
        ensure_venv()
    check = ROOT / "tools" / "check_system.py"
    return run([str(VENV_PY), str(check)], check=False).returncode


def update() -> None:
    ensure_venv()
    script = ROOT / "tools" / "check_youtube.py"
    run([str(VENV_PY), "-m", "pip", "install", "--upgrade", "yt-dlp[default,deno]", "yt-dlp-getpot-wpc"], check=False)
    if script.exists():
        run([str(VENV_PY), str(script)], check=False)



def should_warm_asr(profile: dict | None) -> bool:
    try:
        from app.services.worker_control import asr_memory_policy
        return bool(asr_memory_policy(profile).get("warm_model"))
    except Exception:
        return False


def warm_selected_asr() -> None:
    """Best-effort warm-up after the Worker is already healthy."""
    try:
        from app.services.hardware import load_or_build_profile
        from app.services.transcriber import warm_selected_backend
        profile = load_or_build_profile()
        selected = str((profile.get("asr") or {}).get("selected_backend") or "").strip()
        if not selected or not should_warm_asr(profile):
            print("[ASR] Warm-up ignorado pela política de memória/perfil.")
            return
        result = warm_selected_backend(profile)
        state = "OK" if result.get("ok") else "AVISO"
        print(f"[{state}] ASR warm-up: {selected}")
    except Exception as exc:
        print(f"[AVISO] ASR warm-up não concluído: {type(exc).__name__}: {exc}")


def wait_for_health(base_url: str, proc: subprocess.Popen, timeout: float = 45.0) -> bool:
    health_url = base_url.rstrip("/") + "/api/v1/health"
    deadline = time.monotonic() + timeout
    print(f"[Worker] Aguardando health check em {health_url}...")
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print(f"[ERRO] Local Worker encerrou antes de ficar pronto (codigo {proc.returncode}).")
            return False
        try:
            with urllib.request.urlopen(health_url, timeout=1.5) as response:
                if 200 <= int(response.status) < 300:
                    print("[OK] Local Worker pronto.")
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.4)
    print("[ERRO] Local Worker nao respondeu ao health check dentro do tempo esperado.")
    return False

def start(*, safe: bool = False) -> int:
    print("[Worker] ViralClip Studio V4.2 · Local Worker para processamento pesado")
    ensure_venv()
    ensure_ffmpeg()
    setup_acceleration()
    install_models_and_fonts()
    install_optional_assets()
    env = os.environ.copy()
    if safe:
        env["VIDEO_ENCODER"] = "libx264"
        env["WHISPER_BACKEND"] = "faster-whisper"
        env["WHISPER_DEVICE"] = "cpu"
    try:
        from app.config import HOST, PORT
        url = f"http://{HOST}:{PORT}"
    except Exception:
        url = "http://127.0.0.1:8080"
    print("$", str(VENV_PY), "run.py")
    proc = subprocess.Popen([str(VENV_PY), "run.py"], cwd=ROOT, env=env)
    if not wait_for_health(url, proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        return int(proc.returncode or 1)
    if not safe:
        warm_selected_asr()
    print(f"Abrindo {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        return int(proc.wait())
    except KeyboardInterrupt:
        print("\n[Worker] Encerrando Local Worker...")
        proc.terminate()
        try:
            return int(proc.wait(timeout=8))
        except subprocess.TimeoutExpired:
            proc.kill()
            return int(proc.wait())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ViralClip Studio V4.2 Local Worker bootstrap")
    parser.add_argument("mode", nargs="?", default="start", choices=sorted(MODES))
    args = parser.parse_args(argv)
    if args.mode == "repair":
        ensure_venv(force=True)
        ensure_ffmpeg()
        setup_acceleration()
        install_models_and_fonts()
        install_optional_assets()
        return diagnose()
    if args.mode == "diagnose":
        return diagnose()
    if args.mode == "update":
        update()
        return 0
    if args.mode == "safe":
        return start(safe=True)
    return start()


if __name__ == "__main__":
    raise SystemExit(main())
