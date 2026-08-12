"""middleware/auth.py — the gate every protected route sits behind.

require_auth does not verify anything locally. It forwards the caller's
Authorization header to auth-service /api/token/verify and believes the answer.
That makes three things worth pinning: what it accepts, what it rejects, and
how it behaves when auth-service is not there — because the last one decides
whether an auth-service outage fails open or closed.
"""

import pytest

pytestmark = pytest.mark.contract

PROTECTED = "/files"


def test_missing_authorization_header_is_401(client):
    resp = client.get(PROTECTED)
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Missing Authorization header"


def test_missing_header_does_not_call_auth_service(client, fake_auth):
    """Short-circuit before the network hop, so an unauthenticated flood cannot
    be turned into a denial-of-service against auth-service."""
    client.get(PROTECTED)
    assert fake_auth.calls == []


def test_valid_token_is_accepted(client, fake_auth):
    resp = client.get(PROTECTED, headers={"Authorization": "Bearer user:5"})
    assert resp.status_code == 200
    assert len(fake_auth.calls) == 1


def test_authorization_header_is_forwarded_verbatim(client, fake_auth):
    """auth-service does the parsing; blob-service must not reinterpret."""
    client.get(PROTECTED, headers={"Authorization": "Bearer user:5"})
    assert fake_auth.calls[0]["authorization"] == "Bearer user:5"


def test_verification_targets_the_configured_auth_service(client, fake_auth):
    client.get(PROTECTED, headers={"Authorization": "Bearer user:5"})
    assert fake_auth.calls[0]["url"].endswith("/api/token/verify")
    assert "auth-service.invalid" in fake_auth.calls[0]["url"]


def test_verification_has_a_timeout(client, fake_auth):
    """Without one, a hung auth-service pins a worker thread per request until
    the whole pool is exhausted."""
    client.get(PROTECTED, headers={"Authorization": "Bearer user:5"})
    timeout = fake_auth.calls[0]["timeout"]
    assert timeout is not None, "the call to auth-service has no timeout"
    assert 0 < timeout <= 30, f"timeout of {timeout}s is not a sane bound"


def test_rejected_token_is_401(client):
    resp = client.get(PROTECTED, headers={"Authorization": "Bearer invalid"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Unauthorized"


def test_valid_response_without_user_id_is_401(client):
    """A 200 carrying no user_id must not be treated as authenticated — g.user_id
    would be None and every S3 prefix would collapse to the same namespace."""
    resp = client.get(PROTECTED, headers={"Authorization": "Bearer nouser"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Invalid token payload"


def test_user_id_zero_is_rejected(client):
    """`if not user_id` treats 0 as absent.

    Whether user 0 can exist is auth-service's business, but the consequence
    here is worth pinning: a zero id never reaches a route, so it can never
    become the S3 prefix "0/".
    """
    resp = client.get(PROTECTED, headers={"Authorization": "Bearer user:0"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Invalid token payload"


def test_auth_service_outage_fails_closed_with_503(client):
    """Fail closed, and say so with a 503 rather than a 401.

    401 would tell a device its credential is bad and, for the fleet's
    no-retry-on-401 rule, permanently kill its heartbeat over what was a
    transient dependency outage.
    """
    resp = client.get(PROTECTED, headers={"Authorization": "Bearer down"})
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Authentication unavailable"


def test_auth_service_response_body_is_not_echoed_to_the_caller(client):
    """auth-service's reply is an internal detail; echoing it leaks topology."""
    resp = client.get(PROTECTED, headers={"Authorization": "Bearer invalid"})
    body = resp.get_data(as_text=True).lower()
    assert "fake auth response" not in body
    assert "auth-service.invalid" not in body


def test_user_id_is_stringified_for_s3_prefixes(client, fake_s3):
    """middleware/auth.py does str(user_id) precisely so keys are `<id>/...`."""
    client.post(
        "/presign-upload",
        headers={"Authorization": "Bearer user:5"},
        json={"filename": "a.txt"},
    )
    upload = next(c for c in fake_s3.calls if c[0] == "upload")
    assert upload[1] == "5", f"presign received user_id {upload[1]!r}, expected the string '5'"


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Basic dXNlcjpwYXNz",
        "Bearer  ",
        "Token user:5",
        "Bearer user:5, Bearer user:6",
    ],
)
def test_malformed_authorization_headers_never_500(client, header):
    """Whatever the shape, the answer is a status we chose — not a crash.

    blob-service does not parse the header itself; it hands the whole thing to
    auth-service. So the assertion here is narrow on purpose: no 500, and the
    request never reaches the route body. Which shapes auth-service actually
    rejects is pinned in the live layer, where the real verifier answers.
    """
    resp = client.get(PROTECTED, headers={"Authorization": header})
    assert resp.status_code in (401, 403, 503), (
        f"header {header!r} produced HTTP {resp.status_code}"
    )


def test_non_json_response_from_auth_service_is_handled(client):
    """A 200 whose body is not JSON — an HTML error page from a proxy, say.

    middleware/auth.py calls resp.json() with no guard of its own, but requests
    raises JSONDecodeError, which subclasses RequestException and so lands in
    the existing except clause. The result is a 503, which is the right answer:
    the dependency misbehaved, the credential is not known to be bad.
    """
    resp = client.get(PROTECTED, headers={"Authorization": "Bearer notjson"})
    assert resp.status_code == 503, (
        f"expected 503 for a non-JSON auth response, got {resp.status_code}"
    )
