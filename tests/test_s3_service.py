import importlib


def load_s3_module(monkeypatch):
    monkeypatch.setenv("PHASICON_DISABLE_S3_INIT", "1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "unit")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "unit-secret")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://seaweed-s3:8333")
    import services.s3_service as s3_module

    return importlib.reload(s3_module)


def test_user_file_keys_are_namespaced_and_unique(monkeypatch):
    s3_module = load_s3_module(monkeypatch)
    service = s3_module.S3Service.__new__(s3_module.S3Service)

    first = service.build_key("41", "report.pdf")
    second = service.build_key("41", "report.pdf")

    assert first.startswith("41/")
    assert first.endswith("_report.pdf")
    assert second.startswith("41/")
    assert first != second


def test_artifact_key_sanitizes_device_version_and_filename(monkeypatch):
    s3_module = load_s3_module(monkeypatch)
    service = s3_module.S3Service.__new__(s3_module.S3Service)

    key = service.build_artifact_key("rpi/../alpha", "1.0.0 beta", "firmware@prod.bin")

    assert key == "artifacts/rpialpha/1.0.0beta/firmwareprod.bin"
