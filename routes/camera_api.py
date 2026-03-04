import logging
from flask import Blueprint, request, jsonify, g
from models import db, Device
from middleware.auth import require_auth

logger = logging.getLogger("seaweed-flask")
camera_api_bp = Blueprint("camera_api", __name__)

@camera_api_bp.route("/api/device/camera/poll", methods=["POST"])
@require_auth
def camera_poll():
    """
    Called periodically by the standalone Camera App on the device
    to report available cameras and retrieve any active user requests.
    """
    data = request.json
    device_id = data.get("device_id")
    cameras = data.get("cameras", [])
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
        
    device = Device.query.get(device_id)
    if not device:
        # Assume device must be registered by the main service heartbeat first
        return jsonify({"error": "Device not found"}), 404
        
    # Update available cameras from the device
    device.available_cameras = cameras
    db.session.commit()
    
    return jsonify({
        "status": "ok",
        "command": device.active_camera_command
    })

@camera_api_bp.route("/api/device/<device_id>/camera/start", methods=["POST"])
@require_auth
def start_camera(device_id):
    """
    Called by the Web UI to request a specific camera feed.
    """
    data = request.json
    camera_id = data.get("camera_id")
    
    if not camera_id:
        return jsonify({"error": "camera_id required"}), 400
        
    device = Device.query.get_or_404(device_id)
    device.active_camera_command = camera_id
    db.session.commit()
    
    return jsonify({"message": f"Camera {camera_id} requested"})

@camera_api_bp.route("/api/device/<device_id>/camera/stop", methods=["POST"])
@require_auth
def stop_camera(device_id):
    """
    Called by the Web UI to stop the active camera feed request.
    """
    device = Device.query.get_or_404(device_id)
    device.active_camera_command = None
    db.session.commit()
    
    return jsonify({"message": "Camera stopped"})
