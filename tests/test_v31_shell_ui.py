from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "shell.db")
    db.init_db()
    client = TestClient(main.app)
    client.post("/register", data={"email": "shell@test.com", "password": "abcdef"})
    return client


def test_app_shell_has_workflow_sidebar_and_mobile_create_fab(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    html = client.get("/dashboard").text
    assert "ViralClip Studio" in html
    assert "Cortes e editor" in html
    assert "Criar cortes" in html
    assert "Admin" in html
    assert 'href="/projects/new"' in html
    assert 'href="/videos"' in html
    assert 'href="/admin"' in html
    assert 'href="/hardware"' not in html
    assert "Auto Edit</b>" not in html
    assert "Fila de Publicação" not in html
    assert "Viralytics" not in html
    assert "mobile-create-fab" in html
    assert "theme-toggle" in html


def test_new_project_is_source_first_and_prefills_url(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    url = "https://www.youtube.com/watch?v=test123"
    response = client.get("/projects/new", params={"url": url})
    assert response.status_code == 200
    html = response.text
    assert "Cole o link do vídeo" in html
    assert url.replace("&", "&amp;") in html
    assert "Clique ou arraste um arquivo" in html
    assert "10 GB" in html
    assert "10 horas" in html
    assert "drop-zone" in html
    assert "Configurações do corte" in html
    assert "Layout padrão" in html
    assert "Auto Edit" in html


def test_studio_catalog_pages_exist(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for path, text in [
        ("/videos", "Meus Vídeos"),
        ("/library", "Biblioteca Inteligente"),
        ("/templates", "Templates"),
        ("/brand-kit", "Brand Kit"),
        ("/hardware", "Hardware Local"),
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert text in response.text


def test_library_and_admin_are_hidden_from_regular_users(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.post("/logout")
    client.post("/register", data={"email": "regular@test.com", "password": "abcdef"})
    html = client.get("/dashboard").text
    assert 'href="/admin"' not in html
    assert 'href="/library"' not in html
    assert client.get("/admin").status_code == 403
    assert client.get("/library").status_code == 403
    assert client.get("/api/v1/assets").status_code == 403


def test_hardware_page_uses_detected_profile(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main.hardware_service,
        "load_or_build_profile",
        lambda: {
            "gpu_vendor": "nvidia",
            "gpu_name": "GeForce Test",
            "ram_mb": 16384,
            "cpu_threads": 8,
            "os": "Windows",
            "render": {"encoder": "h264_nvenc", "verified": True},
            "transcription": {"backend": "cuda", "model": "small", "cpu_threads": 4},
            "analysis": {"tracking_fps": 2.5, "width": 720},
            "profile": {"name": "turbo", "label": "TURBO"},
        },
    )
    html = client.get("/hardware").text
    assert "GeForce Test" in html
    assert "h264_nvenc" in html
    assert "cuda" in html.lower()
    assert "TURBO" in html


def test_reference_secrets_are_not_embedded_in_templates():
    root = Path(main.BASE_DIR) / "app" / "templates"
    combined = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.html"))
    # The reference HTML contained live-looking account credentials. Our UI must
    # be an independent implementation and never carry those values forward.
    assert ("real" + "ofc_") not in combined
    assert ("read" + "_only_token") not in combined
    assert "tax_id" not in combined
