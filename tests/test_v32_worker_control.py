from datetime import datetime, timedelta, timezone

from app import db


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'control.db')
    db.init_db()
    from app.services import job_store, worker_control
    jid=job_store.create_job('project','p1')
    job_store.start_stage(jid,'tracking',total=100)
    return job_store, worker_control, jid


def test_job_control_pause_resume_cancel(monkeypatch,tmp_path):
    store, control_mod, jid=_setup(monkeypatch,tmp_path)
    ctl=control_mod.JobControl(jid)
    store.set_control(jid,'paused')
    assert ctl.is_paused() is True
    store.set_control(jid,'running')
    assert ctl.is_paused() is False
    store.set_control(jid,'cancelled')
    assert ctl.should_cancel() is True


def test_tracking_attempts_degrade_fps_resolution_and_detector():
    from app.services import worker_control
    attempts=worker_control.tracking_attempts({'analysis':{'tracking_fps':2.0,'width':720}})
    assert attempts[0]['fps']==2.0 and attempts[0]['width']==720
    assert attempts[1]['fps'] < attempts[0]['fps']
    assert attempts[1]['width'] < attempts[0]['width']
    assert attempts[-1]['detector_backend']=='haar'


def test_stale_snapshot_detection():
    from app.services import worker_control
    stale=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    fresh=datetime.now(timezone.utc).isoformat()
    assert worker_control.is_stale({'heartbeat_at':stale},stale_after_seconds=30)
    assert not worker_control.is_stale({'heartbeat_at':fresh},stale_after_seconds=30)
