from flask import Blueprint, request, jsonify, g
from services.s3_service import s3_service
from middleware.auth import require_auth
import logging

api_bp = Blueprint("api", __name__)
logger = logging.getLogger("seaweed-flask")

@api_bp.route("/presign-upload", methods=["POST"])
@require_auth
def presign_upload():
    data = request.get_json(force=True)
    filename = data.get("filename")
    content_type = data.get("content_type", "application/octet-stream")
    
    # Optional metadata for artifacts (vs raw files)
    device_type = data.get("device_type")
    version = data.get("version")
    artifact_type = data.get("artifact_type")

    if not filename:
        return {"error": "filename required"}, 400

    # Use authenticated user_id
    try:
        if device_type and version:
            # Structured artifact upload
            result = s3_service.generate_presigned_upload(
                g.user_id, 
                filename, 
                content_type, 
                device_type=device_type, 
                version=version
            )
        else:
            # Raw file upload (backward compatibility)
            result = s3_service.generate_presigned_upload(g.user_id, filename, content_type)
            
        return result
    except Exception as e:
        return {"error": str(e)}, 500

@api_bp.route("/files")
@require_auth
def list_files():
    # Ignore query param, use auth user
    try:
        files = s3_service.list_files(g.user_id)
        return {
            "count": len(files),
            "files": files
        }
    except Exception as e:
        return {"error": str(e)}, 500

@api_bp.route("/download", methods=["POST"])
@require_auth
def download():
    key = request.json.get("key")
    if not key:
        return {"error": "key required"}, 400
    
    # Ownership check: key must start with user_id/
    if not key.startswith(f"{g.user_id}/"):
         return {"error": "Forbidden: You do not own this file"}, 403

    try:
        url = s3_service.generate_presigned_download(key)
        return {"downloadUrl": url}
    except Exception as e:
        return {"error": str(e)}, 500

@api_bp.route("/delete", methods=["POST", "DELETE"])
@require_auth
def delete_file():
    key = request.json.get("key")
    if not key:
        return {"error": "key required"}, 400
    
    # Ownership check
    if not key.startswith(f"{g.user_id}/"):
         return {"error": "Forbidden"}, 403

    try:
        s3_service.delete_file(key)
        return {"message": "Deleted"}
    except Exception as e:
        return {"error": str(e)}, 500
