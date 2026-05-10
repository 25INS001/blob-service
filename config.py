import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL", "http://seaweed-s3:8333")
    PUBLIC_S3_URL = os.getenv("PUBLIC_S3_URL", S3_ENDPOINT)
    AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    S3_BUCKET = os.getenv("S3_BUCKET_NAME", "uploads")
    FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))
    AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8080")
    PUBLIC_SOCKET_URL = os.getenv("PUBLIC_SOCKET_URL", "ws://localhost:5000")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes", "on")
    # Database Config
    DB_USER = os.getenv("POSTGRES_USER", "phasicon_blob")
    DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
    DB_HOST = os.getenv("POSTGRES_HOST", "postgres")
    DB_NAME = os.getenv("POSTGRES_DB", "phasicon_blob")
    SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SUPER_ADMIN_ID = os.getenv("SUPER_ADMIN_ID")
