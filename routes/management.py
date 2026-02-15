from flask import Blueprint, request, jsonify, g
from models import db, Artifact, AllowedUploader, Device, DeviceCommand, DeviceLog
from middleware.auth import require_auth
from middleware.rbac import require_uploader, require_super_admin
from services.s3_service import s3_service
import uuid
from datetime import datetime

management_bp = Blueprint("management", __name__)

# --- Admin: Manage Uploaders ---

@management_bp.route("/admin/uploaders", methods=["POST"])
@require_auth
@require_super_admin
def add_uploader():
    data = request.json
    try:
        new_uploader = AllowedUploader(
            user_id=data['user_id'],
            email=data['email'],
            added_by=g.user_id
        )
        db.session.add(new_uploader)
        db.session.commit()
        return jsonify({"message": "Uploader added"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

@management_bp.route("/admin/uploaders", methods=["GET"])
@require_auth
@require_super_admin
def list_uploaders():
    uploaders = AllowedUploader.query.all()
    return jsonify([{
        "user_id": u.user_id,
        "email": u.email,
        "added_by": u.added_by
    } for u in uploaders])

@management_bp.route("/admin/uploaders/<int:user_id>", methods=["DELETE"])
@require_auth
@require_super_admin
def remove_uploader(user_id):
    AllowedUploader.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    return jsonify({"message": "Uploader removed"})

# --- Artifact Management ---

@management_bp.route("/artifacts", methods=["POST"])
@require_auth
@require_uploader
def create_artifact():
    # 1. We expect client to have already uploaded file to S3 (via presign) 
    # OR we can handle file upload here. 
    # Design doc said "Artifact Uploads" handled by service. 
    # Let's assume standard presign flow -> upload -> then register metadata.
    
    data = request.json
    try:
        # Check uniqueness constraint: (device_type, artifact_type, version)
        existing = Artifact.query.filter_by(
            device_type=data['device_type'],
            artifact_type=data['artifact_type'],
            version=data['version']
        ).first()

        if existing:
            return jsonify({"error": f"Version {data['version']} already exists"}), 400

        # Auto-Invalidation Logic
        if data.get('is_active', False):
             Artifact.query.filter_by(
                device_type=data['device_type'], 
                artifact_type=data['artifact_type']
            ).update({"is_active": False})

        artifact = Artifact(
            device_type=data['device_type'],
            artifact_type=data['artifact_type'],
            version=data['version'],
            s3_key=data['s3_key'], # Client sends key after upload
            checksum=data.get('checksum'),
            is_active=data.get('is_active', False),
            created_by=g.user_id
        )
        db.session.add(artifact)
        db.session.commit()
        return jsonify({"message": "Artifact registered", "id": artifact.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

@management_bp.route("/artifacts", methods=["GET"])
@require_auth
def list_artifacts():
    # Optional filters
    device_type = request.args.get('device_type')
    query = Artifact.query
    if device_type:
        query = query.filter_by(device_type=device_type)
        
    artifacts = query.order_by(Artifact.created_at.desc()).all()
    return jsonify([{
        "id": a.id,
        "device_type": a.device_type,
        "artifact_type": a.artifact_type,
        "version": a.version,
        "is_active": a.is_active,
        "created_at": a.created_at.isoformat()
    } for a in artifacts])

@management_bp.route("/artifacts/<artifact_id>/activate", methods=["POST"])
@require_auth
@require_uploader
def activate_artifact(artifact_id):
    artifact = Artifact.query.get_or_404(artifact_id)
    
    # Deactivate others of same type/device? Usually yes for "Release" semantics
    # But maybe we want multiple active? Let's assume strict single active version for now.
    Artifact.query.filter_by(
        device_type=artifact.device_type, 
        artifact_type=artifact.artifact_type
    ).update({"is_active": False})
    
    artifact.is_active = True
    db.session.commit()
    return jsonify({"message": f"Version {artifact.version} activated"})

@management_bp.route("/artifacts/<artifact_id>", methods=["DELETE"])
@require_auth
@require_uploader
def delete_artifact(artifact_id):
    artifact = Artifact.query.get_or_404(artifact_id)
    
    try:
        # 1. Delete from S3
        if artifact.s3_key:
            try:
                s3_service.delete_file(artifact.s3_key)
            except Exception as e:
                # Log but proceed with DB deletion? Or fail?
                # User said "delete everything", implying strong consistency or cleanup.
                # If S3 fails, we probably shouldn't delete DB record to avoid stranding files.
                return jsonify({"error": f"Failed to delete from S3: {str(e)}"}), 500
        
        # 2. Delete from DB
        db.session.delete(artifact)
        db.session.commit()
        return jsonify({"message": "Artifact deleted"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# --- Device Management (Commands) ---

@management_bp.route("/devices", methods=["GET"])
@require_auth
@require_uploader
def list_devices():
    devices = Device.query.all()
    return jsonify([{
        "device_id": d.device_id,
        "device_type": d.device_type,
        "current_version": d.current_version,
        "last_seen": d.last_seen.isoformat() + 'Z' if d.last_seen else None,
        "status": d.status
    } for d in devices])

@management_bp.route("/devices/<device_id>/command", methods=["POST"])
@require_auth
@require_uploader
def queue_command(device_id):
    data = request.json
    cmd = DeviceCommand(
        device_id=device_id,
        command=data['command']
    )
    db.session.add(cmd)
    db.session.commit()
    return jsonify({"message": "Command queued", "command_id": cmd.id})

@management_bp.route("/commands/<command_id>", methods=["GET"])
@require_auth
@require_uploader
def get_command_status(command_id):
    cmd = DeviceCommand.query.get_or_404(command_id)
    return jsonify({
        "id": cmd.id,
        "status": cmd.status,
        "result": cmd.result,
        "created_at": cmd.created_at.isoformat(),
        "executed_at": cmd.executed_at.isoformat() if cmd.executed_at else None
    })

import random

@management_bp.route("/devices/<device_id>/terminal/start", methods=["POST"])
@require_auth
@require_uploader
def start_terminal(device_id):
    device = Device.query.get_or_404(device_id)
    
    # Allocate a random port for the reverse tunnel
    # range 40000-50000
    port = random.randint(40000, 50000)
    
    device.terminal_requested = True
    device.terminal_port = port
    db.session.commit()
    
    return jsonify({
        "message": "Terminal requested",
        "port": port,
        "server": "api.robogenic.site",
        "ssh_user": "root" # Container root
    })

@management_bp.route("/devices/<device_id>/logs", methods=["GET"])
@require_auth
@require_uploader
def get_device_logs(device_id):
    limit = request.args.get('limit', 50, type=int)
    log_type = request.args.get('type')
    
    query = DeviceLog.query.filter_by(device_id=device_id)
    if log_type:
        query = query.filter_by(log_type=log_type)
        
    logs = query.order_by(DeviceLog.created_at.desc()).limit(limit).all()
    
    return jsonify([{
        "id": l.id,
        "created_at": l.created_at.isoformat(),
        "type": l.log_type,
        "content": l.log_content
    } for l in logs])
