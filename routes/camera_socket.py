import logging
from flask import request
from flask_socketio import emit, join_room, leave_room
from models import db, Device

logger = logging.getLogger("seaweed-flask")

# Track the authoritative camera streamer device SID for each device_id
active_camera_devices = {}

def register_camera_socket_events(socketio):
    
    @socketio.on('connect', namespace='/camera')
    def handle_camera_connect(auth=None):
        logger.info(f"==> [DEBUG] Camera Socket CONNECT: SID={request.sid}, Auth={auth}")

    @socketio.on('disconnect', namespace='/camera')
    def handle_camera_disconnect():
        logger.info(f"Camera Socket Client disconnected: {request.sid}")
        # Cleanup active_devices if it was the authoritative one
        for dev_id, sid in list(active_camera_devices.items()):
            if sid == request.sid:
                del active_camera_devices[dev_id]
                logger.info(f"Authoritative camera device {dev_id} disconnected")

    @socketio.on('join', namespace='/camera')
    def handle_join(data):
        logger.info(f"==> [DEBUG] Camera Socket JOIN: SID={request.sid}, Data={data}")
        device_id = data.get('device_id')
        client_type = data.get('type') # 'browser' or 'device'
        
        if not device_id:
            logger.error("==> [DEBUG] JOIN Failed: No device_id provided")
            return
            
        if client_type == 'browser':
            room = f"camera_{device_id}_browsers"
            join_room(room)
            logger.info(f"Browser {request.sid} joined {room}")
        elif client_type == 'device':
            room = f"camera_{device_id}_devices"
            join_room(room)
            active_camera_devices[device_id] = request.sid
            logger.info(f"Device {request.sid} joined camera {room} as AUTHORITATIVE")

    @socketio.on('frame', namespace='/camera')
    def handle_frame(data):
        # Device -> Browser
        device_id = data.get('device_id')
        payload = data.get('data') # Usually base64 JPEG
        payload_size = len(payload) if payload else 0
        
        logger.info(f"==> [DEBUG] Camera FRAME received size={payload_size} for {device_id} (SID={request.sid})")
        
        if not device_id:
            logger.error("==> [DEBUG] FRAME Failed: No device_id provided")
            return
            
        
        if device_id:
            expected_sid = active_camera_devices.get(device_id)
            if expected_sid == request.sid:
                emit('frame', payload, room=f"camera_{device_id}_browsers", include_self=False)
            else:
                logger.error(f"==> [DEBUG] FRAME rejected! expected sid: {expected_sid}, actual: {request.sid}")
