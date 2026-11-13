"""Comprehensive unit tests for core/storage.py: local and S3 backends,
path resolution, traversal protection, streams, deletions, and presigned URLs."""
import io
import os
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.uploadedfile import SimpleUploadedFile

from core import storage

pytestmark = pytest.mark.django_db


def test_is_s3_enabled_false_by_default(settings):
    settings.AWS_STORAGE_BUCKET_NAME = ""
    assert storage.is_s3_enabled() is False


def test_is_s3_enabled_true_when_bucket_set(settings):
    settings.AWS_STORAGE_BUCKET_NAME = "my-test-bucket"
    assert storage.is_s3_enabled() is True


def test_s3_client_configuration(settings):
    settings.AWS_STORAGE_BUCKET_NAME = "my-test-bucket"
    settings.AWS_S3_REGION_NAME = "eu-west-1"
    settings.AWS_S3_ENDPOINT_URL = "https://s3.custom.endpoint"
    settings.AWS_ACCESS_KEY_ID = "test-key"
    settings.AWS_SECRET_ACCESS_KEY = "test-secret"

    with patch("boto3.client") as mock_boto:
        storage._s3_client()
        mock_boto.assert_called_once_with(
            "s3",
            region_name="eu-west-1",
            endpoint_url="https://s3.custom.endpoint",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
        )


def test_resolve_local_path_empty(settings, tmp_path):
    settings.DATA_DIR = str(tmp_path)
    res = storage._resolve_local_path("")
    assert res == os.path.abspath(str(tmp_path))


def test_resolve_local_path_normal(settings, tmp_path):
    settings.DATA_DIR = str(tmp_path)
    res = storage._resolve_local_path("docs/company_1/test.pdf")
    assert res == os.path.join(str(tmp_path), "docs/company_1/test.pdf")


def test_resolve_local_path_strips_redundant_data_prefix(settings, tmp_path):
    base_dir = tmp_path / "custom_data"
    base_dir.mkdir(parents=True, exist_ok=True)
    settings.DATA_DIR = str(base_dir)
    res = storage._resolve_local_path("custom_data/subfolder/file.txt")
    assert res == os.path.join(str(base_dir), "subfolder/file.txt")


def test_resolve_local_path_traversal_detection(settings, tmp_path):
    base_dir = tmp_path / "sandbox"
    base_dir.mkdir(parents=True, exist_ok=True)
    settings.DATA_DIR = str(base_dir)

    with pytest.raises(SuspiciousFileOperation):
        storage._resolve_local_path("../../../etc/passwd", base_dir=str(base_dir))


def test_save_and_read_bytes_local(settings, tmp_path):
    settings.AWS_STORAGE_BUCKET_NAME = ""
    settings.DATA_DIR = str(tmp_path)

    stored_path = storage.save_bytes("test_dir/hello.txt", b"Hello Storage!", base_dir=str(tmp_path))
    assert os.path.exists(stored_path)
    assert storage.exists("test_dir/hello.txt", base_dir=str(tmp_path)) is True
    assert storage.read_bytes("test_dir/hello.txt", base_dir=str(tmp_path)) == b"Hello Storage!"
    assert storage.object_size("test_dir/hello.txt", base_dir=str(tmp_path)) == len(b"Hello Storage!")

    stream = storage.open_stream("test_dir/hello.txt", base_dir=str(tmp_path))
    try:
        assert stream.read() == b"Hello Storage!"
    finally:
        stream.close()

    storage.delete("test_dir/hello.txt", base_dir=str(tmp_path))
    assert storage.exists("test_dir/hello.txt", base_dir=str(tmp_path)) is False
    assert storage.object_size("test_dir/hello.txt", base_dir=str(tmp_path)) is None


def test_save_uploaded_file_local(settings, tmp_path):
    settings.AWS_STORAGE_BUCKET_NAME = ""
    settings.DATA_DIR = str(tmp_path)

    up_file = SimpleUploadedFile("upload.txt", b"Uploaded content bytes", content_type="text/plain")
    stored = storage.save_uploaded_file("uploads/upload.txt", up_file, base_dir=str(tmp_path))
    assert os.path.exists(stored)
    assert storage.read_bytes(stored) == b"Uploaded content bytes"


def test_storage_s3_operations(settings):
    settings.AWS_STORAGE_BUCKET_NAME = "deskwise-bucket"
    mock_s3 = MagicMock()

    with patch.object(storage, "_s3_client", return_value=mock_s3):
        # save_bytes
        key = storage.save_bytes("/company_1/doc.pdf", b"PDF bytes", content_type="application/pdf")
        assert key == "company_1/doc.pdf"
        mock_s3.put_object.assert_called_once_with(
            Bucket="deskwise-bucket",
            Key="company_1/doc.pdf",
            Body=b"PDF bytes",
            ContentType="application/pdf",
        )

        # exists
        mock_s3.head_object.return_value = {"ContentLength": 100}
        assert storage.exists("company_1/doc.pdf") is True

        from botocore.exceptions import ClientError
        mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "head_object")
        assert storage.exists("company_1/not_found.pdf") is False

        # read_bytes
        mock_body = MagicMock()
        mock_body.read.return_value = b"Remote bytes"
        mock_s3.get_object.return_value = {"Body": mock_body}
        assert storage.read_bytes("company_1/doc.pdf") == b"Remote bytes"

        # open_stream
        stream = storage.open_stream("company_1/doc.pdf")
        assert stream.read() == b"Remote bytes"

        # delete
        storage.delete("company_1/doc.pdf")
        mock_s3.delete_object.assert_called_once_with(Bucket="deskwise-bucket", Key="company_1/doc.pdf")


def test_generate_presigned_put(settings):
    settings.AWS_STORAGE_BUCKET_NAME = "deskwise-bucket"
    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = "https://s3.amazonaws.com/deskwise-bucket/presigned"

    with patch.object(storage, "_s3_client", return_value=mock_s3):
        url = storage.generate_presigned_put("uploads/bigfile.bin", content_type="application/pdf", size=5000000)
        assert "presigned" in url
        mock_s3.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={"Bucket": "deskwise-bucket", "Key": "uploads/bigfile.bin", "ContentType": "application/pdf", "ContentLength": 5000000},
            ExpiresIn=900,
        )


def test_generate_presigned_put_disabled_when_no_s3(settings):
    settings.AWS_STORAGE_BUCKET_NAME = ""
    assert storage.generate_presigned_put("uploads/bigfile.bin") is None
