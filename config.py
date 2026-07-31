import os
from dotenv import load_dotenv

load_dotenv()


def _required(name):
    """Read a required setting, failing loudly rather than falling back to a
    hardcoded default. Credentials must never have in-code defaults."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .sample_env to .env and fill it in, "
            f"or provide it via the environment (see the root .env.example)."
        )
    return value


class Config:
    S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL", "http://s3:8333")
    PUBLIC_S3_URL = os.getenv("PUBLIC_S3_URL", S3_ENDPOINT)
    AWS_ACCESS_KEY = _required("AWS_ACCESS_KEY_ID")
    AWS_SECRET_KEY = _required("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    S3_BUCKET = os.getenv("S3_BUCKET_NAME", "uploads")
    FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() in ("1", "true", "yes")
    AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8080")
    CORS_ALLOWED_ORIGINS = [
        o.strip()
        for o in os.getenv("CORS_ALLOWED_ORIGINS", "https://api.robogenic.site").split(",")
        if o.strip()
    ]

    # Database Config
    DB_USER = _required("POSTGRES_USER")
    DB_PASSWORD = _required("POSTGRES_PASSWORD")
    DB_HOST = _required("POSTGRES_HOST")
    DB_PORT = os.getenv("POSTGRES_PORT", "5432")
    DB_NAME = _required("POSTGRES_DB")
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SUPER_ADMIN_ID = os.getenv("SUPER_ADMIN_ID")
