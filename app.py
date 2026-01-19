from flask import Flask
# from flask_cors import CORS
from config import Config
from routes.api import api_bp
from routes.views import views_bp
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config.from_object(Config)
# CORS(app) # Enable CORS if frontend is separate, but we are serving from same origin

from routes.management import management_bp
from routes.device import device_bp

# Register Blueprints
app.register_blueprint(api_bp)
app.register_blueprint(views_bp)
app.register_blueprint(management_bp)
app.register_blueprint(device_bp)

# Initialize DB
from models import db
db.init_app(app)

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.FLASK_PORT, debug=True)