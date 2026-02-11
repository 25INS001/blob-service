import requests
import json

# Configuration
BASE_URL = "http://127.0.0.1:5000"
DEVICE_ID = "test-device-stats-001"
TOKEN = "test-token" # Mock token, assuming auth disabled or mockable locally? 
# Wait, auth is required. @require_auth calls Auth Service.
# Since I cannot easily get a valid token without hitting the real Auth Service (which might be hard from here),
# I might need to bypass auth or assume I can't run this easily against the *container* from *outside* unless I have a token.
# However, I am on the same machine.
# Let's try to run a unit test style approach using the flask test client instead, which is easier than full E2E if I don't have a token.
# But the user asked to "update the req body", implying they might want to see it working against the running service.
# Let's try to use the `app` object to create a test client.

from app import app, db
from models import Device

def test_heartbeat_stats():
    with app.app_context():
        # Mocking the require_auth decorator is hard without changing code.
        # But if I run this as a script importing `app`, I can use `test_client`.
        # However, `require_auth` will still fire.
        # I can mock `requests.get` in `middleware.auth` to return a success.
        
        from unittest.mock import patch, MagicMock
        
        with patch('middleware.auth.requests.get') as mock_get:
            # Mock Auth Service response
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"isValid": True, "user_id": "test-user"}
            mock_get.return_value = mock_resp
            
            client = app.test_client()
            
            payload = {
              "device_id": DEVICE_ID,
              "status": "online",
              "version": "1.0.0",
              "device_type": "compute_unit",
              "stats": {
                "cpu": 67.7,
                "memory": {
                  "total": 33509244928,
                  "available": 24588279808,
                  "percent": 26.6,
                  "used": 8920965120
                },
                "swap": {
                  "total": 2147479552,
                  "used": 0,
                  "percent": 0.0
                },
                "gpus": [
                  {
                    "name": "NVIDIA GeForce RTX 3050",
                    "load": 28.0,
                    "memory_used": 1139.0,
                    "memory_total": 6144.0,
                    "temperature": 33.0
                  }
                ]
              }
            }
            
            headers = {"Authorization": "Bearer mock-token"}
            
            print(f"Sending heartbeat for {DEVICE_ID}...")
            resp = client.post("/device/heartbeat", json=payload, headers=headers)
            
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.json}")
            
            if resp.status_code == 200:
                # Verify DB
                device = Device.query.get(DEVICE_ID)
                if device and device.stats:
                    print("SUCCESS: Stats saved to database.")
                    print(f"Saved Stats: {json.dumps(device.stats, indent=2)}")
                else:
                    print("FAILURE: Device not found or stats empty.")
            else:
                print("FAILURE: API returned non-200 status.")

if __name__ == "__main__":
    test_heartbeat_stats()
