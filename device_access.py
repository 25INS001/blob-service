"""Device authorisation, resolved through auth-service's group model.

Two kinds of operation live here, and they are handled differently on purpose:

* **Reads** go straight to the `device_authorized_users` view. All services
  share one database, and the view exists precisely so that "may this user act
  on this device" is answered identically everywhere rather than re-derived per
  service.

* **Writes** — creating a group, attaching a device — are forwarded to
  auth-service's API with the caller's own token. The invariants (exactly one
  leader, membership and device attachment in one transaction) live in
  GroupService, and reimplementing them in Python is exactly the drift the
  shared view was introduced to avoid.

Design: DEVICE_REGISTRATION.md at the repository root.
"""

import logging

import requests
from flask import g
from sqlalchemy import text

from config import Config
from models import db

logger = logging.getLogger("seaweed-flask")

_AUTH_TIMEOUT = 5


# --- caller identity --------------------------------------------------------


def caller_user_id():
    """The authenticated caller's user id as an int, or None.

    `middleware.auth` stores `g.user_id` as a string (it doubles as an S3 key
    prefix), while the view's `user_id` is INTEGER. Comparing the two without
    converting silently matches nothing, so every caller of this module goes
    through here rather than using `g.user_id` directly.
    """
    raw = getattr(g, "user_id", None)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("caller user_id %r is not an integer", raw)
        return None


def is_super_admin(user_id=None):
    """Whether the caller is the configured super admin.

    Replaces the hardcoded `str(g.user_id) == '41'` that previously bypassed
    every ownership check. `SUPER_ADMIN_ID` has existed in config all along and
    was simply never read. Unset means nobody is a super admin, which is the
    correct default.
    """
    configured = Config.SUPER_ADMIN_ID
    if not configured:
        return False
    uid = user_id if user_id is not None else caller_user_id()
    if uid is None:
        return False
    try:
        return uid == int(configured)
    except (TypeError, ValueError):
        logger.error("SUPER_ADMIN_ID %r is not an integer; refusing override", configured)
        return False


def audit_override(action, device_id):
    """Record a super-admin override.

    An override is a deliberate bypass of the group model, so it must never be
    silent — this is the only place ownership can be ignored.
    """
    logger.warning(
        "SUPER-ADMIN OVERRIDE user_id=%s action=%s device_id=%s",
        caller_user_id(),
        action,
        device_id,
    )


# --- reads: the device_authorized_users view --------------------------------


def user_may_act_on_device(device_id, user_id=None):
    """True if the user belongs to any group containing this device."""
    uid = user_id if user_id is not None else caller_user_id()
    if uid is None:
        return False
    row = db.session.execute(
        text(
            "SELECT 1 FROM device_authorized_users "
            "WHERE device_id = :d AND user_id = :u LIMIT 1"
        ),
        {"d": device_id, "u": uid},
    ).first()
    return row is not None


def user_leads_device(device_id, user_id=None):
    """True if the user leads any group containing this device.

    Destructive actions require this, not mere membership.
    """
    uid = user_id if user_id is not None else caller_user_id()
    if uid is None:
        return False
    row = db.session.execute(
        text(
            "SELECT 1 FROM device_authorized_users "
            "WHERE device_id = :d AND user_id = :u AND role = 'leader' LIMIT 1"
        ),
        {"d": device_id, "u": uid},
    ).first()
    return row is not None


def device_ids_for_user(user_id=None):
    """Every device the user can see, across all their groups."""
    uid = user_id if user_id is not None else caller_user_id()
    if uid is None:
        return []
    rows = db.session.execute(
        text(
            "SELECT DISTINCT device_id FROM device_authorized_users "
            "WHERE user_id = :u ORDER BY device_id"
        ),
        {"u": uid},
    ).fetchall()
    return [r[0] for r in rows]


def led_group_ids_for_device(device_id, user_id=None):
    """Groups containing this device that the user leads."""
    uid = user_id if user_id is not None else caller_user_id()
    if uid is None:
        return []
    rows = db.session.execute(
        text(
            "SELECT DISTINCT group_id FROM device_authorized_users "
            "WHERE device_id = :d AND user_id = :u AND role = 'leader'"
        ),
        {"d": device_id, "u": uid},
    ).fetchall()
    return [r[0] for r in rows]


def device_has_any_group(device_id):
    """Whether the device belongs to any group at all.

    A device in no group is unclaimed and may be adopted; a device in someone
    else's group must not be.
    """
    row = db.session.execute(
        text("SELECT 1 FROM device_authorized_users WHERE device_id = :d LIMIT 1"),
        {"d": device_id},
    ).first()
    return row is not None


# --- writes: forwarded to auth-service --------------------------------------


class GroupApiError(Exception):
    """auth-service rejected or could not serve a group mutation."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _auth_call(method, path, auth_header, json_body=None):
    url = f"{Config.AUTH_SERVICE_URL.rstrip('/')}{path}"
    try:
        resp = requests.request(
            method,
            url,
            headers={"Authorization": auth_header},
            json=json_body,
            timeout=_AUTH_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        logger.error("Group API unreachable: %s", exc)
        raise GroupApiError("Group service unavailable", 503) from exc

    if resp.status_code >= 400:
        # Pass auth-service's own status through where it is meaningful —
        # a 403 from there is a 403 here, not a generic 502.
        try:
            message = resp.json().get("error", "Group operation failed")
        except ValueError:
            message = "Group operation failed"
        raise GroupApiError(message, resp.status_code)
    return resp


def create_group_with_device(name, device_id, auth_header):
    """Create a group led by the caller and attach the device to it.

    Used when adopting a device that belongs to no group yet. Returns the new
    group id.
    """
    created = _auth_call("POST", "/api/groups", auth_header, {"name": name})
    group_id = created.json().get("id")
    if group_id is None:
        raise GroupApiError("Group service returned no group id")

    _auth_call(
        "POST",
        f"/api/groups/{group_id}/devices",
        auth_header,
        {"device_id": device_id},
    )
    return group_id


def detach_device_from_group(group_id, device_id, auth_header):
    """Remove a device from one group. Other groups are unaffected."""
    _auth_call("DELETE", f"/api/groups/{group_id}/devices/{device_id}", auth_header)
