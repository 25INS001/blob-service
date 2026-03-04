import time
import requests
import argparse
import socketio
import base64
import random
import threading

# A minimal 1x1 black JPEG for testing
BLANK_JPEG = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c (0("- \x1c\x1c)/9/),2946:;\x1f%<B3<948\xff\xdb\x00C\x01\t\t\t\x0c\x0b\x0c\x18\r\r\x188 \x1c 88888888888888888888888888888888888888888888888888\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xc4\x00\x1f\x01\x00\x03\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x11\x00\x02\x01\x02\x04\x04\x03\x04\x07\x05\x04\x04\x00\x01\x02w\x00\x01\x02\x03\x11\x04\x05!1\x06\x12AQ\x07aq\x13"2\x81\x08\x14B\x91\xa1\xb1\xc1\t#3R\xf0\x15br\xd1\n\x16$4\xe1%\xf1\x17\x18\x19\x1a&\'()*56789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xfd\xfcP\x07\xff\xd9'

# Configuration
API_URL = "http://localhost:5000"
SOCKET_URL = "ws://localhost:5000"

sio = socketio.Client()
streaming = False
streaming_thread = None

@sio.event(namespace='/camera')
def connect():
    print("Connected to camera socket")

@sio.event(namespace='/camera')
def disconnect():
    print("Disconnected from camera socket")

def stream_camera(device_id, camera_id):
    global streaming
    print(f"Starting stream for camera {camera_id}...")
    sio.connect(SOCKET_URL, namespaces=['/camera'], socketio_path='/socket.io')
    
    # Needs a slight delay to ensure connect event completes
    time.sleep(0.5)
    sio.emit('join', {'device_id': device_id, 'type': 'device'}, namespace='/camera')
    
    # Stream test pattern frames
    frame_count = 0
    while streaming:
        # Just emit the blank JPEG for now, could be dynamic logic
        # Encode as base64 string
        b64_frame = base64.b64encode(BLANK_JPEG).decode('utf-8')
        sio.emit('frame', {'device_id': device_id, 'data': b64_frame}, namespace='/camera')
        frame_count += 1
        time.sleep(0.1) # 10 FPS
        
    print(f"Stopping stream. Sent {frame_count} frames.")
    sio.disconnect()

def start_polling(device_id, auth_token):
    global streaming, streaming_thread
    
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "device_id": device_id,
        "cameras": [
            {"id": "cam01", "name": "Forward Navigation Camera"},
            {"id": "cam02", "name": "Arm Tracking Camera"}
        ]
    }
    
    print(f"Starting camera poller for device {device_id}...")
    while True:
        try:
            res = requests.post(f"{API_URL}/api/device/camera/poll", json=payload, headers=headers)
            if res.status_code == 200:
                data = res.json()
                cmd = data.get("command")
                
                if cmd and not streaming:
                    print(f"Received command to start camera: {cmd}")
                    streaming = True
                    streaming_thread = threading.Thread(target=stream_camera, args=(device_id, cmd))
                    streaming_thread.daemon = True
                    streaming_thread.start()
                elif not cmd and streaming:
                    print("Command cleared/stopped. Stopping stream...")
                    streaming = False
                    if streaming_thread:
                        streaming_thread.join(timeout=1.0)
            else:
                print(f"Poll failed: {res.status_code} - {res.text}")
                
            time.sleep(2.0)
            
        except requests.exceptions.RequestException as e:
            print(f"Connection error: {e}")
            time.sleep(5.0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True, help="Device ID")
    parser.add_argument("--token", required=True, help="JWT Authentication Token")
    args = parser.parse_args()
    
    start_polling(args.device, args.token)
