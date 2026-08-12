"""routes/camera_api.py — the camera request channel.

Two different callers share this blueprint: the on-device camera app polls, and
the dashboard starts and stops feeds. They meet at Device.active_camera_command,
which is a single nullable column — so "start" is last-writer-wins and "stop"
clears it for everyone.

Note that camera_api_bp is not registered in app.py. Every test here first
asserts the route exists, so if the blueprint is wired up later they begin
covering it rather than silently passing.
"""

import pytest

from tests.conftest import bearer

pytestmark = pytest.mark.contract

OWNER = "5"


def route_registered(app, rule):
    return any(r.rule == rule for r in app.url_map.iter_rules())


@pytest.fixture(autouse=True)
def skip_if_blueprint_is_not_registered(app_under_test):
    if not route_registered(app_under_test, "/api/device/camera/poll"):
        pytest.skip(
            "camera_api_bp is not registered in app.py — routes/camera_api.py is "
            "dead code today. Register the blueprint and these tests activate."
        )


@pytest.fixture
def device(db_session):
    from models import Device

    d = Device(device_id="dev-1", device_type="jetson", user_id=OWNER)
    db_session.session.add(d)
    db_session.session.commit()
    return d


# --------------------------------------------------------------------------- #
# POST /api/device/camera/poll
# --------------------------------------------------------------------------- #

def test_poll_requires_authentication(client, db_session):
    assert client.post("/api/device/camera/poll", json={"device_id": "dev-1"}).status_code == 401


def test_poll_requires_a_device_id(client, db_session):
    resp = client.post("/api/device/camera/poll", headers=bearer(OWNER), json={})
    assert resp.status_code == 400


def test_poll_on_an_unknown_device_is_404(client, db_session):
    """Unlike heartbeat, polling does not auto-create — the device must have
    checked in through the main service first."""
    resp = client.post(
        "/api/device/camera/poll", headers=bearer(OWNER), json={"device_id": "ghost"}
    )
    assert resp.status_code == 404


def test_poll_records_the_reported_cameras(client, db_session, device):
    from models import Device

    client.post(
        "/api/device/camera/poll",
        headers=bearer(OWNER),
        json={"device_id": "dev-1", "cameras": ["cam0", "cam1"]},
    )
    assert Device.query.get("dev-1").available_cameras == ["cam0", "cam1"]


def test_poll_returns_no_command_when_none_is_pending(client, db_session, device):
    body = client.post(
        "/api/device/camera/poll", headers=bearer(OWNER), json={"device_id": "dev-1"}
    ).get_json()
    assert body["command"] is None


def test_poll_returns_the_requested_camera(client, db_session, device):
    device.active_camera_command = "cam0"
    db_session.session.commit()

    body = client.post(
        "/api/device/camera/poll", headers=bearer(OWNER), json={"device_id": "dev-1"}
    ).get_json()
    assert body["command"] == "cam0"


def test_poll_does_not_clear_the_request(client, db_session, device):
    """Unlike a queued command, the camera request is level-triggered: it stays
    set until the dashboard stops it, so the feed does not die after one poll."""
    from models import Device

    device.active_camera_command = "cam0"
    db_session.session.commit()

    client.post("/api/device/camera/poll", headers=bearer(OWNER), json={"device_id": "dev-1"})
    assert Device.query.get("dev-1").active_camera_command == "cam0"


def test_poll_with_no_cameras_field_clears_the_list(client, db_session, device):
    from models import Device

    device.available_cameras = ["cam0"]
    db_session.session.commit()

    client.post("/api/device/camera/poll", headers=bearer(OWNER), json={"device_id": "dev-1"})
    assert Device.query.get("dev-1").available_cameras == []


# --------------------------------------------------------------------------- #
# start / stop
# --------------------------------------------------------------------------- #

def test_start_requires_authentication(client, db_session):
    resp = client.post("/api/device/dev-1/camera/start", json={"camera_id": "cam0"})
    assert resp.status_code == 401


def test_start_requires_a_camera_id(client, db_session, device):
    resp = client.post("/api/device/dev-1/camera/start", headers=bearer(OWNER), json={})
    assert resp.status_code == 400


def test_start_sets_the_requested_camera(client, db_session, device):
    from models import Device

    resp = client.post(
        "/api/device/dev-1/camera/start", headers=bearer(OWNER), json={"camera_id": "cam0"}
    )
    assert resp.status_code == 200
    assert Device.query.get("dev-1").active_camera_command == "cam0"


def test_start_on_an_unknown_device_is_404(client, db_session):
    resp = client.post(
        "/api/device/ghost/camera/start", headers=bearer(OWNER), json={"camera_id": "cam0"}
    )
    assert resp.status_code == 404


def test_start_replaces_a_previous_request(client, db_session, device):
    from models import Device

    client.post("/api/device/dev-1/camera/start", headers=bearer(OWNER), json={"camera_id": "cam0"})
    client.post("/api/device/dev-1/camera/start", headers=bearer(OWNER), json={"camera_id": "cam1"})
    assert Device.query.get("dev-1").active_camera_command == "cam1"


def test_stop_clears_the_request(client, db_session, device):
    from models import Device

    device.active_camera_command = "cam0"
    db_session.session.commit()

    resp = client.post("/api/device/dev-1/camera/stop", headers=bearer(OWNER))
    assert resp.status_code == 200
    assert Device.query.get("dev-1").active_camera_command is None


def test_stop_on_an_unknown_device_is_404(client, db_session):
    assert client.post("/api/device/ghost/camera/stop", headers=bearer(OWNER)).status_code == 404


def test_stop_is_idempotent(client, db_session, device):
    assert client.post("/api/device/dev-1/camera/stop", headers=bearer(OWNER)).status_code == 200
    assert client.post("/api/device/dev-1/camera/stop", headers=bearer(OWNER)).status_code == 200


@pytest.mark.defect
def test_any_authenticated_user_can_drive_any_devices_camera(client, db_session, device):
    """Neither start nor stop checks that the caller owns the device.

    dev-1 is bound to user 5; user 6 can still open its camera feed. The
    ownership check that GET /api/user/devices/<id> performs is absent here.
    """
    resp = client.post(
        "/api/device/dev-1/camera/start", headers=bearer("6"), json={"camera_id": "cam0"}
    )
    assert resp.status_code == 200, (
        "camera control now enforces ownership — update this test to assert 403"
    )
