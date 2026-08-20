from app.services.asr_backends import candidate_backend_ids


def test_amd_candidates_prefer_vulkan_then_directml_then_cpu():
    profile = {"gpu_vendor": "amd"}
    assert candidate_backend_ids(profile, platform_name="win32") == [
        "whispercpp-vulkan", "directml", "faster-whisper-cpu"
    ]


def test_nvidia_candidates_prefer_cuda_then_vulkan_then_cpu():
    profile = {"gpu_vendor": "nvidia"}
    assert candidate_backend_ids(profile, platform_name="win32") == [
        "faster-whisper-cuda", "whispercpp-vulkan", "faster-whisper-cpu"
    ]


def test_intel_candidates_prefer_vulkan_then_directml_then_cpu():
    profile = {"gpu_vendor": "intel"}
    assert candidate_backend_ids(profile, platform_name="win32") == [
        "whispercpp-vulkan", "directml", "faster-whisper-cpu"
    ]


def test_cpu_candidate_is_universal_fallback():
    assert candidate_backend_ids({"gpu_vendor": "cpu"}, platform_name="win32") == [
        "faster-whisper-cpu"
    ]
