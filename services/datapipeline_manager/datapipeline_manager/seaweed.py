from __future__ import annotations

from pathlib import Path
from typing import Optional

import boto3
from botocore import UNSIGNED
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from . import config


def s3_client() -> BaseClient:
    client_kwargs = {
        "service_name": "s3",
        "endpoint_url": config.SEAWEED_S3_ENDPOINT,
        "region_name": config.SEAWEED_S3_REGION,
        "verify": config.SEAWEED_S3_VERIFY_SSL,
    }
    client_config = Config(
        s3={"addressing_style": config.SEAWEED_S3_ADDRESSING_STYLE},
        signature_version="s3v4",
    )
    access_key = (config.SEAWEED_S3_ACCESS_KEY or "").strip()
    secret_key = (config.SEAWEED_S3_SECRET_KEY or "").strip()
    if access_key and secret_key:
        client_kwargs["aws_access_key_id"] = access_key
        client_kwargs["aws_secret_access_key"] = secret_key
        client_kwargs["config"] = client_config
    else:
        client_kwargs["config"] = Config(
            s3={"addressing_style": config.SEAWEED_S3_ADDRESSING_STYLE},
            signature_version=UNSIGNED,
        )
    return boto3.client(**client_kwargs)


def bucket_exists(client: BaseClient, bucket_name: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError:
        return False


def normalize_prefix(prefix: Optional[str]) -> str:
    cleaned = (prefix or "").strip()
    cleaned = cleaned.replace("\\", "/").strip("/")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    if not cleaned:
        return ""
    parts = [part for part in cleaned.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError("Invalid folder prefix.")
    return cleaned + "/"


def folder_exists(client: BaseClient, bucket_name: str, prefix: str) -> bool:
    normalized = normalize_prefix(prefix)
    if not normalized:
        return True
    response = client.list_objects_v2(
        Bucket=bucket_name,
        Prefix=normalized,
        MaxKeys=1,
    )
    return bool(response.get("KeyCount", 0))


def upload_file(
    client: BaseClient,
    local_path: str,
    bucket_name: str,
    object_key: str,
) -> None:
    client.upload_file(local_path, bucket_name, object_key)


def file_size_bytes(path: str) -> int:
    return Path(path).stat().st_size
