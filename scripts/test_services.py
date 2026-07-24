"""Smoke tests for PostgreSQL and MinIO services."""
import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db.session import init_db, _make_engine
from db import models
from storage import minio_client


async def test_postgres():
    """Connect, create temp row, verify."""
    await init_db()
    engine = _make_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            models.Base.metadata.tables["users"].insert().values(email="test@test.com")
        )
        user_id = result.inserted_primary_key[0]
        print(f"✅ PostgreSQL: created user id={user_id}")
        await conn.execute(
            models.Base.metadata.tables["users"].delete().where(
                models.Base.metadata.tables["users"].c.id == user_id
            )
        )
    await engine.dispose()
    print("✅ PostgreSQL: cleanup done")


def test_minio():
    """List buckets, verify bucket exists or create."""
    client = minio_client.get_client()
    buckets = client.list_buckets()
    bucket_names = [b.name for b in buckets]
    print(f"✅ MinIO: buckets = {bucket_names}")
    minio_client.ensure_bucket()
    assert client.bucket_exists(config.MINIO_BUCKET), f"Bucket {config.MINIO_BUCKET} not found!"
    print(f"✅ MinIO: bucket '{config.MINIO_BUCKET}' exists")


def test_minio_upload():
    """Upload dummy PDF, verify."""
    client = minio_client.get_client()
    dummy_pdf = b"%PDF-1.4 test content"
    client.put_object(
        config.MINIO_BUCKET,
        "test/dummy.pdf",
        io.BytesIO(dummy_pdf),
        len(dummy_pdf),
        content_type="application/pdf",
    )
    print("✅ MinIO: dummy PDF uploaded")
    obj = client.get_object(config.MINIO_BUCKET, "test/dummy.pdf")
    data = obj.read()
    obj.close()
    assert data == dummy_pdf, "Uploaded data mismatch!"
    print("✅ MinIO: upload verified")
    client.remove_object(config.MINIO_BUCKET, "test/dummy.pdf")
    print("✅ MinIO: cleanup done")


if __name__ == "__main__":
    asyncio.run(test_postgres())
    test_minio()
    test_minio_upload()
    print("\n🎉 All services healthy!")