from pathlib import Path
from app.services import whispercpp


def test_runtime_is_absent_when_executable_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(whispercpp, "RUNTIME_DIR", tmp_path)
    assert whispercpp.find_executable() is None


def test_vulkan_command_requests_json_and_language(monkeypatch, tmp_path):
    exe = tmp_path / "whisper-cli.exe"
    exe.write_text("stub")
    cmd = whispercpp.build_command(exe, Path("audio.wav"), Path("model.gguf"), word_timestamps=True, language="pt")
    joined = " ".join(map(str, cmd)).lower()
    assert "whisper-cli" in joined
    assert "pt" in joined
    assert "json" in joined
    assert "--gpu" in joined or "-ng" not in joined
