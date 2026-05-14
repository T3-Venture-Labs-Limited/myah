"""Tests for sniff_mime utility."""
from myah.utils.files import sniff_mime


def test_sniff_jpeg():
    jpeg = b'\xff\xd8\xff\xe0\x00\x10JFIF' + b'\x00' * 100
    result = sniff_mime(jpeg)
    assert result == 'image/jpeg'


def test_sniff_png():
    # Minimal valid 1x1 RGB PNG (signature + IHDR + IDAT + IEND)
    # Must be a structurally valid PNG so libmagic can identify it correctly.
    png = (
        b'\x89PNG\r\n\x1a\n'
        b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
        b'\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef'
        b'\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    result = sniff_mime(png)
    assert result == 'image/png'


def test_sniff_pdf():
    pdf = b'%PDF-1.4\n' + b'\x00' * 100
    result = sniff_mime(pdf)
    assert result == 'application/pdf'


def test_sniff_empty_returns_octet_stream():
    result = sniff_mime(b'')
    assert result == 'application/octet-stream'


def test_sniff_unknown_falls_back():
    garbage = b'\x00\x01\x02\x03' * 10
    result = sniff_mime(garbage)
    # libmagic may return various values for random bytes
    assert isinstance(result, str)
    assert len(result) > 0
