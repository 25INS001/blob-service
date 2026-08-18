"""blob-service application entrypoint.

MONKEY-PATCHING MUST COME FIRST. Nothing above these lines may import a module
that touches sockets, threads or time, because eventlet rewrites those at
import; anything already imported keeps the blocking originals and silently
stops cooperating.

Why it is here at all: flask-socketio selects eventlet as its async driver
because eventlet is installed, so the server is a single-threaded event loop.
Without patching, every blocking call stalls that loop rather than yielding to
the next request -- the process handles exactly one request at a time.

That was measurable. A concurrency sweep against /blob/files:

    users=1   p50   280ms
    users=2   p50   335ms
    users=4   p50   664ms
    users=8   p50  1229ms

Latency scaling 1:1 with clients is the signature of full serialisation; a
concurrent server holds roughly flat until it saturates CPU.

psycopg2 needs patching separately. It is a C extension, so eventlet cannot
rewrite it, and monkey_patch() alone would leave every database query blocking
the loop -- fixing the sockets and none of the queries. psycogreen registers a
wait callback that yields while the driver waits on the server.
"""

import eventlet
eventlet.monkey_patch()

from psycogreen.eventlet import patch_psycopg  # noqa: E402
patch_psycopg()

import logging

# Configure logging early to capture startup errors
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from flask import Flask
from flask_socketio import SocketIO
from config import Config
from routes.api import api_bp
from routes.views import views_bp

app = Flask(__name__)
app.config.from_object(Config)
socketio = SocketIO(app, cors_allowed_origins=Config.CORS_ALLOWED_ORIGINS)

from routes.management import management_bp
from routes.device import device_bp
from routes.user_devices import user_devices_bp

# Register Blueprints
app.register_blueprint(api_bp)
app.register_blueprint(views_bp)
app.register_blueprint(management_bp)
app.register_blueprint(device_bp)
app.register_blueprint(user_devices_bp)

# Initialize DB
from models import db
db.init_app(app)

# Register Socket Events
from routes.terminal_socket import register_socket_events
register_socket_events(socketio)

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    # debug must stay off outside local development: the Werkzeug debugger
    # exposes an interactive console that executes arbitrary Python.
    socketio.run(
        app,
        host="0.0.0.0",
        port=Config.FLASK_PORT,
        debug=Config.FLASK_DEBUG,
        allow_unsafe_werkzeug=Config.FLASK_DEBUG,
    )