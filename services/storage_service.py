"""File storage service supporting S3 and Cloudinary."""
import logging
import os
import uuid
from typing import Optional, Tuple
from werkzeug.utils import secure_filename

from flask import current_app
from PIL import Image

logger = logging.getLogger(__name__)


class StorageService:
    """Handle file uploads to local storage, S3, or Cloudinary."""

    @staticmethod
    def allowed_file(filename: str) -> bool:
        """Check if file extension is allowed."""
        if not filename or "." not in filename:
            return False
        ext = filename.rsplit(".", 1)[1].lower()
        return ext in current_app.config.get("ALLOWED_EXTENSIONS", set())

    @staticmethod
    def generate_unique_filename(original_filename: str) -> str:
        """Generate a unique filename while preserving extension."""
        secure_name = secure_filename(original_filename)
        name, ext = os.path.splitext(secure_name)
        unique_name = f"{name}_{uuid.uuid4().hex[:12]}{ext}"
        return unique_name

    @staticmethod
    def validate_image(file_path: str, max_size_mb: int = 5) -> bool:
        """Validate image file."""
        try:
            # Check file size
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb > max_size_mb:
                logger.warning(f"Image too large: {file_size_mb:.2f}MB")
                return False

            # Validate it's actually an image
            img = Image.open(file_path)
            img.verify()

            return True

        except Exception as e:
            logger.error(f"Invalid image file: {e}")
            return False

    @staticmethod
    def process_image(file_path: str, max_width: int = 1920, max_height: int = 1920) -> bool:
        """Resize image and strip EXIF data."""
        try:
            img = Image.open(file_path)

            # Strip EXIF data
            if hasattr(img, 'getexif'):
                img = Image.new(img.mode, img.size)

            # Resize if needed
            if img.width > max_width or img.height > max_height:
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            # Save with optimization
            img.save(file_path, optimize=True, quality=85)
            logger.info(f"Processed image: {file_path}")
            return True

        except Exception as e:
            logger.exception(f"Image processing failed: {e}")
            return False

    @staticmethod
    def save_local(file, subfolder: str = "") -> Optional[str]:
        """Save file to local filesystem."""
        try:
            if not StorageService.allowed_file(file.filename):
                logger.warning(f"File type not allowed: {file.filename}")
                return None

            filename = StorageService.generate_unique_filename(file.filename)
            upload_folder = current_app.config["UPLOAD_FOLDER"]

            if subfolder:
                upload_folder = os.path.join(upload_folder, subfolder)
                os.makedirs(upload_folder, exist_ok=True)

            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)

            # Process images
            if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                if not StorageService.validate_image(file_path):
                    os.remove(file_path)
                    return None
                StorageService.process_image(file_path)

            logger.info(f"File saved locally: {file_path}")
            return os.path.join(subfolder, filename) if subfolder else filename

        except Exception as e:
            logger.exception(f"Local file save failed: {e}")
            return None

    @staticmethod
    def save_to_s3(file, subfolder: str = "") -> Optional[str]:
        """Save file to AWS S3."""
        try:
            import boto3
            from botocore.exceptions import ClientError

            if not StorageService.allowed_file(file.filename):
                return None

            filename = StorageService.generate_unique_filename(file.filename)
            s3_key = f"{subfolder}/{filename}" if subfolder else filename

            s3_client = boto3.client(
                's3',
                aws_access_key_id=current_app.config.get("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=current_app.config.get("AWS_SECRET_ACCESS_KEY"),
                region_name=current_app.config.get("AWS_REGION"),
            )

            bucket = current_app.config.get("AWS_S3_BUCKET")

            s3_client.upload_fileobj(
                file,
                bucket,
                s3_key,
                ExtraArgs={"ContentType": file.content_type}
            )

            # Generate URL
            url = f"https://{bucket}.s3.amazonaws.com/{s3_key}"
            logger.info(f"File uploaded to S3: {url}")
            return url

        except Exception as e:
            logger.exception(f"S3 upload failed: {e}")
            return None

    @staticmethod
    def save_to_cloudinary(file, subfolder: str = "") -> Optional[str]:
        """Save file to Cloudinary."""
        try:
            import cloudinary
            import cloudinary.uploader

            cloudinary.config(
                cloud_name=current_app.config.get("CLOUDINARY_CLOUD_NAME"),
                api_key=current_app.config.get("CLOUDINARY_API_KEY"),
                api_secret=current_app.config.get("CLOUDINARY_API_SECRET"),
            )

            folder = f"abroad/{subfolder}" if subfolder else "abroad"

            result = cloudinary.uploader.upload(
                file,
                folder=folder,
                resource_type="auto",
            )

            url = result.get("secure_url")
            logger.info(f"File uploaded to Cloudinary: {url}")
            return url

        except Exception as e:
            logger.exception(f"Cloudinary upload failed: {e}")
            return None

    @staticmethod
    def save_file(file, subfolder: str = "") -> Optional[str]:
        """
        Save file using configured storage backend.

        Returns:
            File URL or path depending on storage backend
        """
        if current_app.config.get("USE_S3"):
            return StorageService.save_to_s3(file, subfolder)
        elif current_app.config.get("USE_CLOUDINARY"):
            return StorageService.save_to_cloudinary(file, subfolder)
        else:
            return StorageService.save_local(file, subfolder)

    @staticmethod
    def delete_file(file_path: str) -> bool:
        """Delete file from storage."""
        try:
            if current_app.config.get("USE_S3"):
                # Delete from S3
                import boto3
                s3_client = boto3.client('s3')
                bucket = current_app.config.get("AWS_S3_BUCKET")
                s3_client.delete_object(Bucket=bucket, Key=file_path)
                logger.info(f"Deleted from S3: {file_path}")
                return True

            elif current_app.config.get("USE_CLOUDINARY"):
                # Delete from Cloudinary
                import cloudinary
                cloudinary.uploader.destroy(file_path)
                logger.info(f"Deleted from Cloudinary: {file_path}")
                return True

            else:
                # Delete from local filesystem
                full_path = os.path.join(current_app.config["UPLOAD_FOLDER"], file_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
                    logger.info(f"Deleted local file: {full_path}")
                return True

        except Exception as e:
            logger.exception(f"File deletion failed: {e}")
            return False
