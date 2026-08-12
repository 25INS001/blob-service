"""routes/management.py — artifact and fleet administration.

The artifact lifecycle is the part with real invariants. "Active" means "this is
what devices will install", and exactly one artifact per (device_type,
artifact_type) may hold it. Two different code paths set it — creating with
is_active, and activating later — so both are tested for the same property.
"""

import pytest

from tests.conftest import SUPER_ADMIN_ID, UPLOADER_ID, bearer

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def uploader_row(db_session):
    from models import AllowedUploader

    db_session.session.add(
        AllowedUploader(user_id=int(UPLOADER_ID), email="uploader@example.test", added_by=1)
    )
    db_session.session.commit()


@pytest.fixture
def artifact_factory(db_session):
    from models import Artifact

    def make(version, active=False, device_type="jetson", artifact_type="firmware"):
        a = Artifact(
            device_type=device_type,
            artifact_type=artifact_type,
            version=version,
            s3_key=f"artifacts/{device_type}/{version}/fw.bin",
            checksum="deadbeef",
            is_active=active,
            created_by=int(UPLOADER_ID),
        )
        db_session.session.add(a)
        db_session.session.commit()
        return a

    return make


def active_versions(device_type="jetson", artifact_type="firmware"):
    from models import Artifact

    return sorted(
        a.version
        for a in Artifact.query.filter_by(
            device_type=device_type, artifact_type=artifact_type, is_active=True
        ).all()
    )


# --------------------------------------------------------------------------- #
# Uploader administration
# --------------------------------------------------------------------------- #

def test_admin_can_add_an_uploader(client, db_session):
    from models import AllowedUploader

    resp = client.post(
        "/admin/uploaders",
        headers=bearer(SUPER_ADMIN_ID),
        json={"user_id": 22, "email": "new@example.test"},
    )
    assert resp.status_code == 201
    assert AllowedUploader.query.filter_by(user_id=22).first() is not None


def test_adding_an_uploader_records_who_added_them(client, db_session):
    """added_by is an Integer column but g.user_id is a string.

    The comparison is against int deliberately: the value round-trips through
    the column type, so what comes back is an int on both SQLite and Postgres.
    A test asserting the string would pass only before the row was flushed.
    """
    from models import AllowedUploader

    client.post(
        "/admin/uploaders",
        headers=bearer(SUPER_ADMIN_ID),
        json={"user_id": 22, "email": "new@example.test"},
    )
    assert AllowedUploader.query.filter_by(user_id=22).first().added_by == int(SUPER_ADMIN_ID)


@pytest.mark.parametrize("body", [{}, {"user_id": 22}, {"email": "a@b.test"}])
def test_adding_an_uploader_needs_both_fields(client, db_session, body):
    resp = client.post("/admin/uploaders", headers=bearer(SUPER_ADMIN_ID), json=body)
    assert resp.status_code == 400


def test_adding_a_duplicate_uploader_is_rejected_not_crashed(client, db_session):
    payload = {"user_id": int(UPLOADER_ID), "email": "dupe@example.test"}
    resp = client.post("/admin/uploaders", headers=bearer(SUPER_ADMIN_ID), json=payload)
    assert resp.status_code == 400, "a primary-key clash should be a 400, not a 500"


def test_admin_can_list_uploaders(client, db_session):
    body = client.get("/admin/uploaders", headers=bearer(SUPER_ADMIN_ID)).get_json()
    assert any(u["user_id"] == int(UPLOADER_ID) for u in body)


def test_admin_can_remove_an_uploader(client, db_session):
    from models import AllowedUploader

    resp = client.delete(f"/admin/uploaders/{UPLOADER_ID}", headers=bearer(SUPER_ADMIN_ID))
    assert resp.status_code == 200
    assert AllowedUploader.query.filter_by(user_id=int(UPLOADER_ID)).first() is None


def test_removing_an_uploader_revokes_their_upload_rights(client, db_session):
    client.delete(f"/admin/uploaders/{UPLOADER_ID}", headers=bearer(SUPER_ADMIN_ID))
    assert client.get("/devices", headers=bearer(UPLOADER_ID)).status_code == 403


# --------------------------------------------------------------------------- #
# POST /artifacts
# --------------------------------------------------------------------------- #

def _artifact_body(version="1.0.0", **extra):
    body = {
        "device_type": "jetson",
        "artifact_type": "firmware",
        "version": version,
        "s3_key": f"artifacts/jetson/{version}/fw.bin",
        "checksum": "deadbeef",
    }
    body.update(extra)
    return body


def test_uploader_can_register_an_artifact(client, db_session):
    resp = client.post("/artifacts", headers=bearer(UPLOADER_ID), json=_artifact_body())
    assert resp.status_code == 201
    assert "id" in resp.get_json()


def test_a_new_artifact_is_inactive_by_default(client, db_session):
    """Registering must not roll anything out. Activation is a separate act."""
    client.post("/artifacts", headers=bearer(UPLOADER_ID), json=_artifact_body())
    assert active_versions() == []


def test_registering_a_duplicate_version_is_rejected(client, db_session, artifact_factory):
    artifact_factory("1.0.0")
    resp = client.post("/artifacts", headers=bearer(UPLOADER_ID), json=_artifact_body("1.0.0"))
    assert resp.status_code == 400
    assert "already exists" in resp.get_json()["error"]


def test_the_same_version_may_exist_for_a_different_device_type(client, db_session, artifact_factory):
    artifact_factory("1.0.0", device_type="jetson")
    resp = client.post(
        "/artifacts", headers=bearer(UPLOADER_ID), json=_artifact_body("1.0.0", device_type="rpi")
    )
    assert resp.status_code == 201


@pytest.mark.parametrize("missing", ["device_type", "artifact_type", "version", "s3_key"])
def test_registering_an_artifact_needs_its_required_fields(client, db_session, missing):
    body = _artifact_body()
    del body[missing]
    resp = client.post("/artifacts", headers=bearer(UPLOADER_ID), json=body)
    assert resp.status_code == 400, f"missing {missing} returned {resp.status_code}"


def test_creating_an_active_artifact_deactivates_the_previous_one(client, db_session, artifact_factory):
    artifact_factory("1.0.0", active=True)
    client.post(
        "/artifacts", headers=bearer(UPLOADER_ID), json=_artifact_body("2.0.0", is_active=True)
    )
    assert active_versions() == ["2.0.0"], (
        "two versions are active at once — devices would install whichever the "
        "query happened to order first"
    )


def test_creating_an_active_artifact_does_not_touch_other_device_types(client, db_session, artifact_factory):
    artifact_factory("1.0.0", active=True, device_type="rpi")
    client.post(
        "/artifacts", headers=bearer(UPLOADER_ID), json=_artifact_body("2.0.0", is_active=True)
    )
    assert active_versions(device_type="rpi") == ["1.0.0"]


def test_artifact_records_its_uploader(client, db_session):
    from models import Artifact

    resp = client.post("/artifacts", headers=bearer(UPLOADER_ID), json=_artifact_body())
    assert Artifact.query.get(resp.get_json()["id"]).created_by == int(UPLOADER_ID)


# --------------------------------------------------------------------------- #
# GET /artifacts
# --------------------------------------------------------------------------- #

def test_listing_artifacts_only_needs_authentication(client, db_session, artifact_factory):
    """Deliberately not uploader-gated: the dashboard shows the catalogue to
    any signed-in user."""
    artifact_factory("1.0.0")
    assert client.get("/artifacts", headers=bearer(999)).status_code == 200


def test_listing_artifacts_can_filter_by_device_type(client, db_session, artifact_factory):
    artifact_factory("1.0.0", device_type="jetson")
    artifact_factory("1.0.0", device_type="rpi")

    body = client.get("/artifacts?device_type=rpi", headers=bearer(UPLOADER_ID)).get_json()
    assert {a["device_type"] for a in body} == {"rpi"}


def test_listing_artifacts_returns_the_expected_shape(client, db_session, artifact_factory):
    artifact_factory("1.0.0")
    entry = client.get("/artifacts", headers=bearer(UPLOADER_ID)).get_json()[0]
    assert set(entry) == {"id", "device_type", "artifact_type", "version", "is_active", "created_at"}


def test_listing_artifacts_does_not_leak_the_s3_key(client, db_session, artifact_factory):
    """The key is the thing a presigned URL is minted against; the catalogue
    listing has no reason to hand it out."""
    artifact_factory("1.0.0")
    body = client.get("/artifacts", headers=bearer(999)).get_json()
    assert "s3_key" not in body[0]


# --------------------------------------------------------------------------- #
# Download / activate / delete
# --------------------------------------------------------------------------- #

def test_artifact_download_returns_a_url(client, db_session, artifact_factory):
    a = artifact_factory("1.0.0")
    body = client.get(f"/artifacts/{a.id}/download", headers=bearer(UPLOADER_ID)).get_json()
    assert body["download_url"].startswith("https://")


def test_artifact_download_for_an_unknown_id_is_404(client, db_session):
    assert client.get("/artifacts/nope/download", headers=bearer(UPLOADER_ID)).status_code == 404


def test_artifact_download_surfaces_an_s3_failure_as_500(client, db_session, artifact_factory, fake_s3):
    a = artifact_factory("1.0.0")
    fake_s3.fail_on_download = True
    assert client.get(f"/artifacts/{a.id}/download", headers=bearer(UPLOADER_ID)).status_code == 500


def test_activating_an_artifact_deactivates_its_siblings(client, db_session, artifact_factory):
    artifact_factory("1.0.0", active=True)
    target = artifact_factory("2.0.0")

    resp = client.post(f"/artifacts/{target.id}/activate", headers=bearer(UPLOADER_ID))
    assert resp.status_code == 200
    assert active_versions() == ["2.0.0"]


def test_activation_is_idempotent(client, db_session, artifact_factory):
    target = artifact_factory("1.0.0", active=True)
    client.post(f"/artifacts/{target.id}/activate", headers=bearer(UPLOADER_ID))
    assert active_versions() == ["1.0.0"]


def test_rolling_back_to_an_older_version_is_allowed(client, db_session, artifact_factory):
    """Activation is not monotonic — a bad release has to be revertible."""
    old = artifact_factory("1.0.0")
    artifact_factory("2.0.0", active=True)

    client.post(f"/artifacts/{old.id}/activate", headers=bearer(UPLOADER_ID))
    assert active_versions() == ["1.0.0"]


def test_activating_an_unknown_artifact_is_404(client, db_session):
    assert client.post("/artifacts/nope/activate", headers=bearer(UPLOADER_ID)).status_code == 404


def test_deleting_an_artifact_removes_the_row_and_the_object(client, db_session, artifact_factory, fake_s3):
    from models import Artifact

    a = artifact_factory("1.0.0")
    key, artifact_id = a.s3_key, a.id

    resp = client.delete(f"/artifacts/{artifact_id}", headers=bearer(UPLOADER_ID))
    assert resp.status_code == 200
    assert Artifact.query.get(artifact_id) is None
    assert key in fake_s3.deleted


def test_a_failed_s3_delete_leaves_the_row_intact(client, db_session, artifact_factory, fake_s3):
    """Deliberate: dropping the row while the object survives would strand a
    file nobody can find again."""
    from models import Artifact

    a = artifact_factory("1.0.0")
    artifact_id = a.id
    fake_s3.fail_on_delete = True

    resp = client.delete(f"/artifacts/{artifact_id}", headers=bearer(UPLOADER_ID))
    assert resp.status_code == 500
    assert Artifact.query.get(artifact_id) is not None, "the artifact row was orphaned"


def test_deleting_an_unknown_artifact_is_404(client, db_session):
    assert client.delete("/artifacts/nope", headers=bearer(UPLOADER_ID)).status_code == 404


@pytest.mark.defect
def test_the_active_artifact_can_be_deleted(client, db_session, artifact_factory, fake_s3):
    """Deleting the active release leaves the fleet with nothing to install.

    /update/check answers `update_available: false` afterwards, so devices stay
    on whatever they have and no error is raised anywhere. Recorded so the
    behaviour is a decision rather than a surprise.
    """
    a = artifact_factory("1.0.0", active=True)
    resp = client.delete(f"/artifacts/{a.id}", headers=bearer(UPLOADER_ID))
    assert resp.status_code == 200, (
        "deleting the active artifact is now refused — good; update this test"
    )
    body = client.get("/update/check?device_type=jetson&artifact_type=firmware").get_json()
    assert body["update_available"] is False


# --------------------------------------------------------------------------- #
# Device administration
# --------------------------------------------------------------------------- #

@pytest.fixture
def managed_device(db_session):
    from models import Device

    d = Device(device_id="dev-1", device_type="jetson", current_version="1.0.0", status="online")
    db_session.session.add(d)
    db_session.session.commit()
    return d


def test_listing_devices_returns_fleet_state(client, db_session, managed_device):
    body = client.get("/devices", headers=bearer(UPLOADER_ID)).get_json()
    assert body[0]["device_id"] == "dev-1"
    assert body[0]["status"] == "online"


def test_queueing_a_command_returns_its_id(client, db_session, managed_device):
    from models import DeviceCommand

    resp = client.post(
        "/devices/dev-1/command", headers=bearer(UPLOADER_ID), json={"command": "reboot"}
    )
    assert resp.status_code == 200
    assert DeviceCommand.query.get(resp.get_json()["command_id"]).command == "reboot"


def test_a_queued_command_starts_pending(client, db_session, managed_device):
    from models import DeviceCommand

    resp = client.post(
        "/devices/dev-1/command", headers=bearer(UPLOADER_ID), json={"command": "reboot"}
    )
    assert DeviceCommand.query.get(resp.get_json()["command_id"]).status == "pending"


@pytest.mark.parametrize(
    "body",
    [{}, {"command": ""}, {"command": None}, {"command": 123}, {"command": []}],
    ids=["absent", "empty", "null", "int", "list"],
)
def test_queueing_a_command_without_a_usable_one_is_a_400(client, db_session, managed_device, body):
    """This used to index data['command'] directly, so an absent or wrong-typed
    command was a 500."""
    resp = client.post("/devices/dev-1/command", headers=bearer(UPLOADER_ID), json=body)
    assert resp.status_code == 400, f"body {body} returned {resp.status_code}"


def test_a_rejected_command_is_not_queued(client, db_session, managed_device):
    from models import DeviceCommand

    client.post("/devices/dev-1/command", headers=bearer(UPLOADER_ID), json={})
    assert DeviceCommand.query.count() == 0


def test_command_status_can_be_read_back(client, db_session, managed_device):
    created = client.post(
        "/devices/dev-1/command", headers=bearer(UPLOADER_ID), json={"command": "reboot"}
    ).get_json()

    body = client.get(f"/commands/{created['command_id']}", headers=bearer(UPLOADER_ID)).get_json()
    assert body["status"] == "pending"
    assert body["executed_at"] is None


def test_unknown_command_status_is_404(client, db_session):
    assert client.get("/commands/nope", headers=bearer(UPLOADER_ID)).status_code == 404


def test_requesting_a_terminal_sets_the_flag(client, db_session, managed_device):
    from models import Device

    resp = client.post("/devices/dev-1/terminal/start", headers=bearer(UPLOADER_ID))
    assert resp.status_code == 200
    assert Device.query.get("dev-1").terminal_requested is True


def test_requesting_a_terminal_on_an_unknown_device_is_404(client, db_session):
    assert client.post("/devices/nope/terminal/start", headers=bearer(UPLOADER_ID)).status_code == 404


def test_device_logs_are_returned_newest_first(client, db_session, managed_device):
    import datetime

    from models import DeviceLog

    for i, hour in enumerate([1, 3, 2]):
        db_session.session.add(
            DeviceLog(
                device_id="dev-1",
                log_content=f"entry {i}",
                log_type="run_sh",
                created_at=datetime.datetime(2026, 1, 1, hour),
            )
        )
    db_session.session.commit()

    body = client.get("/devices/dev-1/logs", headers=bearer(UPLOADER_ID)).get_json()
    assert [e["content"] for e in body] == ["entry 1", "entry 2", "entry 0"]


def test_device_logs_respect_the_limit(client, db_session, managed_device):
    from models import DeviceLog

    for i in range(10):
        db_session.session.add(
            DeviceLog(device_id="dev-1", log_content=str(i), log_type=f"t{i}")
        )
    db_session.session.commit()

    body = client.get("/devices/dev-1/logs?limit=3", headers=bearer(UPLOADER_ID)).get_json()
    assert len(body) == 3


def test_device_logs_can_filter_by_type(client, db_session, managed_device):
    from models import DeviceLog

    db_session.session.add(DeviceLog(device_id="dev-1", log_content="a", log_type="error"))
    db_session.session.add(DeviceLog(device_id="dev-1", log_content="b", log_type="startup"))
    db_session.session.commit()

    body = client.get("/devices/dev-1/logs?type=error", headers=bearer(UPLOADER_ID)).get_json()
    assert [e["content"] for e in body] == ["a"]


def test_a_non_numeric_limit_does_not_crash(client, db_session, managed_device):
    """`type=int` on request.args.get yields None rather than raising, and
    .limit(None) is valid, so this must be a 200."""
    resp = client.get("/devices/dev-1/logs?limit=abc", headers=bearer(UPLOADER_ID))
    assert resp.status_code == 200
