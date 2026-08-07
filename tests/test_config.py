import importlib

import pytest


def test_database_uri_is_composed_from_postgres_parts(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "svc")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "blob")
    import config

    importlib.reload(config)

    assert (
        config.Config.SQLALCHEMY_DATABASE_URI
        == "postgresql://svc:pw@db.internal:6543/blob"
    )


@pytest.mark.parametrize(
    "missing",
    ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST", "POSTGRES_DB",
     "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
)
def test_missing_credential_is_fatal(monkeypatch, missing):
    """Configuration must fail closed.

    An in-code default for a credential is how a service ends up quietly
    running on a placeholder in production, so importing config without one
    has to raise rather than fall back.
    """
    monkeypatch.delenv(missing, raising=False)
    import config

    with pytest.raises(RuntimeError, match=missing):
        importlib.reload(config)


def test_public_socket_url_has_local_default(monkeypatch):
    monkeypatch.delenv("PUBLIC_SOCKET_URL", raising=False)
    import config

    importlib.reload(config)

    assert config.Config.PUBLIC_SOCKET_URL == "ws://localhost:5000"


def test_s3_endpoint_defaults_to_the_compose_service_name(monkeypatch):
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    import config

    importlib.reload(config)

    assert config.Config.S3_ENDPOINT == "http://s3:8333"
