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
socketio = SocketIO(app, cors_allowed_origins="*")

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
    socketio.run(app, host="0.0.0.0", port=Config.FLASK_PORT, debug=True, allow_unsafe_werkzeug=True)