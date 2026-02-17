import logging
from flask import Blueprint, request, jsonify
from models import db, Device, DeviceCommand, Artifact, DeviceLog
from services.s3_service import s3_service
from datetime import datetime
from middleware.auth import require_auth
from config import Config

logger = logging.getLogger("seaweed-flask")

device_bp = Blueprint("device", __name__)

# Note: These endpoints might use a different auth mechanism (e.g., Device Key).
# For now, we'll keep them open but ideally they need protection.

@device_bp.route("/device/heartbeat", methods=["POST"])
@require_auth
def heartbeat():
    data = request.json
    logger.info(f"Received heartbeat from {request.remote_addr}: {data}")
    device_id = data.get("device_id")
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
        
    device = Device.query.get(device_id)
    if not device:
        device = Device(device_id=device_id)
        db.session.add(device)
    
    device.status = data.get("status", "online")
    device.current_version = data.get("version")
    device.device_type = data.get("device_type", "unknown")
    device.stats = data.get("stats")
    device.last_seen = datetime.utcnow()
    
    # Fetch pending commands
    pending_cmds = DeviceCommand.query.filter_by(
        device_id=device_id, 
        status='pending'
    ).all()
    
    commands_data = []
    
    # Check for terminal request
    if device.terminal_requested:
        commands_data.append({
            "id": "web_terminal",
            "action": "start_web_terminal",
            "socket_url": "wss://api.robogenic.site/terminal",
            "device_id": device_id
        })
        
        # Reset the flag so we don't keep sending this command
        device.terminal_requested = False

    for cmd in pending_cmds:
        cmd.status = 'sent'
        commands_data.append({
            "id": cmd.id,
            "command": cmd.command
        })
    
    db.session.commit()
    
    return jsonify({
        "status": "ok", 
        "commands": commands_data
    })

@device_bp.route("/device/command/<command_id>/result", methods=["POST"])
@require_auth
def command_result(command_id):
    data = request.json
    cmd = DeviceCommand.query.get_or_404(command_id)
    
    cmd.status = data.get("status", "failed") # executed, failed
    cmd.result = data.get("result", "")
    cmd.executed_at = datetime.utcnow()
    
    db.session.commit()
    return jsonify({"message": "Result recorded"})

@device_bp.route("/update/check", methods=["GET"])
def check_update():
    device_type = request.args.get("device_type")
    artifact_type = request.args.get("artifact_type")
    current_version = request.args.get("current_version")
    
    if not device_type or not artifact_type:
        return jsonify({"error": "Missing params"}), 400
        
    # Find latest active artifact
    latest = Artifact.query.filter_by(
        device_type=device_type,
        artifact_type=artifact_type,
        is_active=True
    ).order_by(Artifact.created_at.desc()).first()
    
    if not latest:
        return jsonify({"update_available": False})
        
    if latest.version == current_version:
        return jsonify({"update_available": False})
        
    # Generate download URL
    try:
        url = s3_service.generate_presigned_download(latest.s3_key)
        return jsonify({
            "update_available": True,
            "latest_version": latest.version,
            "download_url": url,
            "checksum": latest.checksum,
            "release_date": latest.created_at.isoformat() + 'Z'
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@device_bp.route("/device/logs", methods=["POST"])
@require_auth
def upload_logs():
    data = request.json
    device_id = data.get("device_id")
    content = data.get("logs")
    log_type = data.get("type", "generic") # e.g. run_sh, error

    if not device_id or not content:
        return jsonify({"error": "Missing device_id or logs"}), 400
    
    # Optional: Verify device exists?
    # device = Device.query.get(device_id)
    # if not device: return ...

    # Check for existing log of this type for this device
    log_entry = DeviceLog.query.filter_by(device_id=device_id, log_type=log_type).first()
    
    if log_entry:
        log_entry.log_content = content
        log_entry.created_at = datetime.utcnow()
    else:
        log_entry = DeviceLog(
            device_id=device_id,
            log_content=content,
            log_type=log_type
        )
        db.session.add(log_entry)
        
    db.session.commit()
    
    return jsonify({"message": "Logs updated", "id": log_entry.id})
