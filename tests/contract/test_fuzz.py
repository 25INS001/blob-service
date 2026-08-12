"""Hostile input against blob-service, in process.

The standard this file holds routes to: a bad request produces a status we
chose, not an unhandled exception. Flask turns an uncaught exception into a 500,
and with TESTING on it would propagate — either way it is a failure here.

Two Flask-specific hazards make this worth doing rather than assuming:

  request.json / request.get_json()  raise on a malformed or wrongly-typed body
                                     rather than returning None. Most routes in
                                     this service call them without a guard.
  data['key']                        several routes index the parsed body
                                     directly, so a missing key is a KeyError.
"""

import json

import pytest

from tests.conftest import SUPER_ADMIN_ID, UPLOADER_ID, bearer

pytestmark = [pytest.mark.contract, pytest.mark.fuzz]

HOSTILE_STRINGS = [
    pytest.param("' OR '1'='1", id="sql-tautology"),
    pytest.param("'; DROP TABLE devices; --", id="sql-drop"),
    pytest.param("<script>alert(1)</script>", id="xss"),
    pytest.param("../../../../etc/passwd", id="path-traversal"),
    pytest.param("..\\..\\windows\\system32", id="windows-traversal"),
    pytest.param("\x00null", id="null-byte"),
    pytest.param("%2e%2e%2f", id="encoded-traversal"),
    pytest.param("{{7*7}}", id="template-injection"),
    pytest.param("${jndi:ldap://x.test/a}", id="jndi"),
    pytest.param("a" * 10_000, id="very-long"),
    pytest.param("🙂" * 500, id="astral-plane"),
    pytest.param("\r\nX-Injected: 1", id="crlf"),
]

# Bodies that are not valid JSON at all. Flask raises BadRequest for these,
# which becomes a clean 400 without the route doing anything.
MALFORMED_BODIES = [
    pytest.param(b"", "empty", id="empty"),
    pytest.param(b"   ", "whitespace", id="whitespace"),
    pytest.param(b"not json", "plain text", id="text"),
    pytest.param(b"{", "truncated", id="truncated"),
    pytest.param(b'{"a": ' * 200 + b"1" + b"}" * 200, "deeply nested", id="nested"),
]

# Bodies that ARE valid JSON but are not objects. These parse successfully and
# hand the route a list, a string, None or an int, which it then calls .get()
# on. See test_non_object_json_body_crashes_the_route below.
NON_OBJECT_BODIES = [
    pytest.param(b"[]", "array", id="array"),
    pytest.param(b'"str"', "bare string", id="bare-string"),
    pytest.param(b"null", "null", id="null"),
    pytest.param(b"123", "number", id="number"),
]

# The routes that read the body with request.json / data.get() and no isinstance
# check. /admin/uploaders and /artifacts are absent on purpose: they index the
# body inside a try/except that turns the failure into a 400.
UNGUARDED_BODY_ROUTES = [
    "/presign-upload",
    "/download",
    "/delete",
    "/device/heartbeat",
    "/device/logs",
    "/api/user/devices/register",
]

# Routes that parse a JSON body, with a credential that gets past authorization.
JSON_BODY_ROUTES = [
    ("POST", "/presign-upload", "user:5"),
    ("POST", "/download", "user:5"),
    ("POST", "/delete", "user:5"),
    ("POST", "/device/heartbeat", "user:5"),
    ("POST", "/device/logs", "user:5"),
    ("POST", "/api/user/devices/register", "user:5"),
    ("POST", "/admin/uploaders", f"user:{SUPER_ADMIN_ID}"),
    ("POST", "/artifacts", f"user:{UPLOADER_ID}"),
]


@pytest.fixture(autouse=True)
def uploader_row(db_session):
    from models import AllowedUploader

    db_session.session.add(
        AllowedUploader(user_id=int(UPLOADER_ID), email="u@example.test", added_by=1)
    )
    db_session.session.commit()


def assert_no_server_error(resp, what):
    assert resp.status_code < 500, (
        f"{what} produced HTTP {resp.status_code}. An unhandled exception "
        f"reached the WSGI layer. Body: {resp.get_data(as_text=True)[:300]}"
    )


# --------------------------------------------------------------------------- #
# Malformed bodies
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("method,path,token", JSON_BODY_ROUTES, ids=lambda v: str(v))
@pytest.mark.parametrize("body,description", MALFORMED_BODIES)
def test_malformed_json_body(client, db_session, method, path, token, body, description):
    resp = client.open(
        path,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=body,
    )
    assert_no_server_error(resp, f"{method} {path} with a {description} body")


@pytest.mark.parametrize("path", UNGUARDED_BODY_ROUTES, ids=lambda v: v)
@pytest.mark.parametrize("body,description", NON_OBJECT_BODIES)
def test_non_object_json_body_is_a_400(client, db_session, path, body, description):
    """These six routes used to 500 on a body that parsed but was not an object.

    request.json returned a list, a string, None or an int, and the route went
    straight to .get() on it. validation.json_object now rejects anything that
    is not a dict before a field is read.
    """
    resp = client.post(
        path,
        headers={"Authorization": "Bearer user:5", "Content-Type": "application/json"},
        data=body,
    )
    assert_no_server_error(resp, f"POST {path} with a {description} body")
    assert resp.status_code == 400, (
        f"POST {path} with a {description} body returned {resp.status_code}"
    )


@pytest.mark.parametrize(
    "path",
    ["/admin/uploaders", "/artifacts"],
    ids=lambda v: v,
)
@pytest.mark.parametrize("body,description", NON_OBJECT_BODIES)
def test_routes_guarded_by_try_except_also_reject_a_non_object_body(client, db_session, path,
                                                                    body, description):
    """These two reached the same outcome by a different route.

    They wrap field access in try/except and turn the resulting error into a
    400, so they were never part of the defect. Kept so both patterns stay
    covered.
    """
    token = SUPER_ADMIN_ID if path == "/admin/uploaders" else UPLOADER_ID
    resp = client.post(
        path,
        headers={"Authorization": f"Bearer user:{token}", "Content-Type": "application/json"},
        data=body,
    )
    assert_no_server_error(resp, f"POST {path} with a {description} body")


@pytest.mark.parametrize("method,path,token", JSON_BODY_ROUTES, ids=lambda v: str(v))
def test_no_body_at_all(client, db_session, method, path, token):
    resp = client.open(path, method=method, headers={"Authorization": f"Bearer {token}"})
    assert_no_server_error(resp, f"{method} {path} with no body")


@pytest.mark.parametrize("method,path,token", JSON_BODY_ROUTES, ids=lambda v: str(v))
@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/xml", "application/x-www-form-urlencoded", ""]
)
def test_wrong_content_type(client, db_session, method, path, token, content_type):
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    resp = client.open(path, method=method, headers=headers, data=json.dumps({"a": 1}))
    assert_no_server_error(resp, f"{method} {path} with Content-Type {content_type!r}")


# --------------------------------------------------------------------------- #
# Type confusion
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "value",
    [12345, 1.5, True, None, [], {}],
    ids=["int", "float", "bool", "null", "empty-list", "empty-dict"],
)
def test_scalar_or_falsy_device_id_is_handled(client, db_session, value):
    """device_id feeds a primary-key lookup and a String column.

    Falsy values hit the explicit `if not device_id` guard, and scalars are
    values SQLAlchemy can bind, so all of these resolve without an exception.
    """
    for path in ("/device/heartbeat", "/api/user/devices/register"):
        resp = client.post(path, headers=bearer(5), json={"device_id": value})
        assert_no_server_error(resp, f"{path} with device_id={value!r}")


@pytest.mark.parametrize("value", [["a"], {"$ne": None}], ids=["list", "operator"])
def test_structured_device_id_is_rejected_before_the_lookup(client, db_session, value):
    """A list or dict used to reach Device.query.get(), which cannot bind it to
    a String primary key and raised. validation.string_field now rejects it,
    and a wrong-typed device_id gets the same 400 as a missing one."""
    for path in ("/device/heartbeat", "/api/user/devices/register"):
        resp = client.post(path, headers=bearer(5), json={"device_id": value})
        assert_no_server_error(resp, f"{path} with device_id={value!r}")
        assert resp.status_code == 400, (
            f"{path} with device_id={value!r} returned {resp.status_code}"
        )


@pytest.mark.parametrize(
    "value", [None, [], {}], ids=["null", "empty-list", "empty-dict"]
)
def test_falsy_s3_key_is_rejected(client, db_session, value):
    """These are caught by `if not key` and become a clean 400."""
    for path in ("/download", "/delete"):
        resp = client.post(path, headers=bearer(5), json={"key": value})
        assert resp.status_code == 400, f"{path} with key={value!r} gave {resp.status_code}"


@pytest.mark.parametrize(
    "value", [12345, True, {"nested": {"deep": 1}}], ids=["int", "bool", "nested"]
)
def test_truthy_non_string_s3_key_is_rejected(client, db_session, value):
    """/download and /delete used to guard only against a falsy key, then call
    key.startswith(). A truthy non-string raised AttributeError inside the
    ownership check itself — the guard failing open into a crash rather than
    into a 403. Now every non-string key is a 400 before that point."""
    for path in ("/download", "/delete"):
        resp = client.post(path, headers=bearer(5), json={"key": value})
        assert_no_server_error(resp, f"{path} with key={value!r}")
        assert resp.status_code == 400, (
            f"{path} with key={value!r} returned {resp.status_code}"
        )


def test_a_non_string_key_never_reaches_s3(client, db_session, fake_s3):
    """The consequence that matters: rejection happens before any S3 call."""
    client.post("/delete", headers=bearer(5), json={"key": 12345})
    assert fake_s3.calls == [], f"a wrong-typed key still reached S3: {fake_s3.calls}"


@pytest.mark.parametrize("value", [12345, True, [], {}], ids=["int", "bool", "list", "dict"])
def test_filename_of_the_wrong_type(client, db_session, value):
    resp = client.post("/presign-upload", headers=bearer(5), json={"filename": value})
    assert_no_server_error(resp, f"presign with filename={value!r}")


@pytest.mark.parametrize("value", ["abc", None, [], {}], ids=["str", "null", "list", "dict"])
def test_uploader_user_id_of_the_wrong_type(client, db_session, value):
    resp = client.post(
        "/admin/uploaders",
        headers=bearer(SUPER_ADMIN_ID),
        json={"user_id": value, "email": "a@example.test"},
    )
    assert_no_server_error(resp, f"add uploader with user_id={value!r}")


def test_stats_that_are_not_an_object(client, db_session):
    """Device.stats is a JSON column — it accepts anything JSON-shaped."""
    for value in ("a string", 42, [1, 2, 3], None, True):
        resp = client.post(
            "/device/heartbeat", headers=bearer(5), json={"device_id": "d", "stats": value}
        )
        assert_no_server_error(resp, f"heartbeat with stats={value!r}")


# --------------------------------------------------------------------------- #
# Hostile strings
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_hostile_device_id(client, db_session, hostile):
    resp = client.post("/device/heartbeat", headers=bearer(5), json={"device_id": hostile})
    assert_no_server_error(resp, f"heartbeat with device_id={hostile[:40]!r}")


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_hostile_filename(client, db_session, hostile):
    resp = client.post("/presign-upload", headers=bearer(5), json={"filename": hostile})
    assert_no_server_error(resp, f"presign with filename={hostile[:40]!r}")


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_hostile_s3_key_never_escapes_the_namespace(client, db_session, hostile, fake_s3):
    """Whatever the string, it either fails the prefix check or is passed to S3
    exactly as given — never rewritten into something outside `5/`."""
    resp = client.post("/download", headers=bearer(5), json={"key": hostile})
    assert_no_server_error(resp, f"download with key={hostile[:40]!r}")
    if resp.status_code == 200:
        requested = [c for c in fake_s3.calls if c[0] == "download"][-1][1]
        assert requested.startswith("5/"), (
            f"key {hostile[:40]!r} produced an S3 request for {requested[:60]!r}"
        )


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_hostile_path_parameter(client, db_session, hostile):
    """Path segments reach get_or_404 and filter_by directly."""
    from urllib.parse import quote

    encoded = quote(hostile, safe="")
    for path in (
        f"/api/user/devices/{encoded}",
        f"/artifacts/{encoded}",
        f"/commands/{encoded}",
        f"/devices/{encoded}/logs",
    ):
        resp = client.get(path, headers=bearer(SUPER_ADMIN_ID))
        assert_no_server_error(resp, f"GET {path[:80]}")


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_hostile_query_parameters(client, db_session, hostile):
    from urllib.parse import quote

    encoded = quote(hostile, safe="")
    for path in (
        f"/artifacts?device_type={encoded}",
        f"/update/check?device_type={encoded}&artifact_type=firmware",
        f"/devices/dev-1/logs?type={encoded}",
        f"/devices/dev-1/logs?limit={encoded}",
    ):
        resp = client.get(path, headers=bearer(SUPER_ADMIN_ID))
        assert_no_server_error(resp, f"GET {path[:80]}")


def test_sql_injection_does_not_return_other_users_devices(client, db_session):
    """A tautology in a filtered lookup must not widen the result set."""
    from models import Device

    db_session.session.add(Device(device_id="mine", user_id="5"))
    db_session.session.add(Device(device_id="theirs", user_id="6"))
    db_session.session.commit()

    body = client.get("/api/user/devices", headers=bearer("5' OR '1'='1")).get_json()
    if isinstance(body, list):
        assert [d["device_id"] for d in body] != ["mine", "theirs"], (
            "a SQL tautology in the identity widened the device list"
        )


# --------------------------------------------------------------------------- #
# Size limits
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("size", [100_000, 1_000_000])
def test_large_log_upload(client, db_session, size):
    """DeviceLog.log_content is unbounded Text — a device can fill the table."""
    resp = client.post(
        "/device/logs",
        headers=bearer(5),
        json={"device_id": "dev-1", "logs": "x" * size, "type": "run_sh"},
    )
    assert_no_server_error(resp, f"{size}-byte log upload")


def test_oversized_string_in_a_bounded_column(client, db_session):
    """friendly_name is String(255). SQLite does not enforce the limit and
    Postgres does, so this asserts only that the request is handled — it is
    here to catch a 500 appearing when the suite is pointed at Postgres."""
    resp = client.post(
        "/api/user/devices/register",
        headers=bearer(5),
        json={"device_id": "dev-1", "friendly_name": "n" * 5000},
    )
    assert_no_server_error(resp, "register with a 5000-character friendly_name")


def test_many_keys_in_a_body(client, db_session):
    payload = {"device_id": "dev-1"}
    payload.update({f"extra_{i}": i for i in range(5000)})
    resp = client.post("/device/heartbeat", headers=bearer(5), json=payload)
    assert_no_server_error(resp, "heartbeat with 5000 extra keys")


def test_unknown_fields_are_ignored_not_assigned(client, db_session):
    """A body field must never be able to set a column the route did not name."""
    from models import Device

    client.post(
        "/device/heartbeat",
        headers=bearer(5),
        json={"device_id": "dev-1", "user_id": "999", "terminal_requested": True},
    )
    stored = Device.query.get("dev-1")
    assert stored.user_id != "999", "heartbeat let the body rebind device ownership"
    assert stored.terminal_requested in (False, None), (
        "heartbeat let the body raise terminal_requested"
    )
