import os
import uuid
import sqlite3
import logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

load_dotenv()

S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL")
PUBLIC_S3_URL = os.getenv("PUBLIC_S3_URL", S3_ENDPOINT)

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

S3_BUCKET = os.getenv("S3_BUCKET_NAME", "uploads")
FLASK_PORT = int(os.getenv("FLASK_PORT", 5000))

DB_PATH = "files.db"

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seaweed-flask")

s3_client = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION,
    verify=False,
    config=Config(
        s3={"addressing_style": "path"},
        signature_version="s3v4",
    ),
)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            bucket TEXT NOT NULL,
            s3_key TEXT NOT NULL UNIQUE,
            original_name TEXT NOT NULL,
            content_type TEXT,
            size INTEGER,
            public_url TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def ensure_bucket():
    try:
        s3_client.head_bucket(Bucket=S3_BUCKET)
        logger.info("Bucket exists: %s", S3_BUCKET)
    except ClientError:
        s3_client.create_bucket(Bucket=S3_BUCKET)
        logger.info("Bucket created: %s", S3_BUCKET)

ensure_bucket()

@app.route("/upload", methods=["POST"])
def upload_file():
    user_id = request.form.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    if "file" not in request.files:
        return jsonify({"error": "file required"}), 400

    file = request.files["file"]
    key = f"{user_id}/{uuid.uuid4().hex}_{file.filename}"
    public_url = f"{PUBLIC_S3_URL}/{S3_BUCKET}/{key}"

    try:
        file.stream.seek(0)
        s3_client.upload_fileobj(
            Fileobj=file.stream,
            Bucket=S3_BUCKET,
            Key=key,
            ExtraArgs={"ContentType": file.mimetype or "application/octet-stream"},
        )

        conn = get_db()
        conn.execute("""
            INSERT INTO files (user_id, bucket, s3_key, original_name, content_type, size, public_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            S3_BUCKET,
            key,
            file.filename,
            file.mimetype,
            request.content_length,
            public_url
        ))
        conn.commit()
        conn.close()

        return jsonify({
            "message": "Uploaded",
            "key": key,
            "fileUrl": public_url
        }), 201

    except Exception as e:
        logger.exception("Upload failed")
        return jsonify({"error": str(e)}), 500

@app.route("/files", methods=["GET"])
def list_files():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    conn = get_db()
    rows = conn.execute("""
        SELECT id, original_name, public_url, created_at
        FROM files
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,)).fetchall()
    conn.close()

    return jsonify({
        "count": len(rows),
        "files": [dict(row) for row in rows]
    })

@app.route("/download", methods=["POST"])
def download():
    key = request.json.get("key")
    if not key:
        return jsonify({"error": "key required"}), 400

    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=300,
    )
    return jsonify({"downloadUrl": url})

@app.route("/delete", methods=["POST"])
def delete_file():
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    key = data.get("key")

    if not user_id or not key:
        return jsonify({"error": "user_id and key required"}), 400

    conn = get_db()
    row = conn.execute("""
        SELECT id FROM files WHERE user_id = ? AND s3_key = ?
    """, (user_id, key)).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "File not found"}), 404

    try:
        s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
        conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
        conn.commit()
        conn.close()

        return jsonify({"message": "Deleted", "key": key})

    except Exception as e:
        logger.exception("Delete failed")
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return {
        "status": "ok",
        "bucket": S3_BUCKET,
        "endpoint": S3_ENDPOINT
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=True)
