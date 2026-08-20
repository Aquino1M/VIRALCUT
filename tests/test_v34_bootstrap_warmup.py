from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_module():
    spec = importlib.util.spec_from_file_location("bootstrap_v34", ROOT / "tools" / "bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_is_v34_and_warms_only_after_worker_health():
    text = (ROOT / "tools" / "bootstrap.py").read_text(encoding="utf-8")
    assert "V4.2" in text
    assert "warm_selected_asr" in text
    assert text.index("if not wait_for_health") < text.index("warm_selected_asr", text.index("def start"))


def test_low_memory_profile_skips_asr_warmup():
    module = _bootstrap_module()
    assert module.should_warm_asr({"ram_mb": 4096, "profile": {"name": "eco"}}) is False
    assert module.should_warm_asr({"ram_mb": 16384, "profile": {"name": "balanced"}}) is True
