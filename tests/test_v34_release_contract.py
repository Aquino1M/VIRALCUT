from pathlib import Path


def test_hardware_ui_mentions_vulkan_benchmark_and_incompatible_directml():
    html = Path("app/templates/hardware.html").read_text(encoding="utf-8")
    assert "Vulkan" in html
    assert "benchmark" in html.lower()
    assert "DirectML" in html


def test_release_version_is_3_4():
    assert Path("VERSION").read_text().strip().startswith("4.2")


def test_release_notes_exist():
    assert Path("docs/V3.4_RELEASE_NOTES.md").exists()


def test_capabilities_exposes_compact_asr_benchmark(monkeypatch):
    from app.services import api_v1

    profile = {
        "version": 3,
        "gpu_vendor": "amd",
        "gpu_name": "RX 580",
        "asr": {
            "selected_backend": "whispercpp-vulkan",
            "benchmarked_at": "2026-08-18T10:00:00Z",
            "fallback_reason": None,
            "results": {
                "whispercpp-vulkan": {"ok": True, "x_realtime": 2.4, "init_ms": 200, "error": None},
                "directml": {"ok": False, "x_realtime": 0.0, "error": "TypeError: incompatible"},
            },
        },
    }
    monkeypatch.setattr(api_v1.hardware, "load_or_build_profile", lambda: profile)
    monkeypatch.setattr(api_v1.assets, "starter_pack_status", lambda: {})
    payload = api_v1.capabilities_payload()
    assert payload["asr"]["selected_backend"] == "whispercpp-vulkan"
    assert payload["asr"]["x_realtime"] == 2.4
    assert payload["asr"]["last_benchmark"] == "2026-08-18T10:00:00Z"
    assert payload["asr"]["candidates"]["directml"]["ok"] is False
    assert "Traceback" not in str(payload["asr"])


def test_v34_runtime_asr_artifacts_are_ignored():
    text = Path('.gitignore').read_text(encoding='utf-8')
    for marker in ('data/cache/', 'data/runtime/', 'data/asr_benchmark.json'):
        assert marker in text
