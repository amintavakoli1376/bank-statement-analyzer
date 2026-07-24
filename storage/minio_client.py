import io
from minio import Minio
import config

_client = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_SECURE,
        )
    return _client


def ensure_bucket():
    client = get_client()
    if not client.bucket_exists(config.MINIO_BUCKET):
        client.make_bucket(config.MINIO_BUCKET)


def upload_pdf(file_hash: str, file_bytes: bytes, original_name: str):
    client = get_client()
    client.put_object(
        config.MINIO_BUCKET,
        f"{file_hash}/{original_name}",
        io.BytesIO(file_bytes),
        len(file_bytes),
        content_type="application/pdf",
    )
