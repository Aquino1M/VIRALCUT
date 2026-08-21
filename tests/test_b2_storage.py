from app.services import b2_storage


class _Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


class _Client:
    def __init__(self): self.posts = []
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def get(self, *_args, **_kwargs):
        return _Response({"authorizationToken":"account-token","allowed":{"bucketId":"bucket-id"},"apiInfo":{"storageApi":{"apiUrl":"https://api.example"}}})
    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if url.endswith("b2_get_upload_url"):
            return _Response({"authorizationToken":"upload-token","uploadUrl":"https://upload.example"})
        return _Response({"fileId":"file-id","fileName":"projects/p1/clips/clip.mp4"})


def test_uploads_completed_file_with_restricted_bucket_key(monkeypatch, tmp_path):
    source = tmp_path / "clip.mp4"; source.write_bytes(b"video")
    client = _Client()
    monkeypatch.setattr(b2_storage, "B2_KEY_ID", "key-id")
    monkeypatch.setattr(b2_storage, "B2_APPLICATION_KEY", "secret")
    monkeypatch.setattr(b2_storage, "B2_BUCKET_NAME", "viralgen-media")
    monkeypatch.setattr(b2_storage.httpx, "Client", lambda **_: client)

    saved = b2_storage.upload_file(source, key="projects/p1/clips/clip.mp4")

    assert saved["archived"] is True
    assert client.posts[-1][1]["headers"]["X-Bz-File-Name"] == "projects/p1/clips/clip.mp4"
