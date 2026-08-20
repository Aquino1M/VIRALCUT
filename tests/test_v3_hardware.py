from app.services import hardware
from app.services import render


def fake_runner(outputs):
    def run(cmd):
        joined = " ".join(cmd).lower()
        for needle, value in outputs.items():
            if needle in joined:
                return value
        return ""
    return run


def test_detect_nvidia_prefers_cuda_nvenc():
    caps = hardware.detect_capabilities(
        platform_name="win32",
        command_runner=fake_runner({
            "videocontroller": "Name\nNVIDIA GeForce RTX 3060\n",
            "-encoders": " V..... h264_nvenc NVIDIA NVENC H.264 encoder\n V..... hevc_nvenc NVIDIA NVENC hevc encoder\n",
            "nvidia-smi": "NVIDIA GeForce RTX 3060, 12288\n",
        }),
    )
    assert caps["gpu_vendor"] == "nvidia"
    assert caps["video_encoder"] == "h264_nvenc"
    assert caps["ai_backend"] == "cuda"
    assert caps["vram_mb"] == 12288


def test_detect_amd_prefers_amf_and_directml():
    caps = hardware.detect_capabilities(
        platform_name="win32",
        command_runner=fake_runner({
            "videocontroller": "Name\nAMD Radeon RX 580 2048SP\n",
            "-encoders": " V..... h264_amf AMD AMF H.264 Encoder\n",
        }),
    )
    assert caps["gpu_vendor"] == "amd"
    assert caps["video_encoder"] == "h264_amf"
    assert caps["ai_backend"] == "directml"


def test_detect_intel_prefers_qsv():
    caps = hardware.detect_capabilities(
        platform_name="win32",
        command_runner=fake_runner({
            "videocontroller": "Name\nIntel(R) Arc(TM) A750 Graphics\n",
            "-encoders": " V..... h264_qsv H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (Intel Quick Sync Video acceleration)\n",
        }),
    )
    assert caps["gpu_vendor"] == "intel"
    assert caps["video_encoder"] == "h264_qsv"
    assert caps["ai_backend"] in {"directml", "openvino"}


def test_cpu_fallback_is_always_available():
    caps = hardware.detect_capabilities(
        platform_name="linux",
        command_runner=fake_runner({"-encoders": " V..... libx264 libx264 H.264"}),
    )
    assert caps["gpu_vendor"] == "cpu"
    assert caps["video_encoder"] == "libx264"
    assert caps["ai_backend"] == "cpu"


def test_encoder_args_cover_all_v3_backends():
    assert "h264_nvenc" in render.video_encoder_args("h264_nvenc")
    assert "h264_amf" in render.video_encoder_args("h264_amf")
    assert "h264_qsv" in render.video_encoder_args("h264_qsv")
    assert "libx264" in render.video_encoder_args("libx264")


def test_recommended_profile_scales_with_hardware():
    turbo = hardware.recommended_profile({"gpu_vendor": "nvidia", "vram_mb": 12288, "ram_mb": 32768, "cpu_threads": 16})
    eco = hardware.recommended_profile({"gpu_vendor": "cpu", "vram_mb": 0, "ram_mb": 8192, "cpu_threads": 4})
    assert turbo["name"] == "turbo"
    assert turbo["max_parallel_renders"] >= 2
    assert eco["name"] == "eco"
    assert eco["max_parallel_renders"] == 1
