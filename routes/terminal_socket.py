import logging
from flask import request
from flask_socketio import emit, disconnect, join_room, leave_room
import threading

logger = logging.getLogger("seaweed-flask")

# Track the authoritative device SID for each device_id
# This prevents multiple "cloned" device connections from causing double-echo
active_devices = {}

def register_socket_events(socketio):
    
    @socketio.on('connect', namespace='/terminal')
    def handle_terminal_connect():
        logger.info(f"Terminal Client connected: {request.sid}")

    @socketio.on('disconnect', namespace='/terminal')
    def handle_terminal_disconnect():
        logger.info(f"Terminal Client disconnected: {request.sid}")
        # Cleanup active_devices if it was the authoritative one
        for dev_id, sid in list(active_devices.items()):
            if sid == request.sid:
                del active_devices[dev_id]
                logger.info(f"Authoritative device {dev_id} disconnected")

    @socketio.on('join', namespace='/terminal')
    def handle_join(data):
        device_id = data.get('device_id')
        client_type = data.get('type') # 'browser' or 'device'
        
        if not device_id:
            return
            
        # Separate rooms for browsers and devices to prevent any cross-echo
        if client_type == 'browser':
            room = f"device_{device_id}_browsers"
            join_room(room)
            logger.info(f"Browser {request.sid} joined {room}")
            emit('server_message', {'data': f'Interested in {device_id}. Waiting for device...'}, room=request.sid)
        elif client_type == 'device':
            room = f"device_{device_id}_devices"
            join_room(room)
            active_devices[device_id] = request.sid
            logger.info(f"Device {request.sid} joined {room} as AUTHORITATIVE")
        else:
            # Fallback for old clients
            join_room(f"device_{device_id}")

    @socketio.on('leave', namespace='/terminal')
    def handle_leave(data):
        device_id = data.get('device_id')
        if device_id:
            # Leave all possible rooms
            leave_room(f"device_{device_id}_browsers")
            leave_room(f"device_{device_id}_devices")
            leave_room(f"device_{device_id}")
            logger.info(f"Client {request.sid} left terminal rooms for {device_id}")

    @socketio.on('input', namespace='/terminal')
    def handle_input(data):
        # Browser -> Device
        device_id = data.get('device_id')
        payload = data.get('data')
        
        if device_id:
             # Relay ONLY to devices interested in this ID
             logger.info(f"Input from browser {request.sid} -> device_{device_id}_devices")
             emit('input', payload, room=f"device_{device_id}_devices", include_self=False)
             # Fallback for old clients
             emit('input', payload, room=f"device_{device_id}", include_self=False)

    @socketio.on('output', namespace='/terminal')
    def handle_output(data):
        # Device -> Browser
        device_id = data.get('device_id')
        payload = data.get('data')
        
        if device_id:
            # AUTHORITATIVE CHECK: Only relay if this is the active device SID
            if active_devices.get(device_id) == request.sid:
                logger.info(f"Output from authoritative device {request.sid} -> device_{device_id}_browsers")
                emit('output', payload, room=f"device_{device_id}_browsers", include_self=False)
                # Fallback for old clients
                emit('output', payload, room=f"device_{device_id}", include_self=False)
            else:
                # Ignore output from "ghost" or legacy connections
                logger.warning(f"Ignored output from non-authoritative SID {request.sid} for {device_id}")

    @socketio.on('resize', namespace='/terminal')
    def handle_resize(data):
        device_id = data.get('device_id')
        if device_id:
             emit('resize', data, room=f"device_{device_id}_devices", include_self=False)
             emit('resize', data, room=f"device_{device_id}", include_self=False)
