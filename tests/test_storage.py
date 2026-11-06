"""S3Storage against botocore's Stubber (no network, no credentials)."""
import boto3
import pytest
from botocore.stub import Stubber

from m4l.storage import S3Storage


@pytest.fixture
def s3():
    c = boto3.client("s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(c) as st:
        yield S3Storage("bucket", "state/", client=c), st


def test_missing_key_reads_as_none(s3):
    store, st = s3
    st.add_client_error("get_object", "NoSuchKey", http_status_code=404)
    assert store.read_text("historical-results.json") is None


def test_exists_false_on_404(s3):
    store, st = s3
    st.add_client_error("head_object", "404", http_status_code=404)
    assert store.exists("index.html") is False


def test_access_denied_is_not_swallowed(s3):
    store, st = s3
    st.add_client_error("head_object", "403", http_status_code=403)
    with pytest.raises(Exception):
        store.exists("index.html")


def test_write_sets_prefix_type_and_cache(s3):
    store, st = s3
    st.add_response("put_object", {}, {"Bucket": "bucket", "Key": "state/a.json", "Body": b"{}",
                                       "ContentType": "application/json", "CacheControl": "max-age=1"})
    store.write("a.json", "{}", "application/json", "max-age=1")
