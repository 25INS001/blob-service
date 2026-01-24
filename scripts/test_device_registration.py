import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Add parent dir
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Device

class TestDeviceRegistration(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:' # Use in-memory DB for test?
        # Actually better to use the real DB if we can, but testing logic is safer with isolation.
        # However, since we define specific routes, let's mock the DB session or just usage.
        # Given complexity of mocking DB in existing app, let's try to simple mock auth.
        
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        
        # We will use the REAL DB but inside a transaction? 
        # Or just rely on cleanups.
        
    def tearDown(self):
        self.app_context.pop()

    @patch('middleware.auth.requests.get')
    def test_register_device(self, mock_get):
        # Mock Auth Response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"isValid": True, "user_id": 999}
        mock_get.return_value = mock_response

        # payload
        payload = {
            "device_id": "test-device-001",
            "friendly_name": "My Test Device",
            "device_type": "sensor-x"
        }
        
        # Clean up possible previous run
        prior = Device.query.get("test-device-001")
        if prior:
            db.session.delete(prior)
            db.session.commit()

        # 1. Register new device
        resp = self.app.post('/api/user/devices/register', 
                             json=payload,
                             headers={"Authorization": "Bearer fake-token"})
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json
        self.assertEqual(data['device']['user_id'], '999')
        
        # Verify DB
        dev = Device.query.get("test-device-001")
        self.assertIsNotNone(dev)
        self.assertEqual(dev.user_id, '999')
        self.assertEqual(dev.friendly_name, "My Test Device")

    @patch('middleware.auth.requests.get')
    def test_register_already_bound(self, mock_get):
        # Setup: Device bound to user 888
        dev = Device(device_id="bound-device-001", user_id="888")
        db.session.add(dev)
        try:
            db.session.commit()
        except:
            db.session.rollback()
            
        # Mock Auth as user 999
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"isValid": True, "user_id": 999}
        mock_get.return_value = mock_response

        payload = {
            "device_id": "bound-device-001"
        }
        
        resp = self.app.post('/api/user/devices/register', 
                             json=payload,
                             headers={"Authorization": "Bearer fake-token"})
        
        self.assertEqual(resp.status_code, 409)
        self.assertIn("already bound", resp.json['error'])

        # Cleanup
        db.session.delete(dev)
        db.session.commit()

    @patch('middleware.auth.requests.get')
    def test_list_and_unbind(self, mock_get):
        # Mock Auth as user 777
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"isValid": True, "user_id": 777}
        mock_get.return_value = mock_response
        
        # Setup device
        dev = Device(device_id="my-device-777", user_id="777", friendly_name="Living Room")
        db.session.add(dev)
        db.session.commit()
        
        # List
        resp = self.app.get('/api/user/devices', headers={"Authorization": "Bearer fake"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json), 1)
        self.assertEqual(resp.json[0]['device_id'], "my-device-777")
        
        # Unbind
        resp = self.app.delete('/api/user/devices/my-device-777', headers={"Authorization": "Bearer fake"})
        self.assertEqual(resp.status_code, 200)
        
        # Verify unbind
        dev = Device.query.get("my-device-777")
        self.assertIsNone(dev.user_id)
        
        # Cleanup
        db.session.delete(dev)
        db.session.commit()

if __name__ == '__main__':
    unittest.main()
