"""routes/api.py — presign, list, download, delete.

The security boundary in this blueprint is a string prefix. download() and
delete() both decide ownership with

    key.startswith(f"{g.user_id}/")

and that is the only thing standing between one user's namespace and another's.
Prefix matching has two failure modes worth holding still — traversal inside
the key, and one user id being a prefix of another — so both get explicit tests.
"""

import pytest

from tests.conftest import bearer

pytestmark = pytest.mark.contract


# --------------------------------------------------------------------------- #
# POST /presign-upload
# --------------------------------------------------------------------------- #

def test_presign_requires_authentication(client):
    assert client.post("/presign-upload", json={"filename": "a.txt"}).status_code == 401


def test_presign_requires_a_filename(client):
    resp = client.post("/presign-upload", headers=bearer(5), json={"content_type": "text/plain"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "filename required"


def test_presign_returns_an_upload_url(client):
    resp = client.post("/presign-upload", headers=bearer(5), json={"filename": "a.txt"})
    assert resp.status_code == 200
    assert resp.get_json()["uploadUrl"].startswith("https://")


def test_presign_uses_the_authenticated_user_not_a_body_field(client, fake_s3):
    """The body must not be able to choose whose namespace to write into."""
    client.post(
        "/presign-upload",
        headers=bearer(5),
        json={"filename": "a.txt", "user_id": 999},
    )
    upload = next(c for c in fake_s3.calls if c[0] == "upload")
    assert upload[1] == "5", (
        f"presign wrote into namespace {upload[1]!r}; a user_id in the body "
        "overrode the authenticated identity"
    )


def test_presign_defaults_the_content_type(client, fake_s3):
    client.post("/presign-upload", headers=bearer(5), json={"filename": "a.txt"})
    upload = next(c for c in fake_s3.calls if c[0] == "upload")
    assert upload[3] == "application/octet-stream"


def test_presign_takes_the_artifact_path_when_device_type_and_version_are_given(client, fake_s3):
    client.post(
        "/presign-upload",
        headers=bearer(5),
        json={"filename": "fw.bin", "device_type": "jetson", "version": "1.2.3"},
    )
    upload = next(c for c in fake_s3.calls if c[0] == "upload")
    assert upload[4] == "jetson" and upload[5] == "1.2.3"


def test_presign_falls_back_to_a_raw_upload_when_version_is_missing(client, fake_s3):
    """device_type alone is not enough — the route requires both."""
    client.post(
        "/presign-upload",
        headers=bearer(5),
        json={"filename": "fw.bin", "device_type": "jetson"},
    )
    upload = next(c for c in fake_s3.calls if c[0] == "upload")
    assert upload[4] is None and upload[5] is None


def test_presign_surfaces_an_s3_failure_as_500(client, fake_s3, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bucket is gone")

    monkeypatch.setattr(fake_s3, "generate_presigned_upload", boom)
    resp = client.post("/presign-upload", headers=bearer(5), json={"filename": "a.txt"})
    assert resp.status_code == 500


# --------------------------------------------------------------------------- #
# GET /files
# --------------------------------------------------------------------------- #

def test_list_files_requires_authentication(client):
    assert client.get("/files").status_code == 401


def test_list_files_is_scoped_to_the_caller(client, fake_s3):
    client.get("/files", headers=bearer(5))
    assert ("list", "5") in fake_s3.calls


def test_list_files_ignores_a_user_id_query_parameter(client, fake_s3):
    """The route comments say the query param is ignored. Pin it — this is the
    difference between listing your files and listing anyone's."""
    client.get("/files?user_id=999", headers=bearer(5))
    listed = [c for c in fake_s3.calls if c[0] == "list"]
    assert listed == [("list", "5")], f"listing used {listed}"


def test_list_files_returns_a_count_and_a_list(client, fake_s3):
    fake_s3.stored = {"5/a.txt": "text/plain", "5/b.txt": "text/plain", "6/c.txt": "text/plain"}
    body = client.get("/files", headers=bearer(5)).get_json()
    assert body["count"] == 2
    assert sorted(body["files"]) == ["5/a.txt", "5/b.txt"]


# --------------------------------------------------------------------------- #
# POST /download — ownership
# --------------------------------------------------------------------------- #

def test_download_requires_authentication(client):
    assert client.post("/download", json={"key": "5/a.txt"}).status_code == 401


def test_download_requires_a_key(client):
    resp = client.post("/download", headers=bearer(5), json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "key required"


def test_download_allows_a_key_in_the_callers_namespace(client):
    resp = client.post("/download", headers=bearer(5), json={"key": "5/a.txt"})
    assert resp.status_code == 200
    assert "downloadUrl" in resp.get_json()


def test_download_refuses_another_users_key(client):
    resp = client.post("/download", headers=bearer(5), json={"key": "6/secret.txt"})
    assert resp.status_code == 403


def test_download_refuses_a_bare_key_with_no_namespace(client):
    resp = client.post("/download", headers=bearer(5), json={"key": "secret.txt"})
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "key",
    [
        "5/../6/secret.txt",
        "5/../../6/secret.txt",
        "5/./../6/secret.txt",
        "5/a/../../6/secret.txt",
    ],
)
def test_download_rejects_traversal_out_of_the_callers_namespace(client, key, fake_s3):
    """`startswith("5/")` is satisfied by "5/../6/secret.txt".

    Whether that key actually escapes depends on the S3 implementation: S3 keys
    are opaque strings, so SeaweedFS should treat "5/../6/x" as a literal name
    and the traversal is inert. This test asserts the safe outcome either way —
    either the route refuses the key, or it passes through unnormalised so that
    it can only ever address a literal object of that name, never 6/secret.txt.
    """
    resp = client.post("/download", headers=bearer(5), json={"key": key})
    if resp.status_code == 200:
        requested = [c for c in fake_s3.calls if c[0] == "download"]
        assert requested, "a 200 with no S3 call means the route silently did nothing"
        assert requested[-1][1] == key, (
            f"the route normalised {key!r} to {requested[-1][1]!r} before "
            "handing it to S3 — normalisation after the ownership check is "
            "exactly how a prefix guard gets bypassed"
        )
    else:
        assert resp.status_code == 403


def test_download_prefix_check_is_not_fooled_by_a_longer_user_id(client):
    """User 5 must not reach user 55's objects.

    "55/x" does not start with "5/" thanks to the trailing slash. Drop that
    slash from the check and this test fails, which is the point.
    """
    resp = client.post("/download", headers=bearer(5), json={"key": "55/secret.txt"})
    assert resp.status_code == 403


def test_download_surfaces_an_s3_failure_as_500(client, fake_s3):
    fake_s3.fail_on_download = True
    resp = client.post("/download", headers=bearer(5), json={"key": "5/a.txt"})
    assert resp.status_code == 500


# --------------------------------------------------------------------------- #
# POST/DELETE /delete — ownership
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_delete_requires_authentication(client, method):
    assert client.open("/delete", method=method, json={"key": "5/a.txt"}).status_code == 401


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_delete_requires_a_key(client, method):
    resp = client.open("/delete", method=method, headers=bearer(5), json={})
    assert resp.status_code == 400


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_delete_removes_an_owned_key(client, method, fake_s3):
    resp = client.open("/delete", method=method, headers=bearer(5), json={"key": "5/a.txt"})
    assert resp.status_code == 200
    assert "5/a.txt" in fake_s3.deleted


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_delete_refuses_another_users_key(client, method, fake_s3):
    resp = client.open("/delete", method=method, headers=bearer(5), json={"key": "6/a.txt"})
    assert resp.status_code == 403
    assert fake_s3.deleted == [], "a forbidden delete still reached S3"


def test_delete_does_not_reach_s3_when_ownership_fails(client, fake_s3):
    """The check must happen before the call, not after."""
    client.post("/delete", headers=bearer(5), json={"key": "6/a.txt"})
    assert not [c for c in fake_s3.calls if c[0] == "delete"]


def test_delete_surfaces_an_s3_failure_as_500(client, fake_s3):
    fake_s3.fail_on_delete = True
    resp = client.post("/delete", headers=bearer(5), json={"key": "5/a.txt"})
    assert resp.status_code == 500
