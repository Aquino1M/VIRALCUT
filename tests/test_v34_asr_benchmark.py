from app.services import asr_benchmark


def test_failed_backend_is_not_rebenchmarked_until_environment_changes(monkeypatch, tmp_path):
    profile = {"gpu_vendor": "amd", "gpu_name": "RX 580", "driver": "1.2.3", "version": 3, "transcription": {"model": "small"}}
    calls = []
    monkeypatch.setattr(asr_benchmark, "BENCHMARK_PATH", tmp_path / "asr.json")
    monkeypatch.setattr(asr_benchmark, "candidate_backend_ids", lambda *_a, **_k: ["whispercpp-vulkan", "directml", "faster-whisper-cpu"])
    monkeypatch.setattr(asr_benchmark, "backend_available", lambda *_a, **_k: True)
    monkeypatch.setattr(asr_benchmark, "run_backend_benchmark", lambda bid, *_a, **_k: calls.append(bid) or {"ok": bid != "directml", "x_realtime": 1.0})
    first = asr_benchmark.benchmark_backends(profile)
    second = asr_benchmark.benchmark_backends(profile)
    assert first == second
    assert calls.count("directml") == 1


def test_environment_change_invalidates_persisted_result(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(asr_benchmark, "BENCHMARK_PATH", tmp_path / "asr.json")
    monkeypatch.setattr(asr_benchmark, "candidate_backend_ids", lambda *_a, **_k: ["faster-whisper-cpu"])
    monkeypatch.setattr(asr_benchmark, "backend_available", lambda *_a, **_k: True)
    monkeypatch.setattr(asr_benchmark, "run_backend_benchmark", lambda bid, *_a, **_k: calls.append(bid) or {"ok": True, "x_realtime": 1.0})
    a = {"gpu_vendor": "cpu", "gpu_name": "CPU", "version": 3, "transcription": {"model": "base"}}
    b = {**a, "gpu_name": "Different CPU"}
    asr_benchmark.benchmark_backends(a)
    asr_benchmark.benchmark_backends(b)
    assert calls.count("faster-whisper-cpu") == 2


def test_hardware_profile_v3_can_embed_persisted_asr_benchmark(monkeypatch, tmp_path):
    from app.services import hardware
    monkeypatch.setattr(hardware, 'PROFILE_PATH', tmp_path/'hardware.json')
    monkeypatch.setattr(hardware, 'detect_capabilities', lambda **k: {
        'platform':'win32','os':'Windows','gpu_vendor':'amd','gpu_name':'RX 580','vram_mb':8192,
        'video_encoder':'libx264','cpu_threads':4,'ram_mb':16384,
        'profile':{'name':'balanced','label':'BALANCEADO','tracking_fps':1.8,'whisper_model':'small'},
    })
    monkeypatch.setattr(hardware, '_encoder_benchmark', lambda enc, runner: (True, None))
    profile = hardware.build_hardware_profile(platform_name='win32', command_runner=lambda cmd: '')
    assert profile['version'] == 3
    assert profile['transcription']['backend'] == 'auto'
    assert profile['asr']['selected_backend'] is None
