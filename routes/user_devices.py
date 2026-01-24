from flask import Blueprint, request, jsonify, g
from models import db, Device
from middleware.auth import require_auth
from datetime import datetime

user_devices_bp = Blueprint("user_devices", __name__)

@user_devices_bp.route("/api/user/devices/register", methods=["POST"])
@require_auth
def register_device():
    """
    Registers or updates a device to bind it to the authenticated user.
    """
    data = request.json
    device_id = data.get("device_id")
    friendly_name = data.get("friendly_name")
    
    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    device = Device.query.get(device_id)

    if not device:
        # Create new device if it doesn't exist
        device = Device(device_id=device_id)
        db.session.add(device)
    
    # Check if device is already bound to ANOTHER user
    if device.user_id and device.user_id != g.user_id:
        return jsonify({"error": "Device is already bound to another user"}), 409
    
    # Bind device to user
    device.user_id = g.user_id
    if friendly_name:
        device.friendly_name = friendly_name
    
    # Update other fields if provided (optional, but good for init)
    device.device_type = data.get("device_type", device.device_type)
    device.last_seen = datetime.utcnow() # Mark as seen on registration

    try:
        db.session.commit()
        return jsonify({
            "message": "Device registered successfully",
            "device": {
                "device_id": device.device_id,
                "friendly_name": device.friendly_name,
                "user_id": device.user_id
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@user_devices_bp.route("/api/user/devices", methods=["GET"])
@require_auth
def list_user_devices():
    """
    List all devices bound to the authenticated user.
    """
    devices = Device.query.filter_by(user_id=g.user_id).all()
    
    return jsonify([{
        "device_id": d.device_id,
        "friendly_name": d.friendly_name,
        "type": d.device_type,
        "version": d.current_version,
        "status": d.status,
        "last_seen": d.last_seen.isoformat() if d.last_seen else None
    } for d in devices])

@user_devices_bp.route("/api/user/devices/<device_id>", methods=["DELETE"])
@require_auth
def unbind_device(device_id):
    """
    Unbind a device from the user.
    """
    device = Device.query.filter_by(device_id=device_id, user_id=g.user_id).first()
    
    if not device:
        return jsonify({"error": "Device not found or not bound to user"}), 404
    
    # Unbind instead of delete? Or delete?
    # Requirement: "a device will be bound by one user"
    # Often we just clear the binding so the device record remains (for history/admin)
    # But if it's "register device", maybe user expects it gone.
    # Let's clear the binding for now.
    
    device.user_id = None
    device.friendly_name = None # clear friendly name too?
    
    try:
        db.session.commit()
        return jsonify({"message": "Device unbound successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
