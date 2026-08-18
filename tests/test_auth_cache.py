"""The verification cache and the pooled session.

middleware/auth.py asks auth-service to validate every bearer token. That call
was costing 74.7ms because it built a new connection each time; over a reused
session the same call measures 0.8ms. Two things changed as a result -- a
module-level Session, and a short cache of successful verifications -- and both
have consequences worth pinning down.

The cache is the one with teeth: it means a token revoked at auth-service stays
accepted here until the entry expires. These tests fix that window's behaviour
so it cannot widen by accident.
"""

import importlib
import time

import pytest


@pytest.fixture
def auth(monkeypatch):
    """middleware.auth with a counting stub in place of the session."""
    mod = importlib.import_module("middleware.auth")
    importlib.reload(mod)

    calls = []

    class Resp:
        def __init__(self, status=200, payload=None):
            self.status_code = status
            self.text = "stub"
            self._payload = payload if payload is not None else {"user_id": 7}

        def json(self):
            return self._payload

    class Stub:
        def __init__(self):
            import requests
            self.exceptions = requests.exceptions

        def get(self, url, headers=None, timeout=None, **kw):
            header = (headers or {}).get("Authorization", "")
            calls.append(header)
            if "invalid" in header:
                return Resp(status=401, payload={})
            return Resp()

    stub = Stub()
    monkeypatch.setattr(mod, "_session", stub)
    monkeypatch.setattr(mod, "requests", stub)
    mod._cache.clear()
    return mod, calls


def _run(mod, header):
    """Drive require_auth once, returning (status, body) without a Flask app."""
    from flask import Flask

    app = Flask(__name__)

    @mod.require_auth
    def view():
        from flask import g
        return {"user_id": g.user_id}

    with app.test_request_context("/", headers={"Authorization": header} if header else {}):
        out = view()
        if isinstance(out, tuple):
            return out[1], out[0]
        return 200, out


def test_a_repeated_token_is_verified_once(auth):
    """The point of the cache: a burst from one client costs one round trip."""
    mod, calls = auth
    monkey_ttl = 30
    mod.CACHE_TTL = monkey_ttl

    for _ in range(10):
        status, body = _run(mod, "Bearer good-token")
        assert status == 200
        assert body["user_id"] == "7"

    assert len(calls) == 1, (
        f"expected one verification for ten identical requests, got {len(calls)}"
    )


def test_different_tokens_are_verified_separately(auth):
    """Caching is per credential, not global -- two users must not share a slot."""
    mod, calls = auth
    mod.CACHE_TTL = 30

    _run(mod, "Bearer token-a")
    _run(mod, "Bearer token-b")

    assert len(calls) == 2


def test_the_entry_expires(auth):
    """A revoked token must not be accepted forever.

    TTL is set to effectively zero rather than sleeping, so the test states the
    invariant without costing wall-clock time.
    """
    mod, calls = auth
    mod.CACHE_TTL = 0.001

    _run(mod, "Bearer good-token")
    time.sleep(0.01)
    _run(mod, "Bearer good-token")

    assert len(calls) == 2, "the cached entry outlived its TTL"


def test_failures_are_never_cached(auth):
    """A 401 is cheap to recompute, and caching it would lock out a client that
    fixed its credential -- and let a probe pin a negative result."""
    mod, calls = auth
    mod.CACHE_TTL = 30

    for _ in range(3):
        status, _ = _run(mod, "Bearer invalid")
        assert status == 401

    assert len(calls) == 3, "a rejection was cached"


def test_disabling_the_cache_restores_per_request_verification(auth):
    """AUTH_VERIFY_CACHE_TTL=0 is the escape hatch for immediate revocation."""
    mod, calls = auth
    mod.CACHE_TTL = 0

    for _ in range(4):
        _run(mod, "Bearer good-token")

    assert len(calls) == 4


def test_the_cache_key_is_not_the_raw_credential(auth):
    """The key is a digest, so a heap dump or a log of the map does not hand
    over a usable bearer token."""
    mod, _ = auth
    mod.CACHE_TTL = 30

    _run(mod, "Bearer secret-value-here")

    assert mod._cache, "nothing was cached"
    for key in mod._cache:
        assert "secret-value-here" not in key
        assert len(key) == 64  # sha256 hex


def test_the_cache_is_bounded(auth):
    """An unbounded map keyed by credential is a memory leak that an attacker
    can drive by presenting fresh tokens."""
    mod, _ = auth
    mod.CACHE_TTL = 30
    mod.CACHE_MAX = 16

    for i in range(50):
        _run(mod, f"Bearer token-{i}")

    assert len(mod._cache) <= mod.CACHE_MAX, (
        f"cache grew to {len(mod._cache)} with a cap of {mod.CACHE_MAX}"
    )


def test_the_session_is_pooled(auth):
    """The regression this whole change exists to prevent.

    A module-level Session with a sized pool is what turns 74.7ms into 0.8ms.
    If someone replaces it with a bare requests.get again, the latency returns
    silently -- nothing else in the suite would notice.
    """
    mod = importlib.import_module("middleware.auth")
    importlib.reload(mod)

    import requests
    assert isinstance(mod._session, requests.Session)

    adapter = mod._session.get_adapter("http://auth-service:8080")
    assert adapter._pool_maxsize > 1, (
        "the session's connection pool holds one connection, so concurrent "
        "requests will still build fresh ones"
    )


# --------------------------------------------------------------------------- #
# The S3 signing client
#
# Separate concern from the auth cache, same underlying mistake: building an
# expensive client on every request to do a cheap piece of work with it.
# --------------------------------------------------------------------------- #

def test_the_signing_client_is_built_once(monkeypatch):
    """generate_presigned_* must reuse one signing client.

    Signing happens against PUBLIC_S3_URL rather than the internal endpoint, or
    the Host the client presents will not match what was signed and SeaweedFS
    answers 403. That needs a second boto3 client -- but it is a constant.

    Measured in a pod on the arm64 node:

        boto3.client("s3")      6.1ms   (118ms on the first call)
        generate_presigned_url  0.26ms

    Twenty-four times the cost of the work, paid on every upload and download
    URL. Nothing functional notices, which is why it needs a test.
    """
    import importlib

    mod = importlib.import_module("services.s3_service")

    built = []
    real = mod.boto3.client

    def counting(*a, **kw):
        built.append(kw.get("endpoint_url"))
        return real(*a, **kw)

    monkeypatch.setattr(mod.boto3, "client", counting)

    svc = mod.S3Service.__new__(mod.S3Service)
    svc._signing_client = None

    first = svc._signing()
    for _ in range(25):
        assert svc._signing() is first, "a new signing client was built"

    assert len(built) == 1, (
        f"expected one client construction, got {len(built)}: {built}"
    )
