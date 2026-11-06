"""Storage backends: S3 in Lambda, a local directory for development.

Two independent stores are used, each a (backend, prefix) pair:

- state store: the authoritative dataset, failure log, corrections log, raw
  HTML snapshots, and the publish manifest. Never served to the public.
  S3: s3://BUCKET/state/...      local: ./data/...
- site store: exactly what CloudFront serves.
  S3: s3://BUCKET/site/...       local: ./public/...

CloudFront's origin path is `/site`, so nothing under `state/` is reachable
from the web even though it's the same bucket.
"""

import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)


class LocalStorage:
    def __init__(self, root):
        self.root = Path(root)

    def describe(self, key):
        return str(self.root / key)

    def read_text(self, key):
        path = self.root / key
        return path.read_text(encoding="utf-8") if path.exists() else None

    def write(self, key, body, content_type="application/octet-stream", cache_control=None):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, str):
            body = body.encode("utf-8")
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)  # atomic on POSIX: readers never see half a file

    def exists(self, key):
        return (self.root / key).exists()


class S3Storage:
    def __init__(self, bucket, prefix="", client=None):
        import boto3  # imported lazily so local mode needs no AWS anything
        self.bucket = bucket
        self.prefix = prefix
        self.s3 = client or boto3.client("s3")

    def describe(self, key):
        return f"s3://{self.bucket}/{self.prefix}{key}"

    def read_text(self, key):
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=self.prefix + key)
        except self.s3.exceptions.NoSuchKey:
            return None
        return obj["Body"].read().decode("utf-8")

    def write(self, key, body, content_type="application/octet-stream", cache_control=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        extra = {"CacheControl": cache_control} if cache_control else {}
        self.s3.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=body,
                           ContentType=content_type, **extra)

    def exists(self, key):
        from botocore.exceptions import ClientError
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self.prefix + key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise


def invalidate_cloudfront(distribution_id, paths, client=None):
    import boto3
    cf = client or boto3.client("cloudfront")
    resp = cf.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            "Paths": {"Quantity": len(paths), "Items": paths},
            "CallerReference": f"m4l-{time.time_ns()}",
        },
    )
    return resp["Invalidation"]["Id"]
