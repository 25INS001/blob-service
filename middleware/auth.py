from functools import wraps
from flask import request, g, jsonify
import requests
import logging
from config import Config

logger = logging.getLogger("seaweed-flask")

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"error": "Missing Authorization header"}), 401

        # Remote verification
        try:
            resp = requests.get(
                f"{Config.AUTH_SERVICE_URL}/api/token/verify",
                headers={"Authorization": auth_header},
                timeout=5
            )
            
            if resp.status_code != 200:
                logger.warning(f"Auth failed: {resp.status_code} {resp.text}")
                return jsonify({"error": "Unauthorized"}), 401
            
            # Parse user user_id from response
            data = resp.json()
            # TokenController returns: {"isValid": true, "user_id": 123}
            user_id = data.get("user_id")
            if not user_id:
                 return jsonify({"error": "Invalid token payload"}), 401

            g.user_id = str(user_id) # Convert to string for S3 prefixes
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Auth Service unreachable: {e}")
            return jsonify({"error": "Authentication unavailable"}), 503

        return f(*args, **kwargs)
    return decorated
