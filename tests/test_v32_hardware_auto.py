import json

from app.services import hardware


def fake_runner(outputs):
    def run(cmd):
        joined = ' '.join(cmd).lower()
        for needle, value in outputs.items():
            if needle in joined:
                return value
        return ''
    return run


def test_build_hardware_profile_uses_verified_nvidia_encoder(monkeypatch, tmp_path):
    monkeypatch.setattr(hardware, 'PROFILE_PATH', tmp_path / 'hardware_profile.json', raising=False)
    runner = fake_runner({
        'videocontroller': 'Name\nNVIDIA GeForce RTX 3060\n',
        'nvidia-smi': 'NVIDIA GeForce RTX 3060, 12288\n',
        '-encoders': ' h264_nvenc h264_qsv libx264 ',
        'color=c=black': 'benchmark-ok',
    })
    profile = hardware.build_hardware_profile(platform_name='win32', command_runner=runner)
    assert profile['version'] >= 2
    assert profile['gpu_vendor'] == 'nvidia'
    assert profile['render']['encoder'] == 'h264_nvenc'
    assert profile['transcription']['backend'] == 'auto'
    assert profile['asr']['selected_backend'] is None
    assert profile['analysis']['tracking_fps'] >= 1.0
    assert profile['analysis']['width'] >= 480


def test_announced_hardware_encoder_falls_back_when_benchmark_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(hardware, 'PROFILE_PATH', tmp_path / 'hardware_profile.json', raising=False)
    def runner(cmd):
        joined=' '.join(cmd).lower()
        if 'videocontroller' in joined: return 'AMD Radeon RX 580\n'
        if '-encoders' in joined: return ' h264_amf libx264 '
        if 'h264_amf' in joined and 'color=c=black' in joined: return 'error initializing encoder'
        return ''
    profile = hardware.build_hardware_profile(platform_name='win32', command_runner=runner)
    assert profile['gpu_vendor'] == 'amd'
    assert profile['render']['encoder'] == 'libx264'
    assert profile['render']['fallback_reason']
    assert profile['transcription']['backend'] == 'auto'
    assert profile['asr']['selected_backend'] is None


def test_load_or_build_profile_persists_and_routes(monkeypatch, tmp_path):
    path = tmp_path/'hardware_profile.json'
    monkeypatch.setattr(hardware, 'PROFILE_PATH', path, raising=False)
    monkeypatch.setattr(hardware, 'build_hardware_profile', lambda **kwargs: {
        'version':2,'gpu_vendor':'intel','profile':{'name':'balanced','label':'BALANCEADO'},
        'render':{'encoder':'h264_qsv'},'transcription':{'backend':'openvino','model':'small'},
        'analysis':{'tracking_fps':1.5,'width':640},'cpu_threads':8,'ram_mb':16000
    })
    profile = hardware.load_or_build_profile(force=True)
    assert path.exists()
    assert hardware.render_route(profile)['encoder'] == 'h264_qsv'
    assert hardware.transcription_route(profile)['backend'] == 'openvino'
    assert json.loads(path.read_text())['gpu_vendor'] == 'intel'
