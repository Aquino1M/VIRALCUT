from app.services import transcriber


def test_hardware_profile_controls_faster_whisper_model_threads_and_cuda_route():
    profile = {
        'gpu_vendor': 'nvidia',
        'transcription': {'backend': 'cuda', 'model': 'medium', 'cpu_threads': 7},
    }
    cfg = transcriber.faster_model_config(profile)
    assert cfg['model'] == 'medium'
    assert cfg['cpu_threads'] == 7
    assert cfg['device'] == 'cuda'
    assert cfg['compute_type'] == 'float16'


def test_hardware_profile_controls_cpu_fallback_runtime():
    profile = {
        'gpu_vendor': 'cpu',
        'transcription': {'backend': 'cpu', 'model': 'base', 'cpu_threads': 2},
    }
    cfg = transcriber.faster_model_config(profile)
    assert cfg == {
        'model': 'base', 'device': 'cpu', 'compute_type': 'int8',
        'cpu_threads': 2, 'num_workers': 1,
    }


def test_transcribe_passes_hardware_profile_to_selected_backend(monkeypatch):
    profile = {'gpu_vendor':'nvidia','transcription':{'backend':'cuda','model':'small','cpu_threads':4}}
    seen = {}
    monkeypatch.setattr(transcriber, 'resolve_backend', lambda preferred=None: 'faster-whisper')
    def fake(video, language, progress, hardware_profile=None):
        seen['profile'] = hardware_profile
        return {'segments': [], 'backend':'faster-whisper'}
    monkeypatch.setattr(transcriber, '_transcribe_faster_whisper', fake)
    result = transcriber.transcribe('video.mp4', hardware_profile=profile)
    assert result['backend'] == 'faster-whisper'
    assert seen['profile'] is profile


def test_directml_model_uses_hardware_profile_model():
    profile={'gpu_vendor':'amd','transcription':{'backend':'directml','model':'base','cpu_threads':3}}
    assert transcriber.transcription_model_name(profile) == 'base'
