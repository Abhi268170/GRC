"""S3-compatible object storage (RustFS). Only the standard S3 API is used, so any
S3-compatible backend can replace RustFS by changing environment variables."""

from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings


@lru_cache
def get_s3():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket() -> None:
    s3, bucket = get_s3(), get_settings().s3_bucket
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        s3.create_bucket(Bucket=bucket)


def bucket_ok() -> bool:
    try:
        get_s3().head_bucket(Bucket=get_settings().s3_bucket)
        return True
    except Exception:
        return False


def put_object(key: str, data: bytes, content_type: str) -> None:
    get_s3().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=data, ContentType=content_type)


def get_object(key: str) -> bytes:
    return get_s3().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()


def delete_object(key: str) -> None:
    get_s3().delete_object(Bucket=get_settings().s3_bucket, Key=key)
