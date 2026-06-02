import pytest
from botocore.exceptions import ClientError
from unittest.mock import MagicMock

from open_webui.storage import provider


def _mock_upload_dir(monkeypatch, tmp_path):
    directory = tmp_path / 'uploads'
    directory.mkdir()
    monkeypatch.setattr(provider, 'UPLOAD_DIR', str(directory))
    return directory


def _make_s3_storage(monkeypatch):
    monkeypatch.setattr(provider, 'S3_ENDPOINT_URL', None)
    monkeypatch.setattr(provider, 'S3_REGION_NAME', 'us-east-1')
    monkeypatch.setattr(provider, 'S3_BUCKET_NAME', 'test-bucket')
    monkeypatch.setattr(provider, 'S3_USE_ACCELERATE_ENDPOINT', False)
    monkeypatch.setattr(provider, 'S3_ADDRESSING_STYLE', 'auto')
    monkeypatch.setattr(provider, 'S3_ENABLE_TAGGING', False)
    monkeypatch.setattr(provider, 'S3_KEY_PREFIX', '')
    s3 = provider.S3StorageProvider()
    s3.s3_client = MagicMock()
    return s3


def _client_error(code: str) -> ClientError:
    return ClientError({'Error': {'Code': code, 'Message': code}}, 'operation')


class TestS3GetFileFallback:
    def test_falls_back_on_local_path(self, monkeypatch, tmp_path):
        upload_dir = _mock_upload_dir(monkeypatch, tmp_path)
        s3 = _make_s3_storage(monkeypatch)
        local_path = str(upload_dir / 'file.txt')
        (upload_dir / 'file.txt').write_bytes(b'content')
        assert s3.get_file(local_path) == local_path

    def test_falls_back_on_client_error(self, monkeypatch, tmp_path):
        upload_dir = _mock_upload_dir(monkeypatch, tmp_path)
        s3 = _make_s3_storage(monkeypatch)
        (upload_dir / 'file.txt').write_bytes(b'content')
        s3.s3_client.download_file.side_effect = _client_error('InvalidSignatureException')
        result = s3.get_file('s3://test-bucket/file.txt')
        assert result == str(upload_dir / 'file.txt')

    def test_raises_when_no_local_copy(self, monkeypatch, tmp_path):
        _mock_upload_dir(monkeypatch, tmp_path)
        s3 = _make_s3_storage(monkeypatch)
        s3.s3_client.download_file.side_effect = _client_error('NoSuchKey')
        with pytest.raises(RuntimeError):
            s3.get_file('s3://test-bucket/nonexistent.txt')


class TestS3DeleteFileFallback:
    def test_falls_back_on_local_path(self, monkeypatch, tmp_path):
        upload_dir = _mock_upload_dir(monkeypatch, tmp_path)
        s3 = _make_s3_storage(monkeypatch)
        local_path = str(upload_dir / 'file.txt')
        (upload_dir / 'file.txt').write_bytes(b'content')
        s3.delete_file(local_path)
        assert not (upload_dir / 'file.txt').exists()
