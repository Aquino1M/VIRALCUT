from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def test_single_launcher_exists_and_routes_modes():
    text = (ROOT / "VIRALCLIP.bat").read_text(encoding="utf-8")
    assert "tools\\bootstrap.py" in text
    assert "Python.Python.3.12" in text
    assert "%*" in text


def test_bootstrap_exposes_required_modes():
    spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "tools" / "bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {"start", "repair", "diagnose", "update", "safe"}.issubset(module.MODES)


def test_bootstrap_has_asset_pack_hook():
    text = (ROOT / "tools" / "bootstrap.py").read_text(encoding="utf-8")
    assert "install_asset_pack.py" in text
    assert "VIRALCLIP_ASSET_PACK" in text


def test_bootstrap_caches_dependency_install_for_fast_second_start():
    text = (ROOT / "tools" / "bootstrap.py").read_text(encoding="utf-8")
    assert "dependency_fingerprint" in text
    assert ".viralclip_requirements.sha256" in text
