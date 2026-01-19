import uuid
import logging
import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from config import Config

logger = logging.getLogger("seaweed-flask")

class S3Service:
    def __init__(self):
        self.s3 = boto3.client(
            "s3",
            endpoint_url=Config.S3_ENDPOINT,
            aws_access_key_id=Config.AWS_ACCESS_KEY,
            aws_secret_access_key=Config.AWS_SECRET_KEY,
            region_name=Config.AWS_REGION,
            verify=False,
            config=BotoConfig(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
            ),
        )
        self.ensure_bucket()

    def ensure_bucket(self):
        try:
            self.s3.head_bucket(Bucket=Config.S3_BUCKET)
        except ClientError:
            logger.info("Creating bucket %s", Config.S3_BUCKET)
            try:
                self.s3.create_bucket(Bucket=Config.S3_BUCKET)
            except Exception as e:
                logger.error(f"Failed to create bucket: {e}")

    def build_key(self, user_id: str, filename: str) -> str:
        return f"{user_id}/{uuid.uuid4().hex}_{filename}"

    def public_url(self, key: str) -> str:
        return f"{Config.PUBLIC_S3_URL}/{Config.S3_BUCKET}/{key}"

    def generate_presigned_upload(self, user_id, filename, content_type):
        key = self.build_key(user_id, filename)
        try:
            upload_url = self.s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": Config.S3_BUCKET,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=900,
            )
            # Ensure public URL host if needed, though for upload internal usually fine if called from outside? 
            # Actually for upload, if client is external (browser), it needs PUBLIC endpoint.
            # But generate_presigned_url uses the endpoint_url configured in boto3 client.
            # If Config.S3_ENDPOINT is internal (http://s3:8333), the browser can't reach it.
            # We MUST replace it with PUBLIC_S3_URL if they differ.
            
            if Config.S3_ENDPOINT and Config.PUBLIC_S3_URL and Config.S3_ENDPOINT in upload_url:
                 upload_url = upload_url.replace(Config.S3_ENDPOINT, Config.PUBLIC_S3_URL)

            return {
                "uploadUrl": upload_url,
                "key": key,
                "fileUrl": self.public_url(key)
            }
        except Exception as e:
            logger.error(f"Error generating presigned upload: {e}")
            raise

    def list_files(self, user_id):
        prefix = f"{user_id}/"
        files = []
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=Config.S3_BUCKET, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    files.append({
                        "key": key,
                        "fileUrl": self.public_url(key),
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat()
                    })
        except Exception as e:
             logger.error(f"Error listing files: {e}")
             raise
        return files

    def generate_presigned_download(self, key):
        try:
            url = self.s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": Config.S3_BUCKET, "Key": key},
                ExpiresIn=300,
            )
            if Config.S3_ENDPOINT and Config.PUBLIC_S3_URL and Config.S3_ENDPOINT in url:
                url = url.replace(Config.S3_ENDPOINT, Config.PUBLIC_S3_URL)
            return url
        except Exception as e:
            logger.error(f"Error generating download URL: {e}")
            raise

    def delete_file(self, key):
        try:
            self.s3.delete_object(Bucket=Config.S3_BUCKET, Key=key)
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            raise

s3_service = S3Service()
