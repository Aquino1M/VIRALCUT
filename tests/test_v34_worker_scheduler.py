from app.services.worker_control import asr_memory_policy


def test_asr_memory_policy_limits_low_memory_workers():
    low = asr_memory_policy({"ram_mb": 4096, "profile": {"name": "eco"}})
    assert low == {"warm_model": False, "max_workers": 1}


def test_asr_memory_policy_allows_resident_model_on_balanced_pc():
    normal = asr_memory_policy({"ram_mb": 16384, "profile": {"name": "balanced"}})
    assert normal["warm_model"] is True
    assert normal["max_workers"] >= 1
