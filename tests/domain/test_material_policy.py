"""Test chính sách học liệu — magic bytes, kích thước, TTL (QLKH-010, REQ-007)."""

from __future__ import annotations

import io
import zipfile

from qlkh.domain import material_policy as mp


def _pptx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/presentation.xml", "<p:presentation/>")
        archive.writestr("[Content_Types].xml", "<Types/>")
    return buffer.getvalue()


def _docx_bytes() -> bytes:
    """zip hợp lệ nhưng KHÔNG phải pptx (không có thư mục ppt/)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def test_pdf_that_duoc_nhan_dien():
    assert mp.sniff_mime_type(b"%PDF-1.7\n...") == mp.PDF


def test_png_that_duoc_nhan_dien():
    assert mp.sniff_mime_type(b"\x89PNG\r\n\x1a\n\x00\x00\x00") == mp.PNG


def test_jpeg_that_duoc_nhan_dien():
    assert mp.sniff_mime_type(b"\xff\xd8\xff\xe0\x00\x10JFIF") == mp.JPEG


def test_pptx_that_duoc_nhan_dien():
    assert mp.sniff_mime_type(_pptx_bytes()) == mp.PPTX


def test_html_doi_duoi_thanh_pdf_bi_tu_choi():
    """Gherkin ticket: .pdf đổi đuôi từ .html -> magic bytes không khớp -> None (415)."""
    fake_pdf = b"<html><body>khong phai pdf that</body></html>"
    assert mp.sniff_mime_type(fake_pdf) is None


def test_zip_khong_phai_pptx_bi_tu_choi():
    assert mp.sniff_mime_type(_docx_bytes()) is None


def test_zip_hong_bi_tu_choi_khong_nem_loi():
    assert mp.sniff_mime_type(b"PK\x03\x04\x00\x00broken") is None


def test_object_key_ngau_nhien_va_khong_trung():
    a = mp.generate_object_key()
    b = mp.generate_object_key()
    assert a != b
    assert len(a) >= 32


def test_ttl_mac_dinh_la_max():
    assert mp.clamp_signed_url_ttl() == mp.MAX_SIGNED_URL_TTL_SECONDS


def test_ttl_vuot_tran_bi_ep_ve_max():
    assert mp.clamp_signed_url_ttl(9999) == mp.MAX_SIGNED_URL_TTL_SECONDS


def test_ttl_am_hoac_zero_bi_ep_ve_max():
    assert mp.clamp_signed_url_ttl(0) == mp.MAX_SIGNED_URL_TTL_SECONDS
    assert mp.clamp_signed_url_ttl(-5) == mp.MAX_SIGNED_URL_TTL_SECONDS


def test_ttl_hop_le_duoc_giu_nguyen():
    assert mp.clamp_signed_url_ttl(300) == 300
