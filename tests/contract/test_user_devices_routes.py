"""routes/user_devices.py — binding devices to the people who own them.

Device binding is first-come: an unbound device belongs to whoever registers it
first, and after that another user gets a 409. That makes the binding check the
only thing preventing a user from claiming someone else's hardware, so it gets
tested from both directions.

This blueprint also carries a hardcoded administrator — `str(g.user_id) == '41'`
appears twice, granting cross-tenant read and hard delete. It is not derived
from SUPER_ADMIN_ID or from any table, so nothing else in the system can revoke
it. Tests below pin the behaviour exactly as written, and are marked so they
are easy to find when it is replaced by a real role.
"""

import pytest

from tests.conftest import HARDCODED_ADMIN_ID, bearer

pytestmark = pytest.mark.contract

OWNER = "5"
STRANGER = "6"


@pytest.fixture
def bound_device(db_session):
    from models import Device

    d = Device(device_id="dev-1", device_type="jetson", user_id=OWNER, friendly_name="Lab unit")
    db_session.session.add(d)
    db_session.session.commit()
    return d


@pytest.fixture
def unbound_device(db_session):
    from models import Device

    d = Device(device_id="dev-free", device_type="jetson")
    db_session.session.add(d)
    db_session.session.commit()
    return d


# --------------------------------------------------------------------------- #
# POST /api/user/devices/register
# --------------------------------------------------------------------------- #

def test_register_requires_authentication(client, db_session):
    resp = client.post("/api/user/devices/register", json={"device_id": "dev-1"})
    assert resp.status_code == 401


def test_register_requires_a_device_id(client, db_session):
    resp = client.post("/api/user/devices/register", headers=bearer(OWNER), json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "device_id is required"


def test_register_creates_an_unknown_device_and_binds_it(client, db_session):
    from models import Device

    resp = client.post(
        "/api/user/devices/register",
        headers=bearer(OWNER),
        json={"device_id": "brand-new", "friendly_name": "Bench"},
    )
    assert resp.status_code == 200
    stored = Device.query.get("brand-new")
    assert stored.user_id == OWNER
    assert stored.friendly_name == "Bench"


def test_register_claims_an_existing_unbound_device(client, db_session, unbound_device):
    from models import Device

    resp = client.post(
        "/api/user/devices/register", headers=bearer(OWNER), json={"device_id": "dev-free"}
    )
    assert resp.status_code == 200
    assert Device.query.get("dev-free").user_id == OWNER


def test_register_refuses_a_device_bound_to_someone_else(client, db_session, bound_device):
    from models import Device

    resp = client.post(
        "/api/user/devices/register", headers=bearer(STRANGER), json={"device_id": "dev-1"}
    )
    assert resp.status_code == 409
    assert Device.query.get("dev-1").user_id == OWNER, "the binding was overwritten"


def test_the_owner_can_re_register_their_own_device(client, db_session, bound_device):
    """Re-registering is how a device is renamed; it must not 409 against itself."""
    from models import Device

    resp = client.post(
        "/api/user/devices/register",
        headers=bearer(OWNER),
        json={"device_id": "dev-1", "friendly_name": "Renamed"},
    )
    assert resp.status_code == 200
    assert Device.query.get("dev-1").friendly_name == "Renamed"


def test_register_without_a_friendly_name_keeps_the_existing_one(client, db_session, bound_device):
    from models import Device

    client.post("/api/user/devices/register", headers=bearer(OWNER), json={"device_id": "dev-1"})
    assert Device.query.get("dev-1").friendly_name == "Lab unit"


def test_register_marks_the_device_seen(client, db_session, unbound_device):
    from models import Device

    client.post("/api/user/devices/register", headers=bearer(OWNER), json={"device_id": "dev-free"})
    assert Device.query.get("dev-free").last_seen is not None


@pytest.mark.defect
def test_the_hardcoded_admin_is_not_exempt_from_the_binding_check(client, db_session, bound_device):
    """User 41 overrides ownership on read and delete but not on register.

    That asymmetry is worth knowing about: the same identity that can delete any
    device cannot claim one. Pinned so a future change makes it deliberate.
    """
    resp = client.post(
        "/api/user/devices/register",
        headers=bearer(HARDCODED_ADMIN_ID),
        json={"device_id": "dev-1"},
    )
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# GET /api/user/devices
# --------------------------------------------------------------------------- #

def test_listing_requires_authentication(client, db_session):
    assert client.get("/api/user/devices").status_code == 401


def test_listing_returns_only_the_callers_devices(client, db_session, bound_device):
    from models import Device

    db_session.session.add(Device(device_id="dev-other", user_id=STRANGER))
    db_session.session.commit()

    body = client.get("/api/user/devices", headers=bearer(OWNER)).get_json()
    assert [d["device_id"] for d in body] == ["dev-1"]


def test_listing_excludes_unbound_devices(client, db_session, unbound_device):
    body = client.get("/api/user/devices", headers=bearer(OWNER)).get_json()
    assert body == []


def test_listing_is_empty_for_a_user_with_no_devices(client, db_session, bound_device):
    assert client.get("/api/user/devices", headers=bearer(STRANGER)).get_json() == []


# --------------------------------------------------------------------------- #
# GET /api/user/devices/<id>
# --------------------------------------------------------------------------- #

def test_owner_can_read_their_device(client, db_session, bound_device):
    body = client.get("/api/user/devices/dev-1", headers=bearer(OWNER)).get_json()
    assert body["device_id"] == "dev-1"
    assert body["friendly_name"] == "Lab unit"


def test_a_stranger_cannot_read_someone_elses_device(client, db_session, bound_device):
    resp = client.get("/api/user/devices/dev-1", headers=bearer(STRANGER))
    assert resp.status_code == 403


def test_reading_an_unknown_device_is_404(client, db_session):
    assert client.get("/api/user/devices/nope", headers=bearer(OWNER)).status_code == 404


def test_reading_an_unbound_device_is_forbidden(client, db_session, unbound_device):
    """user_id is None, which equals nobody, so no one may read it."""
    assert client.get("/api/user/devices/dev-free", headers=bearer(OWNER)).status_code == 403


def test_device_detail_includes_stats_and_cameras(client, db_session, bound_device):
    bound_device.stats = {"cpu": 12}
    bound_device.available_cameras = ["cam0"]
    db_session.session.commit()

    body = client.get("/api/user/devices/dev-1", headers=bearer(OWNER)).get_json()
    assert body["stats"] == {"cpu": 12}
    assert body["available_cameras"] == ["cam0"]


@pytest.mark.defect
def test_hardcoded_admin_41_can_read_any_device(client, db_session, bound_device):
    """`str(g.user_id) != '41'` in routes/user_devices.py.

    Not configurable and not revocable — if user 41 exists in auth-service, that
    account reads every device in the fleet. Replacing it with SUPER_ADMIN_ID or
    a role check should make this test fail.
    """
    resp = client.get("/api/user/devices/dev-1", headers=bearer(HARDCODED_ADMIN_ID))
    assert resp.status_code == 200, (
        "user 41 no longer has a blanket override — replace this test with one "
        "covering whatever role took its place"
    )


# --------------------------------------------------------------------------- #
# DELETE /api/user/devices/<id>
# --------------------------------------------------------------------------- #

def test_unbinding_requires_authentication(client, db_session, bound_device):
    assert client.delete("/api/user/devices/dev-1").status_code == 401


def test_owner_unbinds_rather_than_deletes(client, db_session, bound_device):
    """The row survives so the device keeps its history and can be re-claimed."""
    from models import Device

    resp = client.delete("/api/user/devices/dev-1", headers=bearer(OWNER))
    assert resp.status_code == 200
    assert "unbound" in resp.get_json()["message"]

    stored = Device.query.get("dev-1")
    assert stored is not None
    assert stored.user_id is None
    assert stored.friendly_name is None


def test_a_stranger_cannot_unbind_someone_elses_device(client, db_session, bound_device):
    from models import Device

    resp = client.delete("/api/user/devices/dev-1", headers=bearer(STRANGER))
    assert resp.status_code == 404
    assert Device.query.get("dev-1").user_id == OWNER


def test_unbinding_an_unknown_device_is_404(client, db_session):
    assert client.delete("/api/user/devices/nope", headers=bearer(OWNER)).status_code == 404


def test_an_unbound_device_can_be_claimed_again(client, db_session, bound_device):
    from models import Device

    client.delete("/api/user/devices/dev-1", headers=bearer(OWNER))
    resp = client.post(
        "/api/user/devices/register", headers=bearer(STRANGER), json={"device_id": "dev-1"}
    )
    assert resp.status_code == 200
    assert Device.query.get("dev-1").user_id == STRANGER


@pytest.mark.defect
def test_hardcoded_admin_41_hard_deletes_any_device(client, db_session, bound_device):
    from models import Device

    resp = client.delete("/api/user/devices/dev-1", headers=bearer(HARDCODED_ADMIN_ID))
    assert resp.status_code == 200
    assert "deleted" in resp.get_json()["message"]
    assert Device.query.get("dev-1") is None


def test_admin_delete_removes_dependent_commands(client, db_session, bound_device):
    """device_commands has a foreign key to devices; leaving rows behind would
    violate it. The route deletes them first."""
    from models import DeviceCommand

    db_session.session.add(DeviceCommand(device_id="dev-1", command="reboot"))
    db_session.session.commit()

    resp = client.delete("/api/user/devices/dev-1", headers=bearer(HARDCODED_ADMIN_ID))
    assert resp.status_code == 200
    assert DeviceCommand.query.filter_by(device_id="dev-1").count() == 0
