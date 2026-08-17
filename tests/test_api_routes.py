import importlib


class FakeAuthResponse:
    status_code = 200
    text = "ok"

    def json(self):
        return {"user_id": 123}


class FakeS3Service:
    def generate_presigned_upload(self, user_id, filename, content_type, device_type=None, version=None):
        return {
            "user_id": user_id,
            "filename": filename,
            "content_type": content_type,
            "device_type": device_type,
            "version": version,
            "uploadUrl": "https://upload.example.test",
        }

    def generate_presigned_download(self, key):
        return f"https://download.example.test/{key}"

    def delete_file(self, key):
        return None


def load_app(monkeypatch):
    monkeypatch.setenv("PHASICON_DISABLE_S3_INIT", "1")
    monkeypatch.setenv("AUTH_SERVICE_URL", "http://auth-service:8080")

    config = importlib.import_module("config")
    importlib.reload(config)

    # config builds a postgres URI from the required POSTGRES_* settings and no
    # longer honours DATABASE_URL, so point the app at an in-memory database
    # directly. app.py calls db.create_all() at import, which would otherwise
    # try to reach a real server. Must happen before app is (re)loaded.
    monkeypatch.setattr(config.Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

    app_module = importlib.import_module("app")
    importlib.reload(app_module)
    routes_api = importlib.import_module("routes.api")
    middleware_auth = importlib.import_module("middleware.auth")

    monkeypatch.setattr(routes_api, "s3_service", FakeS3Service())
    # The middleware verifies over a pooled Session, so patching requests.get
    # alone no longer intercepts it. Caching is disabled here too: these tests
    # reuse one Authorization header, and a cached result would leak the first
    # test's identity into the rest.
    monkeypatch.setattr(middleware_auth.requests, "get", lambda *args, **kwargs: FakeAuthResponse())
    monkeypatch.setattr(middleware_auth._session, "get", lambda *args, **kwargs: FakeAuthResponse())
    monkeypatch.setattr(middleware_auth, "CACHE_TTL", 0)
    middleware_auth._cache.clear()

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_presign_upload_requires_filename(monkeypatch):
    client = load_app(monkeypatch)

    response = client.post(
        "/presign-upload",
        headers={"Authorization": "Bearer test"},
        json={"content_type": "text/plain"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "filename required"


def test_presign_upload_returns_artifact_upload(monkeypatch):
    client = load_app(monkeypatch)

    response = client.post(
        "/presign-upload",
        headers={"Authorization": "Bearer test"},
        json={
            "filename": "firmware.bin",
            "content_type": "application/octet-stream",
            "device_type": "pi",
            "version": "1.2.3",
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["user_id"] == "123"
    assert body["device_type"] == "pi"
    assert body["version"] == "1.2.3"


def test_download_rejects_other_user_key(monkeypatch):
    client = load_app(monkeypatch)

    response = client.post(
        "/download",
        headers={"Authorization": "Bearer test"},
        json={"key": "456/private.txt"},
    )

    assert response.status_code == 403
