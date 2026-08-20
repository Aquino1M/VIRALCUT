from pathlib import Path

from app.services import api_v1, compute

ROOT=Path(__file__).resolve().parents[1]


def test_v42_version_and_docs_exist():
    assert (ROOT/'VERSION').read_text(encoding='utf-8').strip()=='4.2.0'
    assert (ROOT/'docs/V4.2_RELEASE_NOTES.md').exists()
    assert (ROOT/'LIGHTNING_FREE_CPU_SETUP.md').exists()
    assert (ROOT/'lightning_worker/main.py').exists()


def test_v42_capabilities_expose_compute_intelligence_features():
    features=api_v1.capabilities_payload()['features']
    for name in ('compute_fabric','lightning_free_cpu_only','viral_score_v3','semantic_search','prompt_to_edit','revision_history','creator_intelligence','quality_guard_v2','auto_edit_v2'):
        assert features.get(name) is True


def test_v42_scheduler_never_allows_cloud_gpu():
    node=compute.ComputeNode('paid','cloud_gpu','GPU remota',True,free_only=False)
    assert compute._allowed(node,'asr_segments','auto') is False


def test_v42_worker_is_hard_locked_to_free_cpu():
    text=(ROOT/'lightning_worker/main.py').read_text(encoding='utf-8')
    assert 'FREE_CPU_ONLY = True' in text
    assert "HEAVY_SLOTS = 1" in text
    assert 'faster-whisper-cpu' in text
    assert 'NVIDIA T4' not in text
    assert 'lightning_sdk' not in text


def test_v42_pytest_runs_without_external_pythonpath():
    text=(ROOT/'pytest.ini').read_text(encoding='utf-8')
    assert 'pythonpath = .' in text
