from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import B2_APPLICATION_KEY, B2_BUCKET_NAME, B2_KEY_ID

AUTH_URL = "https://api.backblazeb2.com/b2api/v4/b2_authorize_account"


def configured() -> bool:
    return bool(B2_KEY_ID and B2_APPLICATION_KEY and B2_BUCKET_NAME)


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def upload_file(path: str | Path, *, key: str) -> dict:
    """Archive one completed artifact in the configured private B2 bucket."""
    if not configured():
        return {"archived": False, "reason": "not-configured"}
    source = Path(path)
    if not source.is_file():
        return {"archived": False, "reason": "missing-file"}
    basic = base64.b64encode(f"{B2_KEY_ID}:{B2_APPLICATION_KEY}".encode()).decode()
    with httpx.Client(timeout=120) as client:
        auth = client.get(AUTH_URL, headers={"Authorization": f"Basic {basic}"})
        auth.raise_for_status()
        session = auth.json()
        storage_api = (session.get("apiInfo") or {}).get("storageApi") or {}
        api_url = storage_api.get("apiUrl") or session.get("apiUrl")
        token = session.get("authorizationToken")
        allowed = session.get("allowed") or {}
        bucket_id = allowed.get("bucketId")
        if not api_url or not token or not bucket_id:
            raise RuntimeError("A chave B2 precisa ser limitada ao bucket configurado.")
        upload = client.post(f"{api_url}/b2api/v4/b2_get_upload_url", headers={"Authorization": token}, json={"bucketId": bucket_id})
        upload.raise_for_status()
        target = upload.json()
        headers = {
            "Authorization": target["authorizationToken"],
            "Content-Type": "b2/x-auto",
            "Content-Length": str(source.stat().st_size),
            "X-Bz-File-Name": quote(key, safe="/"),
            "X-Bz-Content-Sha1": _sha1(source),
        }
        with source.open("rb") as handle:
            response = client.post(target["uploadUrl"], headers=headers, content=handle)
        response.raise_for_status()
        data = response.json()
    return {"archived": True, "file_id": data.get("fileId"), "file_name": data.get("fileName"), "bucket": B2_BUCKET_NAME}
