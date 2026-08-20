from pathlib import Path

from app.services.api_v1 import capabilities_payload

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_advances_to_320():
    assert (ROOT / 'VERSION').read_text(encoding='utf-8').strip() == '4.2.0'


def test_capabilities_advertise_v31_studio_features():
    features = capabilities_payload()['features']
    for key in (
        'studio_shell', 'source_first_create', 'mobile_navigation',
        'asset_manager', 'templates_catalog', 'brand_kit',
    ):
        assert features.get(key) is True


def test_legacy_bats_point_normal_users_to_single_launcher():
    install = (ROOT / 'install.bat').read_text(encoding='utf-8')
    run = (ROOT / 'run.bat').read_text(encoding='utf-8')
    diag = (ROOT / 'diagnostico.bat').read_text(encoding='utf-8')
    amd = (ROOT / 'setup_amd_gpu.bat').read_text(encoding='utf-8')
    for text in (install, run, diag, amd):
        assert 'VIRALCLIP.bat' in text
    assert 'Para RX 580, execute setup_amd_gpu.bat' not in install
    assert 'Depois execute run.bat' not in install


def test_readme_calls_viralclip_bat_the_normal_entrypoint_and_documents_v31_shell():
    text = (ROOT / 'README.md').read_text(encoding='utf-8')
    for marker in (
        'V3.1', 'VIRALCLIP.bat', 'Navegação mobile', 'Hardware Local',
        'Biblioteca Inteligente', 'Templates', 'Brand Kit', 'Cole o link do vídeo',
    ):
        assert marker in text
