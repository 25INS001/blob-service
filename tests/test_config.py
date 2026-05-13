import importlib


def test_database_url_overrides_postgres_parts(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    import config

    importlib.reload(config)

    assert config.Config.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"


def test_public_socket_url_has_local_default(monkeypatch):
    monkeypatch.delenv("PUBLIC_SOCKET_URL", raising=False)
    import config

    importlib.reload(config)

    assert config.Config.PUBLIC_SOCKET_URL == "ws://localhost:5000"
