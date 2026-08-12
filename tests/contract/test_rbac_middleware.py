"""middleware/rbac.py — who may upload artifacts and who may administer.

Two roles sit on top of authentication:

  require_super_admin   identity must equal the SUPER_ADMIN_ID environment
                        variable. Nothing else grants it.
  require_uploader      SUPER_ADMIN_ID, or a row in allowed_uploaders.

Both compare `str(g.user_id)` against an env var, so an unset SUPER_ADMIN_ID is
the interesting case: it must not turn into a wildcard.
"""

import pytest

from tests.conftest import PLAIN_USER_ID, SUPER_ADMIN_ID, UPLOADER_ID, bearer

pytestmark = pytest.mark.contract

SUPER_ADMIN_ROUTE = "/admin/uploaders"
UPLOADER_ROUTE = "/devices"


@pytest.fixture
def seeded_uploader(db_session):
    """Put UPLOADER_ID in allowed_uploaders."""
    from models import AllowedUploader

    db_session.session.add(
        AllowedUploader(user_id=int(UPLOADER_ID), email="uploader@example.test", added_by=1)
    )
    db_session.session.commit()
    return UPLOADER_ID


# --------------------------------------------------------------------------- #
# require_super_admin
# --------------------------------------------------------------------------- #

def test_super_admin_is_allowed(client, db_session):
    resp = client.get(SUPER_ADMIN_ROUTE, headers=bearer(SUPER_ADMIN_ID))
    assert resp.status_code == 200


def test_plain_user_is_forbidden_from_admin_routes(client, db_session):
    resp = client.get(SUPER_ADMIN_ROUTE, headers=bearer(PLAIN_USER_ID))
    assert resp.status_code == 403
    assert "Super Admin" in resp.get_json()["error"]


def test_uploader_is_not_automatically_an_admin(client, db_session, seeded_uploader):
    """Being on the uploader list must not confer administration."""
    resp = client.get(SUPER_ADMIN_ROUTE, headers=bearer(UPLOADER_ID))
    assert resp.status_code == 403


def test_unauthenticated_request_stops_at_authentication(client, db_session):
    resp = client.get(SUPER_ADMIN_ROUTE)
    assert resp.status_code == 401


def test_unset_super_admin_id_denies_everyone(client, db_session, monkeypatch):
    """With SUPER_ADMIN_ID unset, `str(user_id) == None` is False for every
    caller. This test exists so that stays true — a change to `in` or a
    truthiness check would make the empty value match."""
    monkeypatch.delenv("SUPER_ADMIN_ID", raising=False)
    for identity in (SUPER_ADMIN_ID, PLAIN_USER_ID, UPLOADER_ID):
        resp = client.get(SUPER_ADMIN_ROUTE, headers=bearer(identity))
        assert resp.status_code == 403, (
            f"user {identity!r} was granted admin while SUPER_ADMIN_ID is unset"
        )


# --------------------------------------------------------------------------- #
# require_uploader
# --------------------------------------------------------------------------- #

def test_listed_uploader_is_allowed(client, db_session, seeded_uploader):
    resp = client.get(UPLOADER_ROUTE, headers=bearer(UPLOADER_ID))
    assert resp.status_code == 200


def test_unlisted_user_is_forbidden(client, db_session):
    resp = client.get(UPLOADER_ROUTE, headers=bearer(PLAIN_USER_ID))
    assert resp.status_code == 403
    assert "Uploader" in resp.get_json()["error"]


def test_super_admin_is_an_uploader_without_being_listed(client, db_session):
    """The bootstrap path: the first admin can upload before anyone is listed."""
    resp = client.get(UPLOADER_ROUTE, headers=bearer(SUPER_ADMIN_ID))
    assert resp.status_code == 200


def test_revoked_uploader_loses_access_immediately(client, db_session, seeded_uploader):
    """No caching between the table and the decision."""
    from models import AllowedUploader

    assert client.get(UPLOADER_ROUTE, headers=bearer(UPLOADER_ID)).status_code == 200

    AllowedUploader.query.filter_by(user_id=int(UPLOADER_ID)).delete()
    db_session.session.commit()

    assert client.get(UPLOADER_ROUTE, headers=bearer(UPLOADER_ID)).status_code == 403


def test_uploader_check_does_not_500_on_a_non_numeric_identity(client, db_session):
    """require_uploader does `int(g.user_id)` with no guard.

    Today auth-service always returns an integer user_id, so this cannot fire.
    It is pinned because the device PAT migration introduces credentials that
    are not user-shaped: if a PAT ever resolves to a non-numeric subject, this
    line is where it turns into a 500 instead of a 403.
    """
    resp = client.get(UPLOADER_ROUTE, headers={"Authorization": "Bearer user:12"})
    assert resp.status_code in (200, 403), f"unexpected {resp.status_code}"


# --------------------------------------------------------------------------- #
# Coverage of the whole role-gated surface
# --------------------------------------------------------------------------- #

SUPER_ADMIN_ONLY = [
    ("POST", "/admin/uploaders", {"user_id": 2, "email": "x@example.test"}),
    ("GET", "/admin/uploaders", None),
    ("DELETE", "/admin/uploaders/2", None),
]

UPLOADER_ONLY = [
    ("POST", "/artifacts", {"device_type": "d", "artifact_type": "a", "version": "1", "s3_key": "k"}),
    ("POST", "/artifacts/some-id/activate", None),
    ("DELETE", "/artifacts/some-id", None),
    ("GET", "/devices", None),
    ("POST", "/devices/dev-1/command", {"command": "ls"}),
    ("GET", "/commands/some-id", None),
    ("POST", "/devices/dev-1/terminal/start", None),
    ("GET", "/devices/dev-1/logs", None),
]


@pytest.mark.parametrize(
    "method,path,body", SUPER_ADMIN_ONLY, ids=[f"{m} {p}" for m, p, _ in SUPER_ADMIN_ONLY]
)
def test_super_admin_routes_reject_a_plain_user(client, db_session, method, path, body):
    resp = client.open(path, method=method, headers=bearer(PLAIN_USER_ID), json=body)
    assert resp.status_code == 403, f"{method} {path} returned {resp.status_code}"


@pytest.mark.parametrize(
    "method,path,body", UPLOADER_ONLY, ids=[f"{m} {p}" for m, p, _ in UPLOADER_ONLY]
)
def test_uploader_routes_reject_a_plain_user(client, db_session, method, path, body):
    resp = client.open(path, method=method, headers=bearer(PLAIN_USER_ID), json=body)
    assert resp.status_code == 403, f"{method} {path} returned {resp.status_code}"


@pytest.mark.parametrize(
    "method,path,body",
    SUPER_ADMIN_ONLY + UPLOADER_ONLY,
    ids=[f"{m} {p}" for m, p, _ in SUPER_ADMIN_ONLY + UPLOADER_ONLY],
)
def test_role_gated_routes_reject_anonymous(client, db_session, method, path, body):
    resp = client.open(path, method=method, json=body)
    assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"
