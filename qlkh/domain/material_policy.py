"""Chính sách học liệu — magic bytes, kích thước, TTL URL ký (QLKH-010, REQ-007).

Thuần domain: không import ORM/HTTP/SDK object storage. `sniff_mime_type` chỉ
nhìn NỘI DUNG tệp (magic bytes), không bao giờ tin đuôi tệp hay header
`Content-Type` do client gửi (ADR-005) — một `.pdf` giả (đổi đuôi từ
`.html`/`.svg`...) không có magic bytes khớp allowlist sẽ trả None.

Threat refs: RISK-5/ADR-005 (bucket public nhầm), QLKH-T-05 (upload tệp giả
mạo loại). NFR liên quan: kích thước tối đa 25 MiB (api-contract `Material`),
TTL URL ký tối đa 15 phút — ép cứng ở đây, không phụ thuộc cấu hình adapter.
"""

from __future__ import annotations

import io
import secrets
import zipfile

MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25 MiB — khớp `Material.size_bytes` contract
MAX_SIGNED_URL_TTL_SECONDS = 15 * 60  # ADR-005: URL ký luôn <= 15 phút

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

ALLOWED_MIME_TYPES: frozenset[str] = frozenset({PDF, PNG, JPEG, PPTX})

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_ZIP_MAGIC = b"PK\x03\x04"


def sniff_mime_type(content: bytes) -> str | None:
    """Suy MIME hiệu lực từ magic bytes nội dung; None nếu không khớp allowlist.

    Không tin đuôi tệp hay `Content-Type` client gửi. Với định dạng zip-based
    (pptx), kiểm thêm cấu trúc nội bộ (`ppt/`) để không nhận nhầm docx/xlsx —
    chỉ đọc nội dung tệp thật, không suy diễn từ tên.
    """
    if content.startswith(_PDF_MAGIC):
        return PDF
    if content.startswith(_PNG_MAGIC):
        return PNG
    if content.startswith(_JPEG_MAGIC):
        return JPEG
    if content.startswith(_ZIP_MAGIC):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile:
            return None
        if any(name.startswith("ppt/") for name in names):
            return PPTX
        return None
    return None


def generate_object_key() -> str:
    """Tên đối tượng ngẫu nhiên trong bucket riêng tư — không suy ra được từ
    `filename` (ADR-005), tránh đoán/liệt kê object_key."""
    return secrets.token_urlsafe(32)


def clamp_signed_url_ttl(requested_seconds: int | None = None) -> int:
    """TTL URL ký luôn <= MAX_SIGNED_URL_TTL_SECONDS, bất kể adapter/cấu hình
    truyền gì vào — ép ở tầng domain (ADR-005), không phải tuỳ chọn."""
    if requested_seconds is None or requested_seconds > MAX_SIGNED_URL_TTL_SECONDS:
        return MAX_SIGNED_URL_TTL_SECONDS
    if requested_seconds <= 0:
        return MAX_SIGNED_URL_TTL_SECONDS
    return requested_seconds
