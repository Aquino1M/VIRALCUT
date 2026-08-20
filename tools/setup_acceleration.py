from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DIRECTML_COMMIT = "8700779fe7a09ea7a007cf3d7ab4293c78e41017"
DIRECTML_URL = f"https://github.com/microsoft/DirectML/archive/{DIRECTML_COMMIT}.zip"
WHISPERCPP_VERSION = "v1.9.1"
WHISPERCPP_SOURCE_URL = f"https://github.com/ggml-org/whisper.cpp/archive/refs/tags/{WHISPERCPP_VERSION}.zip"
WHISPERCPP_MODEL_URL_TEMPLATE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin"


def recommended_env(capabilities: dict) -> dict[str, str]:
    vendor = str(capabilities.get("gpu_vendor") or "cpu").lower()
    values = {
        "VIDEO_ENCODER": "auto",
        "WHISPER_BACKEND": "auto",
        "WHISPER_COMPUTE_TYPE": "auto",
    }
    if vendor == "nvidia":
        values["WHISPER_DEVICE"] = "auto"
    elif vendor in {"amd", "intel"}:
        # DirectML is selected by WHISPER_BACKEND=auto when the optional runtime is installed.
        # faster-whisper itself stays CPU-only on these vendors as a safe fallback.
        values["WHISPER_DEVICE"] = "auto"
    else:
        values["WHISPER_DEVICE"] = "cpu"
        values["WHISPER_COMPUTE_TYPE"] = "int8"
    return values


def _update_env(path: Path, values: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    lines = existing.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in values:
                out.append(f"{key}={values[key]}")
                seen.add(key)
                continue
        out.append(line)
    if out and out[-1].strip():
        out.append("")
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _python_can_import(python_exe: str, module: str) -> bool:
    proc = subprocess.run([python_exe, "-c", f"import {module}"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


def _install_directml(python_exe: str) -> bool:
    print("[GPU] Preparando DirectML para AMD/Intel (best effort)...")
    proc = subprocess.run(
        [python_exe, "-m", "pip", "install", "--upgrade", "torch-directml", "numba", "numpy", "tqdm", "more-itertools", "tiktoken", "ffmpeg-python"],
        cwd=ROOT,
    )
    if proc.returncode != 0:
        print("[GPU] DirectML não pôde ser instalado; o fallback CPU continuará disponível.")
        return False
    if _python_can_import(python_exe, "torch_directml") and (ROOT / "vendor/directml_whisper/whisper/__init__.py").exists():
        return True
    try:
        import httpx
        with tempfile.TemporaryDirectory(prefix="viralclip_dml_") as td:
            td_path = Path(td)
            zip_path = td_path / "directml.zip"
            with httpx.stream("GET", DIRECTML_URL, follow_redirects=True, timeout=90) as response:
                response.raise_for_status()
                with zip_path.open("wb") as fh:
                    for chunk in response.iter_bytes(1024 * 1024):
                        if chunk:
                            fh.write(chunk)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(td_path / "src")
            src = td_path / "src" / f"DirectML-{DIRECTML_COMMIT}" / "PyTorch" / "audio" / "whisper"
            whisper_src = src / "whisper"
            if not whisper_src.exists():
                raise RuntimeError("amostra Whisper DirectML não encontrada no pacote")
            dst = ROOT / "vendor" / "directml_whisper"
            shutil.rmtree(dst / "whisper", ignore_errors=True)
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copytree(whisper_src, dst / "whisper")
            license_src = src / "LICENSE"
            if license_src.exists():
                shutil.copy2(license_src, dst / "MICROSOFT_WHISPER_LICENSE.txt")
    except Exception as exc:
        print(f"[GPU] Não foi possível baixar o sample DirectML: {exc}")
        return False
    return _python_can_import(python_exe, "torch_directml") and (ROOT / "vendor/directml_whisper/whisper/__init__.py").exists()



def _download_file(url: str, destination: Path, *, timeout: int = 180) -> None:
    import httpx
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as response:
        response.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in response.iter_bytes(1024 * 1024):
                if chunk:
                    fh.write(chunk)
    tmp.replace(destination)


def install_whispercpp_runtime(*, install_model: bool = True, model: str = "small") -> bool:
    """Best-effort Vulkan build from the pinned official whisper.cpp source.

    The release ZIP never embeds this runtime. On Windows we only build it when
    CMake and a Vulkan SDK are already available; otherwise DirectML/CPU remain
    safe fallbacks and setup continues normally.
    """
    runtime_dir = ROOT / "data" / "runtime" / "whispercpp"
    existing = runtime_dir / "whisper-cli.exe"
    if existing.exists():
        return True
    cmake = shutil.which("cmake")
    if not cmake or (os.name == "nt" and not os.getenv("VULKAN_SDK")):
        print("[GPU] whisper.cpp Vulkan opcional ignorado: CMake/Vulkan SDK não encontrado.")
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="viralclip_whispercpp_") as td:
            td_path = Path(td)
            archive = td_path / "whispercpp.zip"
            _download_file(WHISPERCPP_SOURCE_URL, archive)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(td_path / "src")
            src_root = next((p for p in (td_path / "src").iterdir() if p.is_dir()), None)
            if src_root is None:
                raise RuntimeError("fonte whisper.cpp não encontrada no arquivo")
            build = td_path / "build"
            configure_cmd = [
                cmake, "-S", str(src_root), "-B", str(build),
                "-DGGML_VULKAN=ON", "-DGGML_CUDA=OFF", "-DGGML_HIP=OFF",
                "-DWHISPER_BUILD_TESTS=OFF", "-DWHISPER_BUILD_EXAMPLES=ON",
            ]
            if subprocess.run(configure_cmd, cwd=ROOT).returncode != 0:
                return False
            if subprocess.run([cmake, "--build", str(build), "--config", "Release", "--target", "whisper-cli"], cwd=ROOT).returncode != 0:
                return False
            exe = next(build.rglob("whisper-cli.exe"), None) if os.name == "nt" else next(build.rglob("whisper-cli"), None)
            if exe is None:
                raise RuntimeError("whisper-cli não foi gerado")
            runtime_dir.mkdir(parents=True, exist_ok=True)
            # Copy the executable and sibling runtime libraries required by the build.
            for item in exe.parent.iterdir():
                if item.is_file() and (item.name == exe.name or item.suffix.lower() in {".dll", ".so", ".dylib"}):
                    shutil.copy2(item, runtime_dir / item.name)
        model_path = runtime_dir / "models" / f"ggml-{model}.bin"
        if install_model and not model_path.exists():
            try:
                _download_file(WHISPERCPP_MODEL_URL_TEMPLATE.format(model=model), model_path, timeout=600)
            except Exception as exc:
                print(f"[GPU] Runtime Vulkan pronto, mas modelo whisper.cpp não baixado: {exc}")
        manifest = {
            "version": WHISPERCPP_VERSION,
            "executable": "whisper-cli.exe" if os.name == "nt" else "whisper-cli",
            "origin_url": WHISPERCPP_SOURCE_URL,
            "model": str(model_path.relative_to(runtime_dir)) if model_path.exists() else None,
            "built_with": "GGML_VULKAN=ON",
        }
        (runtime_dir / "runtime.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return (runtime_dir / manifest["executable"]).exists()
    except Exception as exc:
        print(f"[GPU] whisper.cpp Vulkan não pôde ser preparado: {exc}")
        return False

def configure(*, python_exe: str | None = None, install_optional: bool = True) -> dict:
    from app.services.hardware import build_hardware_profile, detect_capabilities, PROFILE_PATH

    python_exe = python_exe or sys.executable
    caps = detect_capabilities()
    vendor = str(caps.get("gpu_vendor") or "cpu")
    dml_ready = False
    vulkan_ready = False
    if os.name == "nt" and vendor in {"amd", "intel"} and install_optional:
        vulkan_ready = install_whispercpp_runtime(model=str((caps.get("profile") or {}).get("whisper_model") or "small"))
    if os.name == "nt" and vendor in {"amd", "intel"}:
        dml_ready = _python_can_import(python_exe, "torch_directml") and (ROOT / "vendor/directml_whisper/whisper/__init__.py").exists()
        if install_optional and not dml_ready:
            dml_ready = _install_directml(python_exe)
    env_values = recommended_env(caps)
    env_path = ROOT / ".env"
    if not env_path.exists() and (ROOT / ".env.example").exists():
        shutil.copy2(ROOT / ".env.example", env_path)
    _update_env(env_path, env_values)
    # Re-run the executable Hardware Auto 2.0 benchmark after optional GPU
    # runtimes have been installed. This keeps the persisted profile schema
    # identical to the one consumed by the Worker.
    profile = build_hardware_profile()
    profile["directml_ready"] = bool(dml_ready)
    profile["whispercpp_vulkan_ready"] = bool(vulkan_ready)
    try:
        from app.services import asr_benchmark
        profile["asr"] = asr_benchmark.benchmark_backends(profile, force=True)
    except Exception as exc:
        profile["asr"] = {**dict(profile.get("asr") or {}), "fallback_reason": f"Benchmark ASR não concluído: {type(exc).__name__}: {exc}"[:500]}
    profile["env"] = env_values
    # Persist to data/hardware_profile.json through the shared PROFILE_PATH.
    Path(PROFILE_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(PROFILE_PATH).write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    render = profile.get("render") or {}
    transcribe = profile.get("transcription") or {}
    asr = profile.get("asr") or {}
    print(
        f"[GPU] {profile.get('gpu_name')} · IA {asr.get('selected_backend') or transcribe.get('backend')} · "
        f"encoder {render.get('encoder')} · perfil {(profile.get('profile') or {}).get('label')}"
    )
    return profile


def main() -> int:
    configure(python_exe=sys.executable, install_optional=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
