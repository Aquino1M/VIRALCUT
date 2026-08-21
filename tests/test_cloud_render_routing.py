from pathlib import Path

from app import db
from app.services import compute_fabric


def test_cloud_mode_uses_lightning_for_render(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "cloud.db")
    db.init_db()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    out = tmp_path / "result.mp4"
    calls = []
    monkeypatch.setattr(compute_fabric.cloud_client, "configured", lambda: True)
    monkeypatch.setattr(compute_fabric.cloud_client, "health", lambda **_: {"ok": True})
    monkeypatch.setattr(compute_fabric.cloud_client, "submit_task", lambda *args, **kwargs: calls.append(args[0]) or "cloud-job")
    monkeypatch.setattr(compute_fabric.cloud_client, "wait_job", lambda *args, **kwargs: {"encoder": "lightning-cpu"})
    monkeypatch.setattr(compute_fabric.cloud_client, "download_result_file", lambda _job, target: Path(target).write_bytes(b"cloud") or Path(target))

    result, route = compute_fabric.render_adaptive(
        source, out, render_kind="clean", payload={"start": 0, "end": 1, "edit_state": {}},
        profile={}, mode="hybrid", local_renderer=lambda: (_ for _ in ()).throw(AssertionError("local render used")),
    )

    assert calls == ["render"]
    assert out.read_bytes() == b"cloud"
    assert result["encoder"] == "lightning-cpu"
    assert route["selected"] == "cloud_cpu"
