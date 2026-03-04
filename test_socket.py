import socketio
import time

sio = socketio.Client(logger=True, engineio_logger=True)

@sio.event(namespace='/camera')
def connect():
    print('===> [TEST SCRIPT] Connected to namespace!')
    sio.emit('join', {'device_id': 'test01', 'type': 'browser'}, namespace='/camera')

@sio.event(namespace='/camera')
def disconnect():
    print('===> [TEST SCRIPT] Disconnected from namespace!')

try:
    print("Connecting...")
    sio.connect('https://api.robogenic.site', namespaces=['/camera'], socketio_path='/socket.io')
    print("Waiting 5 seconds...")
    time.sleep(5)
    sio.disconnect()
except Exception as e:
    print(f"Failed: {e}")
