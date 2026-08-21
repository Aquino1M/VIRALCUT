import httpx

from app.services.cloud_client import _response_detail


def test_cloud_error_detail_uses_worker_message():
    response = httpx.Response(400, json={"detail": "ffprobe não encontrado"})

    assert _response_detail(response) == "ffprobe não encontrado"
