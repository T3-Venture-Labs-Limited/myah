"""Inline-disposition test for HTML files served by /api/v1/files/{id}/content.

Per artifact-pane-redesign Section 8.1: HTML must be served with
Content-Disposition: inline so it can be loaded directly into an iframe
src (not a Blob URL).
"""
from open_webui.routers.files import _resolve_disposition_for_test


def test_html_inline_branch():
    """The disposition resolver returns inline for HTML content-types and HTML filenames."""
    assert _resolve_disposition_for_test('text/html', 'foo.html', attachment=False) == 'inline'
    assert _resolve_disposition_for_test('application/xhtml+xml', 'foo.xhtml', attachment=False) == 'inline'
    # Filename-only fallback when content-type is unhelpful.
    assert _resolve_disposition_for_test('application/octet-stream', 'foo.html', attachment=False) == 'inline'
    assert _resolve_disposition_for_test('application/octet-stream', 'foo.htm', attachment=False) == 'inline'


def test_pdf_inline_still_works():
    """Regression — PDF inline disposition must still work."""
    assert _resolve_disposition_for_test('application/pdf', 'foo.pdf', attachment=False) == 'inline'
    assert _resolve_disposition_for_test('application/octet-stream', 'foo.pdf', attachment=False) == 'inline'


def test_text_plain_no_attachment():
    """text/plain stays inline (current behavior — no Content-Disposition header set)."""
    assert _resolve_disposition_for_test('text/plain', 'foo.txt', attachment=False) is None


def test_other_kinds_get_attachment():
    """Non-HTML, non-PDF, non-text-plain files use attachment disposition."""
    assert _resolve_disposition_for_test('application/zip', 'archive.zip', attachment=False) == 'attachment'
    assert _resolve_disposition_for_test('image/png', 'pic.png', attachment=False) == 'attachment'


def test_attachment_query_param_overrides_inline():
    """?attachment=true forces attachment disposition even for HTML/PDF."""
    assert _resolve_disposition_for_test('text/html', 'foo.html', attachment=True) == 'attachment'
    assert _resolve_disposition_for_test('application/pdf', 'foo.pdf', attachment=True) == 'attachment'
