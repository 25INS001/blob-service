from flask import Blueprint, request, jsonify, g
from models import db, Device, DeviceCommand
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
        "last_seen": d.last_seen.isoformat() + 'Z' if d.last_seen else None
    } for d in devices])

@user_devices_bp.route("/api/user/devices/<device_id>", methods=["DELETE"])
@require_auth
def unbind_device(device_id):
    """
    Unbind a device from the user. Admin can delete it entirely.
    """
    is_admin = (str(g.user_id) == '41')
    
    if is_admin: # Admin override
        device = Device.query.filter_by(device_id=device_id).first()
    else:
        device = Device.query.filter_by(device_id=device_id, user_id=g.user_id).first()
    
    if not device:
        return jsonify({"error": "Device not found or not bound to user"}), 404
    
    try:
        if is_admin:
            # Full Delete
            DeviceCommand.query.filter_by(device_id=device_id).delete()
            db.session.delete(device)
            msg = "Device deleted successfully"
        else:
            # Unbind
            device.user_id = None
            device.friendly_name = None
            msg = "Device unbound successfully"
            
        db.session.commit()
        return jsonify({"message": msg}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@user_devices_bp.route("/api/user/devices/<device_id>", methods=["GET"])
@require_auth
def get_user_device(device_id):
    """
    Get details of a specific device bound to the authenticated user.
    """
    device = Device.query.filter_by(device_id=device_id).first()
    
    if not device:
        return jsonify({"error": "Device not found"}), 404
        
    # Check ownership (unless admin, but for now strict user binding)
    if device.user_id != g.user_id and str(g.user_id) != '41':
        return jsonify({"error": "Unauthorized"}), 403
    
    return jsonify({
        "device_id": device.device_id,
        "friendly_name": device.friendly_name,
        "type": device.device_type,
        "version": device.current_version,
        "status": device.status,
        "last_seen": device.last_seen.isoformat() + 'Z' if device.last_seen else None,
        "stats": device.stats
    })


