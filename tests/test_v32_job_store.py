from datetime import datetime, timedelta, timezone

from app import db


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'v32_jobs.db')
    db.init_db()
    from app.services import job_store
    return job_store


def test_job_store_persists_stage_progress_and_eta(monkeypatch, tmp_path):
    job_store = _setup(monkeypatch, tmp_path)
    job_id = job_store.create_job('project', 'p1')
    job_store.start_stage(job_id, 'transcribe', total=120.0, backend='cuda')
    job_store.update_stage(job_id, current=60.0, speed=2.0, message='Transcrevendo')
    snap = job_store.job_snapshot(job_id)
    assert snap['status'] == 'running'
    assert snap['stage'] == 'transcribe'
    assert snap['progress_current'] == 60.0
    assert snap['progress_total'] == 120.0
    assert snap['percent'] == 50.0
    assert 29 <= snap['eta_seconds'] <= 31
    assert snap['backend'] == 'cuda'
    assert snap['heartbeat_at']


def test_recover_stale_jobs_marks_running_as_interrupted(monkeypatch, tmp_path):
    job_store = _setup(monkeypatch, tmp_path)
    job_id = job_store.create_job('project', 'p1')
    job_store.start_stage(job_id, 'tracking', total=10.0)
    stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    db.execute("UPDATE worker_jobs SET heartbeat_at=? WHERE id=?", (stale, job_id))
    recovered = job_store.recover_stale_jobs(stale_after_seconds=30)
    snap = job_store.job_snapshot(job_id)
    assert job_id in recovered
    assert snap['status'] == 'interrupted'
    assert 'interrompido' in snap['message'].lower()
