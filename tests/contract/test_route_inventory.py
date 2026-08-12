"""Every registered rule, checked against a declaration.

The per-blueprint files assert what each route does. This one asserts what the
route *table* is — so a new endpoint cannot be added without a deliberate
decision about whether it needs a credential, and a blueprint cannot silently
stop being registered.

The auth posture is probed rather than read off a decorator: each rule is called
with no Authorization header, and anything that does not answer 401 is treated
as public and must appear in PUBLIC_RULES.
"""

import pytest

pytestmark = pytest.mark.contract

# Rules reachable without any credential, each with the reason it is exempt.
PUBLIC_RULES = {
    "/": "login redirect target",
    "/login": "the login page itself",
    "/views/artifacts": "server-rendered page; the API calls behind it are authenticated",
    "/views/files": "server-rendered page",
    "/views/devices": "server-rendered page",
    "/views/devices/<device_id>": "server-rendered page",
    "/views/admin": "server-rendered page",
    "/static/<path:filename>": "Flask's own static handler",
    "/update/check": (
        "devices pull firmware before they hold a credential; see "
        "test_device_routes.test_update_check_discloses_a_download_url_to_anyone"
    ),
}

# The full API surface, so a removed blueprint fails loudly.
EXPECTED_RULES = {
    "/presign-upload",
    "/files",
    "/download",
    "/delete",
    "/device/heartbeat",
    "/device/command/<command_id>/result",
    "/update/check",
    "/device/logs",
    "/admin/uploaders",
    "/admin/uploaders/<int:user_id>",
    "/artifacts",
    "/artifacts/<artifact_id>/download",
    "/artifacts/<artifact_id>/activate",
    "/artifacts/<artifact_id>",
    "/devices",
    "/devices/<device_id>/command",
    "/commands/<command_id>",
    "/devices/<device_id>/terminal/start",
    "/devices/<device_id>/logs",
    "/api/user/devices/register",
    "/api/user/devices",
    "/api/user/devices/<device_id>",
}


def api_rules(app):
    """Every registered rule except Flask's static endpoint."""
    return sorted(
        (r for r in app.url_map.iter_rules() if r.endpoint != "static"),
        key=lambda r: (r.rule, sorted(r.methods)),
    )


def test_every_expected_rule_is_registered(app_under_test):
    registered = {r.rule for r in app_under_test.url_map.iter_rules()}
    missing = sorted(EXPECTED_RULES - registered)
    assert not missing, (
        f"these routes are no longer registered: {missing}. A blueprint was "
        "probably dropped from app.py."
    )


def test_no_unexpected_rules_are_registered(app_under_test):
    registered = {
        r.rule for r in app_under_test.url_map.iter_rules() if r.endpoint != "static"
    }
    extra = sorted(registered - EXPECTED_RULES - set(PUBLIC_RULES))
    assert not extra, (
        f"undeclared routes are registered: {extra}. Add them here together "
        "with their intended auth posture."
    )


def test_camera_blueprint_is_not_registered(app_under_test):
    """routes/camera_api.py defines three routes that app.py never registers.

    This is deliberate documentation of dead code, not an endorsement. When the
    blueprint is wired up, this test fails and tests/contract/test_camera_routes.py
    stops skipping.
    """
    registered = {r.rule for r in app_under_test.url_map.iter_rules()}
    assert "/api/device/camera/poll" not in registered, (
        "camera_api_bp is now registered — delete this test; the camera route "
        "tests will start running on their own"
    )


@pytest.mark.parametrize(
    "rule",
    sorted(EXPECTED_RULES - set(PUBLIC_RULES)),
    ids=lambda r: r,
)
def test_api_rules_reject_anonymous_callers(client, app_under_test, db_session, rule):
    """Probe each rule without a credential; 401 is the only acceptable answer.

    Path parameters are filled with values that do not exist, because the check
    must happen before the lookup — a 404 for an anonymous caller would mean the
    route revealed whether a resource exists before asking who is calling.
    """
    concrete = (
        rule.replace("<command_id>", "no-such-command")
        .replace("<artifact_id>", "no-such-artifact")
        .replace("<device_id>", "no-such-device")
        .replace("<int:user_id>", "999999")
    )
    matching = [r for r in app_under_test.url_map.iter_rules() if r.rule == rule]
    methods = sorted({m for r in matching for m in r.methods} - {"HEAD", "OPTIONS"})

    for method in methods:
        resp = client.open(concrete, method=method, json={})
        assert resp.status_code == 401, (
            f"{method} {concrete} answered {resp.status_code} without a credential"
        )


@pytest.mark.parametrize("rule,reason", sorted(PUBLIC_RULES.items()), ids=lambda v: str(v))
def test_public_rules_stay_reachable(client, app_under_test, db_session, rule, reason):
    """The exempt list is not a wish — each entry is confirmed still public, so
    a stale exemption cannot hide a route that has since been locked down."""
    if rule.startswith("/static"):
        pytest.skip("Flask's own static handler")

    concrete = rule.replace("<device_id>", "no-such-device").replace(
        "<path:filename>", "x.css"
    )
    matching = [r for r in app_under_test.url_map.iter_rules() if r.rule == rule]
    if not matching:
        pytest.skip(f"{rule} is not registered in this build")

    methods = sorted({m for r in matching for m in r.methods} - {"HEAD", "OPTIONS"})
    for method in methods:
        resp = client.open(concrete, method=method, json={})
        assert resp.status_code != 401, (
            f"{method} {concrete} is listed public ({reason}) but returned 401 — "
            "remove the exemption"
        )


def test_no_route_answers_500_to_an_anonymous_probe(client, app_under_test, db_session):
    """Authentication must be decided before any body or path parsing."""
    failures = []
    for rule in app_under_test.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        concrete = (
            rule.rule.replace("<command_id>", "x")
            .replace("<artifact_id>", "x")
            .replace("<device_id>", "x")
            .replace("<int:user_id>", "1")
        )
        for method in sorted(set(rule.methods) - {"HEAD", "OPTIONS"}):
            resp = client.open(concrete, method=method, json={})
            if resp.status_code >= 500:
                failures.append(f"{method} {concrete} -> {resp.status_code}")
    assert not failures, "anonymous probes produced server errors:\n  " + "\n  ".join(failures)
