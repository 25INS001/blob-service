"""routes/device.py — the endpoints the fleet itself calls.

These four routes are the device-facing half of blob-service, and they are the
ones the PAT migration is about. Three require a user access token today, which
is the wrong credential for a device to hold; the fourth requires nothing at
all. Both facts are pinned here so the migration has something to change
against.
"""

import pytest

from tests.conftest import bearer

pytestmark = pytest.mark.contract


@pytest.fixture
def device(db_session):
    from models import Device

    d = Device(device_id="dev-1", device_type="jetson", current_version="1.0.0")
    db_session.session.add(d)
    db_session.session.commit()
    return d


@pytest.fixture
def active_artifact(db_session):
    from models import Artifact

    a = Artifact(
        device_type="jetson",
        artifact_type="firmware",
        version="2.0.0",
        s3_key="artifacts/jetson/2.0.0/fw.bin",
        checksum="abc123",
        is_active=True,
        created_by=1,
    )
    db_session.session.add(a)
    db_session.session.commit()
    return a


# --------------------------------------------------------------------------- #
# POST /device/heartbeat
# --------------------------------------------------------------------------- #

def test_heartbeat_requires_authentication(client, db_session):
    resp = client.post("/device/heartbeat", json={"device_id": "dev-1"})
    assert resp.status_code == 401


def test_heartbeat_requires_a_device_id(client, db_session):
    resp = client.post("/device/heartbeat", headers=bearer(5), json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "device_id required"


def test_heartbeat_registers_an_unknown_device(client, db_session):
    """First contact creates the row — devices are not pre-provisioned."""
    from models import Device

    resp = client.post(
        "/device/heartbeat",
        headers=bearer(5),
        json={"device_id": "brand-new", "version": "1.0.0", "device_type": "jetson"},
    )
    assert resp.status_code == 200
    assert Device.query.get("brand-new") is not None


def test_heartbeat_records_the_reported_state(client, db_session, device):
    from models import Device

    client.post(
        "/device/heartbeat",
        headers=bearer(5),
        json={
            "device_id": "dev-1",
            "status": "updating",
            "version": "1.1.0",
            "device_type": "jetson",
            "stats": {"cpu": 42},
        },
    )
    refreshed = Device.query.get("dev-1")
    assert refreshed.status == "updating"
    assert refreshed.current_version == "1.1.0"
    assert refreshed.stats == {"cpu": 42}


def test_heartbeat_defaults_status_to_online(client, db_session, device):
    from models import Device

    client.post("/device/heartbeat", headers=bearer(5), json={"device_id": "dev-1"})
    assert Device.query.get("dev-1").status == "online"


def test_heartbeat_updates_last_seen(client, db_session, device):
    from models import Device

    before = Device.query.get("dev-1").last_seen
    client.post("/device/heartbeat", headers=bearer(5), json={"device_id": "dev-1"})
    assert Device.query.get("dev-1").last_seen >= before


def test_heartbeat_returns_pending_commands_and_marks_them_sent(client, db_session, device):
    from models import DeviceCommand

    cmd = DeviceCommand(device_id="dev-1", command="reboot")
    db_session.session.add(cmd)
    db_session.session.commit()
    command_id = cmd.id

    body = client.post(
        "/device/heartbeat", headers=bearer(5), json={"device_id": "dev-1"}
    ).get_json()

    assert [c["id"] for c in body["commands"]] == [command_id]
    assert DeviceCommand.query.get(command_id).status == "sent"


def test_a_command_is_only_delivered_once(client, db_session, device):
    """Commands are marked sent on delivery, so the next heartbeat is empty.

    Without this, a queued `reboot` would be executed on every heartbeat.
    """
    from models import DeviceCommand

    db_session.session.add(DeviceCommand(device_id="dev-1", command="reboot"))
    db_session.session.commit()

    first = client.post("/device/heartbeat", headers=bearer(5), json={"device_id": "dev-1"})
    second = client.post("/device/heartbeat", headers=bearer(5), json={"device_id": "dev-1"})

    assert len(first.get_json()["commands"]) == 1
    assert second.get_json()["commands"] == []


def test_commands_for_other_devices_are_not_delivered(client, db_session, device):
    from models import Device, DeviceCommand

    db_session.session.add(Device(device_id="dev-2"))
    db_session.session.commit()
    db_session.session.add(DeviceCommand(device_id="dev-2", command="rm -rf /"))
    db_session.session.commit()

    body = client.post(
        "/device/heartbeat", headers=bearer(5), json={"device_id": "dev-1"}
    ).get_json()
    assert body["commands"] == [], "a command queued for dev-2 was handed to dev-1"


def test_terminal_request_is_delivered_then_cleared(client, db_session, device):
    """The flag is one-shot: delivering it resets it, so a single click in the
    dashboard does not open a terminal on every subsequent heartbeat."""
    from models import Device

    device.terminal_requested = True
    db_session.session.commit()

    first = client.post("/device/heartbeat", headers=bearer(5), json={"device_id": "dev-1"})
    actions = [c.get("action") for c in first.get_json()["commands"]]
    assert "start_web_terminal" in actions
    assert Device.query.get("dev-1").terminal_requested is False

    second = client.post("/device/heartbeat", headers=bearer(5), json={"device_id": "dev-1"})
    assert second.get_json()["commands"] == []


# --------------------------------------------------------------------------- #
# POST /device/command/<id>/result
# --------------------------------------------------------------------------- #

def test_command_result_requires_authentication(client, db_session):
    assert client.post("/device/command/x/result", json={}).status_code == 401


def test_command_result_records_the_outcome(client, db_session, device):
    from models import DeviceCommand

    cmd = DeviceCommand(device_id="dev-1", command="uptime", status="sent")
    db_session.session.add(cmd)
    db_session.session.commit()

    resp = client.post(
        f"/device/command/{cmd.id}/result",
        headers=bearer(5),
        json={"status": "executed", "result": "up 3 days"},
    )
    assert resp.status_code == 200
    stored = DeviceCommand.query.get(cmd.id)
    assert stored.status == "executed"
    assert stored.result == "up 3 days"
    assert stored.executed_at is not None


def test_command_result_defaults_to_failed(client, db_session, device):
    """An empty report must not be read as success."""
    from models import DeviceCommand

    cmd = DeviceCommand(device_id="dev-1", command="uptime", status="sent")
    db_session.session.add(cmd)
    db_session.session.commit()

    client.post(f"/device/command/{cmd.id}/result", headers=bearer(5), json={})
    assert DeviceCommand.query.get(cmd.id).status == "failed"


def test_command_result_for_an_unknown_command_is_404(client, db_session):
    resp = client.post(
        "/device/command/no-such-command/result", headers=bearer(5), json={"status": "executed"}
    )
    assert resp.status_code == 404


@pytest.mark.defect
def test_any_authenticated_caller_can_report_a_result_for_any_command(client, db_session, device):
    """There is no check that the reporter is the device the command was for.

    Any user with a valid token can mark another device's command executed and
    write arbitrary text into its result field. Documented rather than asserted
    as correct: fixing it means binding the caller to a device, which is exactly
    what the PAT migration introduces.
    """
    from models import DeviceCommand

    cmd = DeviceCommand(device_id="dev-1", command="uptime", status="sent")
    db_session.session.add(cmd)
    db_session.session.commit()

    resp = client.post(
        f"/device/command/{cmd.id}/result",
        headers=bearer(9999),  # not dev-1, not its owner
        json={"status": "executed", "result": "forged"},
    )
    assert resp.status_code == 200, (
        "a caller unrelated to dev-1 was refused — the ownership check this "
        "test documents as missing now exists, so update the test"
    )


# --------------------------------------------------------------------------- #
# GET /update/check — unauthenticated
# --------------------------------------------------------------------------- #

def test_update_check_requires_no_authentication(client, db_session):
    """This is the one device route with no @require_auth.

    It is how a device that has not yet been provisioned can still pull its
    first firmware. The cost is that the endpoint hands a presigned download URL
    to anyone who can name a device_type — see the disclosure test below.
    """
    resp = client.get("/update/check?device_type=jetson&artifact_type=firmware")
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "query",
    ["", "?device_type=jetson", "?artifact_type=firmware", "?current_version=1.0.0"],
)
def test_update_check_requires_both_type_parameters(client, db_session, query):
    resp = client.get(f"/update/check{query}")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing params"


def test_update_check_reports_no_update_when_nothing_is_active(client, db_session):
    body = client.get("/update/check?device_type=jetson&artifact_type=firmware").get_json()
    assert body["update_available"] is False


def test_update_check_offers_an_active_artifact(client, db_session, active_artifact):
    body = client.get(
        "/update/check?device_type=jetson&artifact_type=firmware&current_version=1.0.0"
    ).get_json()
    assert body["update_available"] is True
    assert body["latest_version"] == "2.0.0"
    assert body["checksum"] == "abc123"
    assert body["download_url"].startswith("https://")


def test_update_check_is_quiet_when_already_current(client, db_session, active_artifact):
    body = client.get(
        "/update/check?device_type=jetson&artifact_type=firmware&current_version=2.0.0"
    ).get_json()
    assert body["update_available"] is False


def test_update_check_ignores_inactive_artifacts(client, db_session, active_artifact):
    """A newer version that has not been activated must not be rolled out."""
    from models import Artifact

    db_session.session.add(
        Artifact(
            device_type="jetson",
            artifact_type="firmware",
            version="3.0.0",
            s3_key="artifacts/jetson/3.0.0/fw.bin",
            is_active=False,
            created_by=1,
        )
    )
    db_session.session.commit()

    body = client.get(
        "/update/check?device_type=jetson&artifact_type=firmware&current_version=1.0.0"
    ).get_json()
    assert body["latest_version"] == "2.0.0", "an unactivated artifact was offered to a device"


def test_update_check_does_not_cross_device_types(client, db_session, active_artifact):
    body = client.get(
        "/update/check?device_type=raspberrypi&artifact_type=firmware"
    ).get_json()
    assert body["update_available"] is False


@pytest.mark.defect
def test_update_check_discloses_a_download_url_to_anyone(client, db_session, active_artifact):
    """Unauthenticated callers receive a working presigned firmware URL.

    Whoever can reach the host can enumerate device types and pull production
    firmware. Recorded as the current, deliberate behaviour — devices need it
    before they hold a credential — and as the thing a device PAT would let you
    close.
    """
    body = client.get("/update/check?device_type=jetson&artifact_type=firmware").get_json()
    assert "download_url" in body, (
        "the endpoint no longer hands out a URL unauthenticated — if it now "
        "requires a credential, move this test to the authenticated cases"
    )


# --------------------------------------------------------------------------- #
# POST /device/logs
# --------------------------------------------------------------------------- #

def test_upload_logs_requires_authentication(client, db_session):
    assert client.post("/device/logs", json={"device_id": "dev-1", "logs": "x"}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [{}, {"device_id": "dev-1"}, {"logs": "text"}, {"device_id": "", "logs": "text"},
     {"device_id": "dev-1", "logs": ""}],
)
def test_upload_logs_requires_both_fields(client, db_session, body):
    resp = client.post("/device/logs", headers=bearer(5), json=body)
    assert resp.status_code == 400


def test_upload_logs_stores_an_entry(client, db_session, device):
    from models import DeviceLog

    resp = client.post(
        "/device/logs",
        headers=bearer(5),
        json={"device_id": "dev-1", "logs": "boot ok", "type": "startup"},
    )
    assert resp.status_code in (200, 201)
    stored = DeviceLog.query.filter_by(device_id="dev-1", log_type="startup").first()
    assert stored is not None and stored.log_content == "boot ok"


def test_uploading_the_same_log_type_overwrites_rather_than_accumulates(client, db_session, device):
    """The route upserts on (device_id, log_type). A device reporting every
    minute must not grow an unbounded table."""
    from models import DeviceLog

    for i in range(3):
        client.post(
            "/device/logs",
            headers=bearer(5),
            json={"device_id": "dev-1", "logs": f"run {i}", "type": "run_sh"},
        )

    rows = DeviceLog.query.filter_by(device_id="dev-1", log_type="run_sh").all()
    assert len(rows) == 1, f"{len(rows)} rows accumulated for one device and log type"
    assert rows[0].log_content == "run 2"


def test_different_log_types_are_stored_separately(client, db_session, device):
    from models import DeviceLog

    for log_type in ("startup", "error", "run_sh"):
        client.post(
            "/device/logs",
            headers=bearer(5),
            json={"device_id": "dev-1", "logs": "x", "type": log_type},
        )
    assert DeviceLog.query.filter_by(device_id="dev-1").count() == 3


def test_log_type_defaults_to_generic(client, db_session, device):
    from models import DeviceLog

    client.post("/device/logs", headers=bearer(5), json={"device_id": "dev-1", "logs": "x"})
    assert DeviceLog.query.filter_by(device_id="dev-1", log_type="generic").first() is not None
