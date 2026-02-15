import uuid
import logging
import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from config import Config

logger = logging.getLogger("seaweed-flask")

class S3Service:
    def __init__(self):
        try:
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
                    retries={'max_attempts': 5, 'mode': 'standard'}
                ),
            )
            self.ensure_bucket()
        except Exception as e:
            logger.error(f"Critical error during S3 client initialization: {e}")
            # We don't raise here to allow the app to start and log the error.
            # Subsequent requests will fail with a clearer error message.
            self.s3 = None

    def ensure_bucket(self):
        if not self.s3:
            logger.error("Cannot ensure bucket: S3 client not initialized")
            return

        try:
            self.s3.head_bucket(Bucket=Config.S3_BUCKET)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404' or error_code == 'NoSuchBucket':
                logger.info("Creating bucket %s", Config.S3_BUCKET)
                try:
                    self.s3.create_bucket(Bucket=Config.S3_BUCKET)
                except Exception as create_e:
                    logger.error(f"Failed to create bucket: {create_e}")
            else:
                logger.error(f"Error checking bucket: {e}")
        except Exception as e:
            logger.error(f"Unexpected error connecting to S3 during startup: {e}")

    def build_key(self, user_id: str, filename: str) -> str:
        return f"{user_id}/{uuid.uuid4().hex}_{filename}"

    def build_artifact_key(self, device_type: str, version: str, filename: str) -> str:
        # Structured path: artifacts/<device_type>/<version>/<filename>
        # Sanitize inputs to prevent directory traversal
        device_type = "".join(c for c in device_type if c.isalnum() or c in ('-', '_'))
        version = "".join(c for c in version if c.isalnum() or c in ('.', '-', '_'))
        filename = "".join(c for c in filename if c.isalnum() or c in ('.', '-', '_'))
        return f"artifacts/{device_type}/{version}/{filename}"

    def public_url(self, key: str) -> str:
        return f"{Config.PUBLIC_S3_URL}/{Config.S3_BUCKET}/{key}"

    def generate_presigned_upload(self, user_id, filename, content_type, device_type=None, version=None):
        if not self.s3:
            raise Exception("S3 client not initialized")
        
        # Determine Key
        if device_type and version:
            key = self.build_artifact_key(device_type, version, filename)
        else:
            key = self.build_key(user_id, filename)

        try:
            # Fix for 403 Forbidden due to Host header mismatch when behind Nginx
            # We must sign the request as if it's going to the public endpoint (host: api.robogenic.site)
            # but preserve the path structure that the backend S3 expects (/bucket/key).
            
            # Extract host from PUBLIC_S3_URL
            from urllib.parse import urlparse
            public_url_parsed = urlparse(Config.PUBLIC_S3_URL) # e.g. https://api.robogenic.site/s3
            public_host = f"{public_url_parsed.scheme}://{public_url_parsed.netloc}" # https://api.robogenic.site
            
            # Create a temporary client bound to the public host for signing
            # We disable SSL verify because internal->external loopback might have cert issues, 
            # and we only need the string generation, not actual connection.
            signing_client = boto3.client(
                "s3",
                endpoint_url=public_host,
                aws_access_key_id=Config.AWS_ACCESS_KEY,
                aws_secret_access_key=Config.AWS_SECRET_KEY,
                region_name=Config.AWS_REGION,
                verify=False,
                config=BotoConfig(
                    s3={"addressing_style": "path"},
                    signature_version="s3v4"
                ),
            )

            # Generate URL where Path is /bucket/key (standard boto3 behavior with path addressing)
            # Host will be api.robogenic.site
            upload_url = signing_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": Config.S3_BUCKET,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=900,
            )
            
            # Now, if our public URL has a path prefix (like /s3) that Nginx strips before forwarding,
            # we need to inject it back into the signed URL so the browser hits the right Nginx location.
            # Example: 
            #   Signed URL: https://api.robogenic.site/uploads/key?...
            #   Browser needs: https://api.robogenic.site/s3/uploads/key?...
            #   Nginx strips /s3 -> forwards /uploads/key to s3:8333.
            
            if public_url_parsed.path and public_url_parsed.path != "/":
                # simplistic injection: replace the scheme://netloc with scheme://netloc/path
                # but careful not to double slash
                prefix = public_url_parsed.path.rstrip('/')
                upload_url = upload_url.replace(public_host, f"{public_host}{prefix}", 1)

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
            # Similar fix for download URLs to match Host header
            from urllib.parse import urlparse
            public_url_parsed = urlparse(Config.PUBLIC_S3_URL)
            public_host = f"{public_url_parsed.scheme}://{public_url_parsed.netloc}"

            signing_client = boto3.client(
                "s3",
                endpoint_url=public_host,
                aws_access_key_id=Config.AWS_ACCESS_KEY,
                aws_secret_access_key=Config.AWS_SECRET_KEY,
                region_name=Config.AWS_REGION,
                verify=False,
                config=BotoConfig(
                    s3={"addressing_style": "path"},
                    signature_version="s3v4"
                ),
            )

            url = signing_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": Config.S3_BUCKET, "Key": key},
                ExpiresIn=300,
            )
            
            if public_url_parsed.path and public_url_parsed.path != "/":
                prefix = public_url_parsed.path.rstrip('/')
                url = url.replace(public_host, f"{public_host}{prefix}", 1)
                
            return url
        except Exception as e:
            logger.error(f"Error generating download URL: {e}")
            raise

    def delete_file(self, key):
        if not self.s3:
            raise Exception("S3 client not initialized")
        try:
            self.s3.delete_object(Bucket=Config.S3_BUCKET, Key=key)
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            raise

s3_service = S3Service()
