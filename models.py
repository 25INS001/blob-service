from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import UUID
import uuid

db = SQLAlchemy()

class AllowedUploader(db.Model):
    __tablename__ = 'allowed_uploaders'
    
    user_id = db.Column(db.Integer, primary_key=True) # ID from auth-service
    email = db.Column(db.String(255), nullable=False)
    added_by = db.Column(db.Integer) # Admin ID who added them
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Artifact(db.Model):
    __tablename__ = 'artifacts'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_type = db.Column(db.String(50), nullable=False, index=True)
    artifact_type = db.Column(db.String(50), nullable=False) # model, firmware, script
    version = db.Column(db.String(20), nullable=False)
    s3_key = db.Column(db.String(255), nullable=False)
    checksum = db.Column(db.String(64)) # SHA256
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=False) # Uploader ID

    __table_args__ = (
        db.UniqueConstraint('device_type', 'artifact_type', 'version', name='_artifact_version_uc'),
    )

class Device(db.Model):
    __tablename__ = 'devices'
    
    device_id = db.Column(db.String(255), primary_key=True)
    device_type = db.Column(db.String(50))
    current_version = db.Column(db.String(50))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50)) # online, error, updating

class DeviceCommand(db.Model):
    __tablename__ = 'device_commands'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(db.String(255), db.ForeignKey('devices.device_id'), nullable=False)
    command = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending') # pending, sent, success, failed
    result = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    executed_at = db.Column(db.DateTime)
