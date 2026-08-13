"""User-facing device routes, authorised through the group model.

Previously these read `Device.user_id` — one scalar owner per device — and
granted a hardcoded user id 41 an override that skipped ownership entirely.
Both are gone. Authorisation now resolves through `device_authorized_users`, so
a device may be shared with everyone in any group it belongs to, and the
override is the configured `SUPER_ADMIN_ID`, audited on every use.

`devices.user_id` is still written where it was written before. It is legacy
through the cutover — the groups are authoritative — and is dropped in P4 of
DEVICE_PAT_MIGRATION.md.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from device_access import (
    GroupApiError,
    audit_override,
    caller_user_id,
    create_group_with_device,
    detach_device_from_group,
    device_has_any_group,
    device_ids_for_user,
    is_super_admin,
    led_group_ids_for_device,
    user_leads_device,
    user_may_act_on_device,
)
from middleware.auth import require_auth
from models import Device, DeviceCommand, db
from validation import json_object, string_field

user_devices_bp = Blueprint("user_devices", __name__)


def _device_json(device, detailed=False):
    payload = {
        "device_id": device.device_id,
        "friendly_name": device.friendly_name,
        "type": device.device_type,
        "version": device.current_version,
        "status": device.status,
        "last_seen": device.last_seen.isoformat() + "Z" if device.last_seen else None,
    }
    if detailed:
        payload["stats"] = device.stats
        payload["available_cameras"] = device.available_cameras
    return payload


@user_devices_bp.route("/api/user/devices/register", methods=["POST"])
@require_auth
def register_device():
    """Adopt a device, or update one the caller already has access to.

    A device belonging to no group is claimable: a group is created for it with
    the caller as leader. A device already in someone else's group is refused —
    adopting it would otherwise be a way to grant yourself its video feed.
    """
    data = json_object(request)
    if data is None:
        return jsonify({"error": "JSON object body required"}), 400

    device_id = string_field(data, "device_id")
    friendly_name = string_field(data, "friendly_name")

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    caller = caller_user_id()
    if caller is None:
        return jsonify({"error": "Unauthorized"}), 401

    already_grouped = device_has_any_group(device_id)
    if already_grouped and not user_may_act_on_device(device_id):
        return jsonify({"error": "Device is already bound to another group"}), 409

    device = Device.query.get(device_id)
    if not device:
        device = Device(device_id=device_id)
        db.session.add(device)

    if friendly_name:
        device.friendly_name = friendly_name
    device.device_type = data.get("device_type", device.device_type)
    device.last_seen = datetime.utcnow()
    device.user_id = str(caller)  # legacy column, kept in step through cutover

    group_id = None
    try:
        if not already_grouped:
            # Group creation goes through auth-service so its invariants —
            # one leader, membership and attachment in one transaction — are
            # enforced in the one place that owns them.
            group_id = create_group_with_device(
                friendly_name or f"device-{device_id}",
                device_id,
                request.headers.get("Authorization"),
            )
        db.session.commit()
    except GroupApiError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), exc.status
    except Exception as exc:  # noqa: BLE001 — preserved from the original handler
        db.session.rollback()
        return jsonify({"error": str(exc)}), 500

    body = {
        "message": "Device registered successfully",
        "device": {
            "device_id": device.device_id,
            "friendly_name": device.friendly_name,
            "user_id": device.user_id,
        },
    }
    if group_id is not None:
        body["group_id"] = group_id
    return jsonify(body), 200


@user_devices_bp.route("/api/user/devices", methods=["GET"])
@require_auth
def list_user_devices():
    """Every device the caller can see, across all their groups."""
    device_ids = device_ids_for_user()
    if not device_ids:
        return jsonify([])

    devices = Device.query.filter(Device.device_id.in_(device_ids)).all()
    return jsonify([_device_json(d) for d in devices])


@user_devices_bp.route("/api/user/devices/<device_id>", methods=["GET"])
@require_auth
def get_user_device(device_id):
    """Details of one device. Membership is enough; leadership is not required."""
    authorised = user_may_act_on_device(device_id)
    if not authorised and is_super_admin():
        audit_override("read", device_id)
        authorised = True

    device = Device.query.filter_by(device_id=device_id).first()
    # Unauthorised and non-existent are reported identically, so device ids
    # cannot be probed for existence by anyone outside the group.
    if not device or not authorised:
        return jsonify({"error": "Device not found"}), 404

    return jsonify(_device_json(device, detailed=True))


@user_devices_bp.route("/api/user/devices/<device_id>", methods=["DELETE"])
@require_auth
def unbind_device(device_id):
    """Detach a device from the caller's groups. Super admin deletes outright.

    Leadership is required: a member can see a device but cannot take it away
    from everyone else in the group.
    """
    device = Device.query.filter_by(device_id=device_id).first()

    if is_super_admin():
        if not device:
            return jsonify({"error": "Device not found"}), 404
        audit_override("delete", device_id)
        try:
            DeviceCommand.query.filter_by(device_id=device_id).delete()
            db.session.delete(device)
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            return jsonify({"error": str(exc)}), 500
        # Group rows referencing this device are left for the reconciliation
        # query in DEVICE_PAT_MIGRATION.md section 4.1 to surface, rather than
        # deleted from under auth-service by a service that does not own them.
        return jsonify({"message": "Device deleted successfully"}), 200

    if not device or not user_leads_device(device_id):
        # Members and strangers get the same answer as for a missing device.
        return jsonify({"error": "Device not found, or you do not lead it"}), 404

    group_ids = led_group_ids_for_device(device_id)
    auth_header = request.headers.get("Authorization")
    try:
        for group_id in group_ids:
            detach_device_from_group(group_id, device_id, auth_header)
    except GroupApiError as exc:
        return jsonify({"error": str(exc)}), exc.status

    # Only clear the legacy column once the device has left every group the
    # caller leads; it may still be in groups led by someone else.
    if not device_has_any_group(device_id):
        try:
            device.user_id = None
            device.friendly_name = None
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "message": "Device unbound successfully",
            "groups_detached": len(group_ids),
        }
    ), 200
