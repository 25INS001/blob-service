from functools import wraps
from flask import request, g, jsonify
import os
from models import AllowedUploader

def require_uploader(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Ensure user is authenticated first (g.user_id should be set by require_auth)
        if not hasattr(g, 'user_id') or not g.user_id:
            return jsonify({"error": "Authentication required"}), 401
            
        user_id = int(g.user_id)
        
        # Check if Super Admin (via env var check, assuming auth-service passes email or we check user_id if static)
        # Note: In require_auth we only get user_id. We might need email if SUPER_ADMIN_EMAIL is used.
        # Ideally auth middleware should store g.email too if available.
        # Let's check AllowedUploader table first.
        
        uploader = AllowedUploader.query.filter_by(user_id=user_id).first()
        
        # Fallback: specific ID or check if we can get email from somewhere. 
        # For now, we'll assume the 'added_by' logic handles promotion. 
        # But we need a bootstrap super admin.
        # Let's say User ID 1 is always admin, or use an ENV var for SUPER_ADMIN_ID.
        
        SUPER_ADMIN_ID = os.getenv("SUPER_ADMIN_ID") # e.g. "1"
        
        if (str(user_id) == SUPER_ADMIN_ID) or uploader:
            return f(*args, **kwargs)
            
        return jsonify({"error": "Forbidden: Uploader permission required"}), 403
        
    return decorated

def require_super_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, 'user_id') or not g.user_id:
            return jsonify({"error": "Authentication required"}), 401
            
        SUPER_ADMIN_ID = os.getenv("SUPER_ADMIN_ID")
        if str(g.user_id) == SUPER_ADMIN_ID:
            return f(*args, **kwargs)
            
        return jsonify({"error": "Forbidden: Super Admin required"}), 403
    return decorated
