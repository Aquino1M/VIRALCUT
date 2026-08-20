from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BackendDescriptor:
    id: str
    quality_class: str
    device_label: str


BACKENDS = {
    "faster-whisper-cuda": BackendDescriptor("faster-whisper-cuda", "whisper", "CUDA GPU"),
    "whispercpp-vulkan": BackendDescriptor("whispercpp-vulkan", "whisper", "Vulkan GPU"),
    "directml": BackendDescriptor("directml", "whisper", "DirectML GPU"),
    "faster-whisper-cpu": BackendDescriptor("faster-whisper-cpu", "whisper", "CPU INT8"),
}


class BackendAdapter(Protocol):
    descriptor: BackendDescriptor
    def is_available(self) -> bool: ...
    def transcribe_segments(self, *args, **kwargs) -> dict: ...
    def transcribe_words(self, *args, **kwargs) -> dict: ...


def candidate_backend_ids(profile: dict, platform_name: str | None = None) -> list[str]:
    vendor = str(profile.get("gpu_vendor") or "cpu").lower()
    platform_name = platform_name or str(profile.get("platform") or sys.platform)
    if vendor == "nvidia":
        return ["faster-whisper-cuda", "whispercpp-vulkan", "faster-whisper-cpu"]
    if vendor in {"amd", "intel"} and platform_name.startswith("win"):
        return ["whispercpp-vulkan", "directml", "faster-whisper-cpu"]
    if vendor in {"amd", "intel"}:
        return ["whispercpp-vulkan", "faster-whisper-cpu"]
    return ["faster-whisper-cpu"]


def choose_persisted_backend(profile: dict) -> str | None:
    selected = str((profile.get("asr") or {}).get("selected_backend") or "").strip()
    return selected if selected in BACKENDS else None


class _Adapter:
    def __init__(self, backend_id: str):
        self.descriptor = BACKENDS[backend_id]
        self.backend_id = backend_id

    def is_available(self) -> bool:
        if self.backend_id == "whispercpp-vulkan":
            from . import whispercpp
            exe = whispercpp.find_executable()
            return bool(exe and whispercpp.validate_runtime(exe).get("ok"))
        if self.backend_id == "directml":
            from . import transcriber
            return transcriber._directml_is_available()
        if importlib.util.find_spec("faster_whisper") is None:
            return False
        if self.backend_id == "faster-whisper-cuda":
            try:
                import ctranslate2
                return bool(ctranslate2.get_supported_compute_types("cuda"))
            except Exception:
                return False
        return True

    def transcribe_segments(self, *args, **kwargs) -> dict:
        if self.backend_id == "whispercpp-vulkan":
            from . import whispercpp
            profile = kwargs.get("hardware_profile") or {}
            model = str(((profile.get("transcription") or {}).get("model")) or "small")
            return whispercpp.transcribe_segments(*args, model=model, **{k: v for k, v in kwargs.items() if k != "hardware_profile"})
        from . import transcriber
        return transcriber._transcribe_segments_backend(*args, backend_id=self.backend_id, **kwargs)

    def transcribe_words(self, *args, **kwargs) -> dict:
        if self.backend_id == "whispercpp-vulkan":
            from . import whispercpp
            profile = kwargs.get("hardware_profile") or {}
            model = str(((profile.get("transcription") or {}).get("model")) or "small")
            return whispercpp.transcribe_words(*args, model=model, **{k: v for k, v in kwargs.items() if k != "hardware_profile"})
        from . import transcriber
        return transcriber._transcribe_words_backend(*args, backend_id=self.backend_id, **kwargs)


def get_backend(backend_id: str) -> BackendAdapter:
    if backend_id not in BACKENDS:
        raise KeyError(f"ASR backend desconhecido: {backend_id}")
    return _Adapter(backend_id)


def backend_available(backend_id: str) -> bool:
    try:
        return bool(get_backend(backend_id).is_available())
    except Exception:
        return False
