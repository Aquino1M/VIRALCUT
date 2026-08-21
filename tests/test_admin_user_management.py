from fastapi.testclient import TestClient

from app import db, main


def test_admin_can_search_and_delete_regular_user(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "admin.db")
    db.init_db()
    client = TestClient(main.app)
    client.post("/register", data={"email": "admin@test.com", "password": "password1"})
    client.post("/logout")
    client.post("/register", data={"email": "remove-me@test.com", "password": "password1"})
    target = db.fetchone("SELECT id FROM users WHERE email='remove-me@test.com'")
    now = db.now_iso()
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p-delete',?,'P','upload','smart','{}',?,?)", (target["id"], now, now))
    client.post("/logout")
    client.post("/login", data={"email": "admin@test.com", "password": "password1"})

    assert "remove-me@test.com" in client.get("/admin?q=remove-me").text
    response = client.post(f"/admin/users/{target['id']}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert db.fetchone("SELECT id FROM users WHERE id=?", (target["id"],)) is None
    assert db.fetchone("SELECT id FROM projects WHERE id='p-delete'") is None
