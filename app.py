from flask import Flask
# from flask_cors import CORS
from config import Config
from routes.api import api_bp
from routes.views import views_bp
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
# CORS(app) # Enable CORS if frontend is separate, but we are serving from same origin

# Register Blueprints
app.register_blueprint(api_bp)
app.register_blueprint(views_bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.FLASK_PORT, debug=True)