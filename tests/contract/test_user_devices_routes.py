"""routes/user_devices.py — device access through the group model.

A device is no longer owned by one user. It belongs to groups, each led by
exactly one user and containing any number of members, and a device may be in
several groups at once — so its authorised user set is the union across them.
`device_authorized_users` answers every question here.

Two distinctions carry most of the weight, and both are tested from both sides:

* **Member vs leader.** Membership grants sight of a device; leadership grants
  power over it. A member reads the dashboard, a leader unbinds.
* **Unauthorised vs absent.** Both answer 404. A 403 would confirm the device
  exists, which turns id enumeration into an inventory of the fleet.

The hardcoded `str(g.user_id) == '41'` override is gone; `SUPER_ADMIN_ID` took
its place and is audited on use. The tests that pinned user 41's powers now
assert it has none.
"""

import pytest

from tests.conftest import (
    HARDCODED_ADMIN_ID,
    SUPER_ADMIN_ID,
    bearer,
    grant_device,
)

pytestmark = pytest.mark.contract

OWNER = "5"
STRANGER = "6"
MEMBER = "8"


@pytest.fixture
def bound_device(db_session):
    """A device in one group, led by OWNER, with MEMBER alongside."""
    from models import Device

    d = Device(device_id="dev-1", device_type="jetson", user_id=OWNER, friendly_name="Lab unit")
    db_session.session.add(d)
    db_session.session.commit()
    grant_device(db_session, "dev-1", leader=OWNER, members=[MEMBER], name="lab")
    return d


@pytest.fixture
def unbound_device(db_session):
    """A device row in no group at all — claimable."""
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
    assert stored.friendly_name == "Bench"
    # The group is what actually grants access now.
    body = client.get("/api/user/devices", headers=bearer(OWNER)).get_json()
    assert "brand-new" in [d["device_id"] for d in body]


def test_registering_makes_the_caller_the_leader(client, db_session):
    """Adoption confers leadership, not mere membership — otherwise nobody
    could ever unbind the device they just claimed."""
    client.post(
        "/api/user/devices/register", headers=bearer(OWNER), json={"device_id": "brand-new"}
    )
    resp = client.delete("/api/user/devices/brand-new", headers=bearer(OWNER))
    assert resp.status_code == 200


def test_register_claims_an_existing_unbound_device(client, db_session, unbound_device):
    resp = client.post(
        "/api/user/devices/register", headers=bearer(OWNER), json={"device_id": "dev-free"}
    )
    assert resp.status_code == 200
    body = client.get("/api/user/devices", headers=bearer(OWNER)).get_json()
    assert [d["device_id"] for d in body] == ["dev-free"]


def test_register_refuses_a_device_in_someone_elses_group(client, db_session, bound_device):
    resp = client.post(
        "/api/user/devices/register", headers=bearer(STRANGER), json={"device_id": "dev-1"}
    )
    assert resp.status_code == 409
    # The stranger gained nothing.
    assert client.get("/api/user/devices", headers=bearer(STRANGER)).get_json() == []


def test_a_member_can_re_register_without_conflict(client, db_session, bound_device):
    """A member is already authorised, so this is a rename, not a claim."""
    from models import Device

    resp = client.post(
        "/api/user/devices/register",
        headers=bearer(MEMBER),
        json={"device_id": "dev-1", "friendly_name": "Renamed by member"},
    )
    assert resp.status_code == 200
    assert Device.query.get("dev-1").friendly_name == "Renamed by member"


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


def test_user_41_is_not_exempt_from_the_binding_check(client, db_session, bound_device):
    """Formerly the hardcoded admin. It is an ordinary account now."""
    resp = client.post(
        "/api/user/devices/register",
        headers=bearer(HARDCODED_ADMIN_ID),
        json={"device_id": "dev-1"},
    )
    assert resp.status_code == 409


def test_a_failed_group_creation_does_not_leave_a_half_bound_device(
    client, db_session, fake_group_api
):
    """If auth-service refuses, the device must not be left looking claimed."""
    fake_group_api.fail_with = (403, "Nope")

    resp = client.post(
        "/api/user/devices/register", headers=bearer(OWNER), json={"device_id": "half-bound"}
    )
    assert resp.status_code == 403
    assert client.get("/api/user/devices", headers=bearer(OWNER)).get_json() == []


def test_group_service_being_down_is_a_503(client, db_session, fake_group_api):
    fake_group_api.fail_with = "down"

    resp = client.post(
        "/api/user/devices/register", headers=bearer(OWNER), json={"device_id": "no-service"}
    )
    assert resp.status_code == 503


# --------------------------------------------------------------------------- #
# GET /api/user/devices
# --------------------------------------------------------------------------- #

def test_listing_requires_authentication(client, db_session):
    assert client.get("/api/user/devices").status_code == 401


def test_listing_returns_only_the_callers_devices(client, db_session, bound_device):
    from models import Device

    db_session.session.add(Device(device_id="dev-other", user_id=STRANGER))
    db_session.session.commit()
    grant_device(db_session, "dev-other", leader=STRANGER, name="theirs")

    body = client.get("/api/user/devices", headers=bearer(OWNER)).get_json()
    assert [d["device_id"] for d in body] == ["dev-1"]


def test_listing_includes_devices_the_caller_only_belongs_to(client, db_session, bound_device):
    """Membership is enough to see a device — this is the whole point of groups."""
    body = client.get("/api/user/devices", headers=bearer(MEMBER)).get_json()
    assert [d["device_id"] for d in body] == ["dev-1"]


def test_listing_unions_across_groups(client, db_session, bound_device):
    """A user in two groups sees the devices of both, once each."""
    from models import Device

    db_session.session.add(Device(device_id="dev-2", user_id=OWNER))
    db_session.session.commit()
    grant_device(db_session, "dev-2", leader=OWNER, name="second")
    # dev-1 again, in a different group the same user leads.
    grant_device(db_session, "dev-1", leader=OWNER, name="overlapping")

    body = client.get("/api/user/devices", headers=bearer(OWNER)).get_json()
    assert sorted(d["device_id"] for d in body) == ["dev-1", "dev-2"]


def test_listing_excludes_ungrouped_devices(client, db_session, unbound_device):
    assert client.get("/api/user/devices", headers=bearer(OWNER)).get_json() == []


def test_listing_is_empty_for_a_user_with_no_devices(client, db_session, bound_device):
    assert client.get("/api/user/devices", headers=bearer(STRANGER)).get_json() == []


def test_a_soft_deleted_group_withdraws_access(client, db_session, bound_device):
    from sqlalchemy import text

    db_session.session.execute(text('UPDATE "groups" SET deleted_at = CURRENT_TIMESTAMP'))
    db_session.session.commit()

    assert client.get("/api/user/devices", headers=bearer(OWNER)).get_json() == []


# --------------------------------------------------------------------------- #
# GET /api/user/devices/<id>
# --------------------------------------------------------------------------- #

def test_owner_can_read_their_device(client, db_session, bound_device):
    body = client.get("/api/user/devices/dev-1", headers=bearer(OWNER)).get_json()
    assert body["device_id"] == "dev-1"
    assert body["friendly_name"] == "Lab unit"


def test_a_member_can_read_the_device(client, db_session, bound_device):
    resp = client.get("/api/user/devices/dev-1", headers=bearer(MEMBER))
    assert resp.status_code == 200


def test_a_stranger_cannot_read_someone_elses_device(client, db_session, bound_device):
    """404, not 403: a 403 would confirm dev-1 exists."""
    resp = client.get("/api/user/devices/dev-1", headers=bearer(STRANGER))
    assert resp.status_code == 404


def test_an_unauthorised_read_is_indistinguishable_from_a_missing_device(
    client, db_session, bound_device
):
    denied = client.get("/api/user/devices/dev-1", headers=bearer(STRANGER))
    missing = client.get("/api/user/devices/nope", headers=bearer(STRANGER))
    assert denied.status_code == missing.status_code == 404
    assert denied.get_json() == missing.get_json()


def test_reading_an_unknown_device_is_404(client, db_session):
    assert client.get("/api/user/devices/nope", headers=bearer(OWNER)).status_code == 404


def test_reading_an_ungrouped_device_is_404(client, db_session, unbound_device):
    """In no group means authorised to nobody."""
    assert client.get("/api/user/devices/dev-free", headers=bearer(OWNER)).status_code == 404


def test_device_detail_includes_stats_and_cameras(client, db_session, bound_device):
    bound_device.stats = {"cpu": 12}
    bound_device.available_cameras = ["cam0"]
    db_session.session.commit()

    body = client.get("/api/user/devices/dev-1", headers=bearer(OWNER)).get_json()
    assert body["stats"] == {"cpu": 12}
    assert body["available_cameras"] == ["cam0"]


def test_user_41_has_no_blanket_read_override(client, db_session, bound_device):
    """The hardcoded override is gone. 41 is now just an id."""
    resp = client.get("/api/user/devices/dev-1", headers=bearer(HARDCODED_ADMIN_ID))
    assert resp.status_code == 404


def test_the_configured_super_admin_can_read_any_device(client, db_session, bound_device):
    """SUPER_ADMIN_ID replaces the hardcoded id: configurable, and revocable by
    unsetting it."""
    resp = client.get("/api/user/devices/dev-1", headers=bearer(SUPER_ADMIN_ID))
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# DELETE /api/user/devices/<id>
# --------------------------------------------------------------------------- #

def test_unbinding_requires_authentication(client, db_session, bound_device):
    assert client.delete("/api/user/devices/dev-1").status_code == 401


def test_leader_unbinds_rather_than_deletes(client, db_session, bound_device):
    """The row survives so the device keeps its history and can be re-claimed."""
    from models import Device

    resp = client.delete("/api/user/devices/dev-1", headers=bearer(OWNER))
    assert resp.status_code == 200
    assert "unbound" in resp.get_json()["message"]

    stored = Device.query.get("dev-1")
    assert stored is not None
    assert stored.user_id is None
    assert stored.friendly_name is None


def test_a_member_cannot_unbind(client, db_session, bound_device):
    """Membership grants sight, not power. A member removing the device would
    take it away from the leader and everyone else."""
    resp = client.delete("/api/user/devices/dev-1", headers=bearer(MEMBER))
    assert resp.status_code == 404
    assert client.get("/api/user/devices/dev-1", headers=bearer(OWNER)).status_code == 200


def test_unbinding_only_detaches_groups_the_caller_leads(client, db_session, bound_device):
    """A device in two groups stays reachable through the one left alone."""
    grant_device(db_session, "dev-1", leader=STRANGER, name="theirs-too")

    resp = client.delete("/api/user/devices/dev-1", headers=bearer(OWNER))
    assert resp.status_code == 200
    assert resp.get_json()["groups_detached"] == 1

    assert client.get("/api/user/devices/dev-1", headers=bearer(OWNER)).status_code == 404
    assert client.get("/api/user/devices/dev-1", headers=bearer(STRANGER)).status_code == 200


def test_unbinding_leaves_the_legacy_column_alone_while_other_groups_remain(
    client, db_session, bound_device
):
    from models import Device

    grant_device(db_session, "dev-1", leader=STRANGER, name="theirs-too")
    client.delete("/api/user/devices/dev-1", headers=bearer(OWNER))

    # Still grouped, so the compatibility column must not be cleared.
    assert Device.query.get("dev-1").user_id is not None


def test_a_stranger_cannot_unbind_someone_elses_device(client, db_session, bound_device):
    resp = client.delete("/api/user/devices/dev-1", headers=bearer(STRANGER))
    assert resp.status_code == 404
    assert client.get("/api/user/devices/dev-1", headers=bearer(OWNER)).status_code == 200


def test_unbinding_an_unknown_device_is_404(client, db_session):
    assert client.delete("/api/user/devices/nope", headers=bearer(OWNER)).status_code == 404


def test_an_unbound_device_can_be_claimed_again(client, db_session, bound_device):
    client.delete("/api/user/devices/dev-1", headers=bearer(OWNER))
    resp = client.post(
        "/api/user/devices/register", headers=bearer(STRANGER), json={"device_id": "dev-1"}
    )
    assert resp.status_code == 200
    body = client.get("/api/user/devices", headers=bearer(STRANGER)).get_json()
    assert [d["device_id"] for d in body] == ["dev-1"]


def test_user_41_has_no_blanket_delete_override(client, db_session, bound_device):
    from models import Device

    resp = client.delete("/api/user/devices/dev-1", headers=bearer(HARDCODED_ADMIN_ID))
    assert resp.status_code == 404
    assert Device.query.get("dev-1") is not None


def test_the_configured_super_admin_hard_deletes_any_device(client, db_session, bound_device):
    from models import Device

    resp = client.delete("/api/user/devices/dev-1", headers=bearer(SUPER_ADMIN_ID))
    assert resp.status_code == 200
    assert "deleted" in resp.get_json()["message"]
    assert Device.query.get("dev-1") is None


def test_super_admin_delete_removes_dependent_commands(client, db_session, bound_device):
    """device_commands has a foreign key to devices; leaving rows behind would
    violate it. The route deletes them first."""
    from models import DeviceCommand

    db_session.session.add(DeviceCommand(device_id="dev-1", command="reboot"))
    db_session.session.commit()

    resp = client.delete("/api/user/devices/dev-1", headers=bearer(SUPER_ADMIN_ID))
    assert resp.status_code == 200
    assert DeviceCommand.query.filter_by(device_id="dev-1").count() == 0


def test_super_admin_override_is_logged(client, db_session, bound_device, caplog):
    """An override bypasses the group model, so it must never be silent."""
    with caplog.at_level("WARNING"):
        client.delete("/api/user/devices/dev-1", headers=bearer(SUPER_ADMIN_ID))
    assert any("SUPER-ADMIN OVERRIDE" in r.message for r in caplog.records)
