import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL")
    PUBLIC_S3_URL = os.getenv("PUBLIC_S3_URL", S3_ENDPOINT)
    AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    S3_BUCKET = os.getenv("S3_BUCKET_NAME", "uploads")
    FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))
    AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8080")
    # Database Config
    DB_USER = os.getenv("POSTGRES_USER", "ins001")
    DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "123456")
    DB_HOST = os.getenv("POSTGRES_HOST", "72.60.102.111")
    DB_NAME = os.getenv("POSTGRES_DB", "ins001db")
    SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SUPER_ADMIN_ID = os.getenv("SUPER_ADMIN_ID")
