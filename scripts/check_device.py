from app import app
from models import Device

with app.app_context():
    d = Device.query.get('test-device-001')
    if d:
        print(f"Device: {d.device_id}, Owner: {d.user_id}")
    else:
        print("Device not found")
