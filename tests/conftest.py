"""Fixtures for the blob-service suite.

blob-service has no application factory — app.py builds the Flask app at import
time and calls db.create_all() while doing it. So the only way to get a clean
app is to reload the module with the environment already pointed somewhere
harmless. That is what `app_under_test` does, and every other fixture builds on
it.

Two collaborators are replaced wholesale:

  auth-service  middleware/auth.py resolves identity by making a real HTTP call
                to /api/token/verify. FakeAuth stands in, so tests choose who
                the caller is by sending `Authorization: Bearer user:<id>`.
  S3            services/s3_service.py talks to SeaweedFS. FakeS3 records calls
                and hands back deterministic URLs.

Both fakes are asserted against in tests/contract/test_fakes.py, so a drift in
the real interface shows up rather than silently making the suite meaningless.
"""

import importlib
import os

import pytest

# The repo-root conftest.py already seeds fake credentials; repeat the ones this
# module depends on so the file is not order-sensitive.
os.environ.setdefault("PHASICON_DISABLE_S3_INIT", "1")
os.environ.setdefault("AUTH_SERVICE_URL", "http://auth-service.invalid:8080")

SUPER_ADMIN_ID = "1"
UPLOADER_ID = "7"
PLAIN_USER_ID = "9"
# routes/user_devices.py hardcodes this id as the admin override.
HARDCODED_ADMIN_ID = "41"


# --------------------------------------------------------------------------- #
# --live gate
# --------------------------------------------------------------------------- #

def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run tests that require a running blob-service",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs a running blob-service; pass --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


# --------------------------------------------------------------------------- #
# Environment isolation
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _no_dotenv_discovery(monkeypatch):
    """Stop config.py from loading a developer's real .env.

    config.py calls load_dotenv() with no argument, which searches upwards from
    the working directory. Run from a checkout, that walk reaches the root
    repository's .env and imports its live credentials — so a test that deletes
    POSTGRES_PASSWORD to prove configuration fails closed gets the value handed
    straight back on reload, and the test fails on exactly the machines where
    the file exists.

    Neutralising discovery makes every test depend only on what it sets. The
    name is re-bound on `importlib.reload(config)`, which is how config is
    always loaded here, so patching the dotenv module reaches it.
    """
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class FakeAuthResponse:
    """Mimics the requests.Response that middleware/auth.py inspects."""

    def __init__(self, status_code=200, payload=None, raises_on_json=False):
        self.status_code = status_code
        self.text = "fake auth response"
        self._payload = payload if payload is not None else {"user_id": 123}
        self._raises_on_json = raises_on_json

    def json(self):
        if self._raises_on_json:
            # The real requests raises JSONDecodeError here, which subclasses
            # RequestException. That distinction decides whether the middleware's
            # except clause catches it, so the fake must raise the same type.
            import requests

            raise requests.exceptions.JSONDecodeError("not json", "doc", 0)
        return self._payload


class FakeAuth:
    """Resolves a bearer token to a user id without leaving the process.

    Token conventions, so a test can pick an identity inline:
        "Bearer user:7"   -> authenticated as user 7
        "Bearer invalid"  -> auth-service answers 401
        "Bearer nouser"   -> auth-service answers 200 with no user_id
        "Bearer down"     -> auth-service is unreachable
    """

    def __init__(self):
        self.calls = []
        # middleware/auth.py catches requests.exceptions.RequestException off
        # the module it imported, so the stand-in has to carry the real
        # exception hierarchy or that except clause stops matching.
        import requests

        self.exceptions = requests.exceptions

    def get(self, url, headers=None, timeout=None, **kwargs):
        import requests

        header = (headers or {}).get("Authorization", "")
        self.calls.append({"url": url, "authorization": header, "timeout": timeout})

        token = header[7:] if header.startswith("Bearer ") else header

        if token == "down":
            raise requests.exceptions.ConnectionError("auth-service unreachable")
        if token == "invalid" or not token:
            return FakeAuthResponse(status_code=401, payload={})
        if token == "nouser":
            return FakeAuthResponse(status_code=200, payload={"isValid": True})
        if token == "notjson":
            return FakeAuthResponse(status_code=200, raises_on_json=True)
        if token.startswith("user:"):
            try:
                return FakeAuthResponse(status_code=200, payload={"user_id": int(token[5:])})
            except ValueError:
                # e.g. a duplicated header collapsed into "user:5, Bearer user:6".
                # The fake must answer like a real verifier, not raise into the
                # caller — an exception here would masquerade as a service bug.
                return FakeAuthResponse(status_code=401, payload={})
        # Anything else is a token auth-service does not recognise. Defaulting
        # to 401 rather than to a valid user keeps an accidentally-unauthenticated
        # request from looking like a passing test.
        return FakeAuthResponse(status_code=401, payload={})


class FakeS3:
    """Stands in for services/s3_service.s3_service.

    Mirrors the method names and signatures the routes actually call. Every call
    is recorded so tests can assert on the S3 key a route derived — which is
    where the ownership rules actually live.
    """

    def __init__(self):
        self.calls = []
        self.deleted = []
        self.fail_on_delete = False
        self.fail_on_download = False
        self.stored = {}

    def generate_presigned_upload(self, user_id, filename, content_type,
                                  device_type=None, version=None):
        self.calls.append(("upload", user_id, filename, content_type, device_type, version))
        key = (
            f"artifacts/{device_type}/{version}/{filename}"
            if device_type and version
            else f"{user_id}/{filename}"
        )
        self.stored[key] = content_type
        return {
            "uploadUrl": f"https://s3.invalid/{key}?signed=1",
            "key": key,
            "user_id": user_id,
            "filename": filename,
            "content_type": content_type,
        }

    def generate_presigned_download(self, key):
        self.calls.append(("download", key))
        if self.fail_on_download:
            raise RuntimeError("S3 unavailable")
        return f"https://s3.invalid/{key}?signed=1"

    def delete_file(self, key):
        self.calls.append(("delete", key))
        if self.fail_on_delete:
            raise RuntimeError("S3 delete failed")
        self.deleted.append(key)
        self.stored.pop(key, None)

    def list_files(self, user_id):
        self.calls.append(("list", user_id))
        return [k for k in self.stored if k.startswith(f"{user_id}/")]


# --------------------------------------------------------------------------- #
# Application fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def fake_s3():
    return FakeS3()


@pytest.fixture
def fake_auth():
    return FakeAuth()


@pytest.fixture
def app_under_test(monkeypatch, fake_s3, fake_auth):
    """A freshly imported blob-service app on an in-memory database.

    Reloading matters: app.py registers blueprints and creates tables as a side
    effect of import, so a stale module would share state across tests.
    """
    monkeypatch.setenv("PHASICON_DISABLE_S3_INIT", "1")
    monkeypatch.setenv("AUTH_SERVICE_URL", "http://auth-service.invalid:8080")
    monkeypatch.setenv("SUPER_ADMIN_ID", SUPER_ADMIN_ID)

    config = importlib.import_module("config")
    importlib.reload(config)
    # config derives a postgres URI from POSTGRES_*; override the built value so
    # db.create_all() at import does not reach for a real server.
    monkeypatch.setattr(config.Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

    app_module = importlib.import_module("app")
    importlib.reload(app_module)

    # Swap collaborators in every module that imported them by name.
    for module_name in ("routes.api", "routes.management", "routes.device"):
        module = importlib.import_module(module_name)
        importlib.reload(module)
        if hasattr(module, "s3_service"):
            monkeypatch.setattr(module, "s3_service", fake_s3)

    middleware_auth = importlib.import_module("middleware.auth")
    monkeypatch.setattr(middleware_auth, "requests", fake_auth)

    app_module.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    return app_module.app


@pytest.fixture
def client(app_under_test):
    return app_under_test.test_client()


@pytest.fixture
def db_session(app_under_test):
    """An app context with the schema created, for seeding rows directly."""
    from models import db

    with app_under_test.app_context():
        db.create_all()
        yield db
        db.session.remove()


def bearer(user_id):
    """Authorization header for a given user id, understood by FakeAuth."""
    return {"Authorization": f"Bearer user:{user_id}"}


@pytest.fixture
def admin_headers():
    return bearer(SUPER_ADMIN_ID)


@pytest.fixture
def uploader_headers():
    return bearer(UPLOADER_ID)


@pytest.fixture
def user_headers():
    return bearer(PLAIN_USER_ID)


# --------------------------------------------------------------------------- #
# Live fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def live_base_url():
    return os.getenv("BLOB_BASE_URL", "http://localhost:5000").rstrip("/")


@pytest.fixture(scope="session")
def live_token():
    token = os.getenv("BLOB_TEST_TOKEN")
    if not token:
        pytest.skip("set BLOB_TEST_TOKEN to an access token from auth-service")
    return token
