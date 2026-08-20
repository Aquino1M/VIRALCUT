from pathlib import Path

from app.services import transcriber
from tools import setup_acceleration


def test_nvidia_auto_runtime_prefers_cuda():
    device, compute = transcriber.select_faster_runtime(
        configured_device='auto', configured_compute='auto', capabilities={'gpu_vendor': 'nvidia'}
    )
    assert device == 'cuda'
    assert compute == 'float16'


def test_amd_auto_runtime_leaves_faster_whisper_on_cpu_because_directml_is_separate():
    device, compute = transcriber.select_faster_runtime(
        configured_device='auto', configured_compute='auto', capabilities={'gpu_vendor': 'amd'}
    )
    assert device == 'cpu'
    assert compute == 'int8'


def test_backend_can_prefer_cuda_over_directml_on_nvidia():
    assert transcriber.resolve_backend(
        'auto', platform_name='win32', directml_available=True, gpu_vendor='nvidia'
    ) == 'faster-whisper'


def test_acceleration_env_values_cover_nvidia_amd_intel_and_cpu():
    assert setup_acceleration.recommended_env({'gpu_vendor': 'nvidia', 'video_encoder': 'h264_nvenc'})['WHISPER_DEVICE'] == 'auto'
    assert setup_acceleration.recommended_env({'gpu_vendor': 'amd', 'video_encoder': 'h264_amf'})['WHISPER_BACKEND'] == 'auto'
    assert setup_acceleration.recommended_env({'gpu_vendor': 'intel', 'video_encoder': 'h264_qsv'})['VIDEO_ENCODER'] == 'auto'
    assert setup_acceleration.recommended_env({'gpu_vendor': 'cpu', 'video_encoder': 'libx264'})['WHISPER_DEVICE'] == 'cpu'


def test_single_bootstrap_runs_hardware_acceleration_setup():
    text = Path('tools/bootstrap.py').read_text(encoding='utf-8')
    assert 'setup_acceleration.py' in text
