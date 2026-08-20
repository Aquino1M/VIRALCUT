from pathlib import Path

import pytest

from app.services import disk_manager


def test_disk_preflight_requires_temp_budget_plus_reserve():
    source_size = 2 * 1024**3
    needed = disk_manager.estimate_temp_bytes(source_size)
    assert needed >= source_size
    ok = disk_manager.evaluate_space(source_size=source_size, free_bytes=needed + 1024**3)
    assert ok['ok'] is True
    low = disk_manager.evaluate_space(source_size=source_size, free_bytes=max(0, needed - 1))
    assert low['ok'] is False
    assert low['required_bytes'] > low['free_bytes']


def test_ensure_job_space_raises_actionable_error_when_storage_is_low(monkeypatch, tmp_path: Path):
    source = tmp_path/'source.mp4'
    source.write_bytes(b'x' * 1024)
    monkeypatch.setattr(disk_manager.shutil, 'disk_usage', lambda _: (10_000, 9_999, 1))
    with pytest.raises(disk_manager.InsufficientDiskSpace, match='espaço'):
        disk_manager.ensure_job_space(source, temp_root=tmp_path)


def test_cleanup_orphan_temp_never_touches_files_outside_temp_root(tmp_path: Path, monkeypatch):
    temp = tmp_path/'temp'; temp.mkdir()
    user = tmp_path/'uploads'; user.mkdir()
    orphan = temp/'old.bin'; orphan.write_bytes(b'x')
    personal = user/'keep.mp4'; personal.write_bytes(b'y')
    monkeypatch.setattr(disk_manager.time, 'time', lambda: 10_000.0)
    monkeypatch.setattr(disk_manager.os.path, 'getmtime', lambda p: 0.0 if Path(p)==orphan else 10_000.0)
    result = disk_manager.cleanup_orphan_temp(temp_root=temp, older_than_seconds=100)
    assert result['removed_files'] == 1
    assert not orphan.exists()
    assert personal.exists()
