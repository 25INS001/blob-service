"""Black-box HTTP against a running blob-service.

The contract layer replaces auth-service and S3 with fakes, which is what makes
it fast and safe — and also what it cannot prove. Three things only exist when
the real processes are running:

  * a real access token from auth-service is accepted here
  * a presigned URL actually works against SeaweedFS
  * the deployed nginx routes these paths to this service

Run with the stack up:

    BLOB_BASE_URL=http://localhost:5000 \
    BLOB_TEST_TOKEN=$(...access token...) \
    pytest --live tests/live
"""

import uuid

import pytest
import requests

pytestmark = pytest.mark.live


@pytest.fixture
def auth(live_token):
    return {"Authorization": f"Bearer {live_token}"}


def test_service_is_reachable(live_base_url):
    try:
        resp = requests.get(f"{live_base_url}/files", timeout=10)
    except requests.exceptions.RequestException as exc:
        pytest.fail(f"blob-service unreachable at {live_base_url}: {exc}")
    assert resp.status_code in (401, 200)


def test_anonymous_request_is_rejected(live_base_url):
    assert requests.get(f"{live_base_url}/files", timeout=10).status_code == 401


def test_a_real_access_token_is_accepted(live_base_url, auth):
    """The end-to-end proof that blob-service and auth-service agree.

    A failure here with the contract suite green means the two services
    disagree about the token format or the verify response shape.
    """
    resp = requests.get(f"{live_base_url}/files", headers=auth, timeout=15)
    assert resp.status_code == 200, (
        f"a real access token was refused: {resp.status_code} {resp.text[:200]}"
    )


def test_a_garbage_token_is_rejected(live_base_url):
    resp = requests.get(
        f"{live_base_url}/files", headers={"Authorization": "Bearer nonsense"}, timeout=15
    )
    assert resp.status_code == 401


def test_presigned_upload_url_actually_works(live_base_url, auth):
    """Mint a URL, PUT through it, and read the object back.

    This is the one path the fakes cannot check: whether the signature the
    service produces is one SeaweedFS will accept.
    """
    filename = f"live-test-{uuid.uuid4().hex}.txt"
    payload = b"phasicon live upload probe"

    presign = requests.post(
        f"{live_base_url}/presign-upload",
        headers=auth,
        json={"filename": filename, "content_type": "text/plain"},
        timeout=15,
    )
    assert presign.status_code == 200, f"presign failed: {presign.text[:300]}"
    upload_url = presign.json()["uploadUrl"]

    put = requests.put(
        upload_url, data=payload, headers={"Content-Type": "text/plain"}, timeout=30, verify=False
    )
    assert put.status_code in (200, 201, 204), (
        f"the presigned PUT was refused by S3: {put.status_code} {put.text[:300]}"
    )

    listing = requests.get(f"{live_base_url}/files", headers=auth, timeout=15).json()
    key = next((k for k in listing["files"] if filename in str(k)), None)
    assert key is not None, f"{filename} is not in the caller's listing after upload"

    download = requests.post(
        f"{live_base_url}/download", headers=auth, json={"key": key}, timeout=15
    )
    assert download.status_code == 200, download.text[:300]

    fetched = requests.get(download.json()["downloadUrl"], timeout=30, verify=False)
    assert fetched.status_code == 200
    assert fetched.content == payload, "the object round-tripped with different bytes"

    cleanup = requests.post(
        f"{live_base_url}/delete", headers=auth, json={"key": key}, timeout=15
    )
    assert cleanup.status_code == 200


def test_another_users_key_is_refused(live_base_url, auth):
    """Prefix ownership, against the real identity rather than a fake one."""
    resp = requests.post(
        f"{live_base_url}/download",
        headers=auth,
        json={"key": "0/definitely-not-mine.txt"},
        timeout=15,
    )
    assert resp.status_code == 403


def test_update_check_needs_no_credential(live_base_url):
    resp = requests.get(
        f"{live_base_url}/update/check",
        params={"device_type": "probe-nonexistent", "artifact_type": "firmware"},
        timeout=15,
    )
    assert resp.status_code == 200
    assert resp.json()["update_available"] is False


def test_update_check_still_validates_its_parameters(live_base_url):
    assert requests.get(f"{live_base_url}/update/check", timeout=15).status_code == 400


@pytest.mark.fuzz
@pytest.mark.parametrize(
    "body",
    [b"", b"not json", b"{", b"[]", b"null", b"123"],
    ids=["empty", "text", "truncated", "array", "null", "number"],
)
def test_malformed_bodies_do_not_take_the_service_down(live_base_url, auth, body):
    """The contract suite records that some of these 500 in process.

    Repeated here against the real deployment for a different reason: a 500 is
    tolerated, a dropped connection or a service that stops answering the next
    request is not.
    """
    try:
        requests.post(
            f"{live_base_url}/device/heartbeat",
            headers={**auth, "Content-Type": "application/json"},
            data=body,
            timeout=15,
        )
    except requests.exceptions.RequestException as exc:
        pytest.fail(f"the connection failed on a malformed body: {exc}")

    after = requests.get(f"{live_base_url}/files", headers=auth, timeout=15)
    assert after.status_code == 200, "the service stopped answering after a malformed body"


@pytest.mark.fuzz
def test_oversized_upload_request_is_bounded(live_base_url, auth):
    resp = requests.post(
        f"{live_base_url}/presign-upload",
        headers=auth,
        json={"filename": "x" * 100_000},
        timeout=30,
    )
    assert resp.status_code != 500 or "error" in resp.text.lower()
