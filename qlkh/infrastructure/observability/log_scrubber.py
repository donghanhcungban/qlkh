"""Cắt PII khỏi log trước khi ghi hoặc trước khi rời hệ thống tới E5 (giám sát bên ngoài).

Nguồn: QLKH-013 (NFR-006, NFR-007), threat-model T-13, RISK-9, LINDDUN.
Chiến lược: allowlist trường (không phải blocklist) — trường không nằm trong
allowlist bị loại khỏi bản ghi log, kể cả trường lạ chưa từng nghĩ tới.
"""

from __future__ import annotations

import re
from typing import Any

# Trường luôn bị cấm xuất hiện trong log dưới mọi hình thức, kể cả đã "mask".
# Đây là payload xác thực/OTP — không có lý do nghiệp vụ nào cần chúng trong log.
FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "password_confirmation",
        "otp",
        "otp_code",
        "mfa_code",
        "totp",
        "token",
        "access_token",
        "refresh_token",
        "session_cookie",
        "qlkh_session",
        "authorization",
    }
)

# Allowlist trường được phép log nguyên văn (không chứa PII).
ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "event",
        "level",
        "trace_id",
        "span_id",
        "request_id",
        "route",
        "method",
        "status_code",
        "duration_ms",
        "branch_id",
        "user_id",
        "role",
        "release_version",
        "service",
        "environment",
        "timestamp",
        "error_type",
    }
)

# Trường được phép log nhưng PHẢI đi qua mask trước (không log nguyên văn).
MASKABLE_FIELDS: frozenset[str] = frozenset({"phone", "phone_number", "email", "contact"})

# SĐT Việt Nam: 0 + 9-10 chữ số, hoặc +84 + 9-10 chữ số.
_PHONE_VN_RE = re.compile(r"(?:\+84|0)(\d{9,10})")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_phone(value: str) -> str:
    """Giữ 2 số đầu + 2 số cuối, che phần còn lại. '+84987654321' -> '+84*******21'."""

    def _mask_match(m: re.Match[str]) -> str:
        full = m.group(0)
        digits = m.group(1)
        prefix = full[: len(full) - len(digits)]
        if len(digits) <= 4:
            return prefix + "*" * len(digits)
        return prefix + digits[:1] + "*" * (len(digits) - 3) + digits[-2:]

    return _PHONE_VN_RE.sub(_mask_match, value)


def mask_email(value: str) -> str:
    def _mask_match(m: re.Match[str]) -> str:
        local, domain = m.group(0).split("@", 1)
        if len(local) <= 2:
            masked_local = local[0] + "*"
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"

    return _EMAIL_RE.sub(_mask_match, value)


def mask_pii_text(value: str) -> str:
    """Mask SĐT và email xuất hiện tự do trong một chuỗi (message tự do, stack trace...)."""
    return mask_email(mask_phone(value))


class ForbiddenFieldError(ValueError):
    """Raised khi payload log chứa trường bị cấm tuyệt đối (mật khẩu, OTP, token)."""


def scrub_log_record(record: dict[str, Any]) -> dict[str, Any]:
    """Áp allowlist + mask cho một bản ghi log có cấu trúc (dict).

    - Trường trong FORBIDDEN_FIELDS: raise ngay, không log kể cả đã che — lỗi lập
      trình phải lộ ra ở CI/test, không được âm thầm lọc rồi cho qua.
    - Trường trong ALLOWED_FIELDS: giữ nguyên.
    - Trường trong MASKABLE_FIELDS: mask trước khi giữ.
    - Trường khác (không nằm trong allowlist nào): loại bỏ (fail-closed).
    - Giá trị kiểu chuỗi bất kỳ còn lại (vd. "message") cũng được quét mask phòng hờ.
    """
    forbidden_present = FORBIDDEN_FIELDS & record.keys()
    if forbidden_present:
        raise ForbiddenFieldError(
            f"log record chứa trường bị cấm tuyệt đối: {sorted(forbidden_present)}"
        )

    scrubbed: dict[str, Any] = {}
    for key, value in record.items():
        if key in ALLOWED_FIELDS:
            scrubbed[key] = mask_pii_text(value) if isinstance(value, str) else value
        elif key in MASKABLE_FIELDS:
            scrubbed[key] = mask_pii_text(str(value))
        elif key == "message" and isinstance(value, str):
            scrubbed[key] = mask_pii_text(value)
        # else: trường không được allowlist -> loại bỏ, không log.
    return scrubbed


def scrub_for_external_sink(record: dict[str, Any]) -> dict[str, Any]:
    """Cắt PII trước khi log rời hệ thống tới dịch vụ giám sát bên ngoài (E5, TB-7).

    Áp allowlist nghiêm hơn: bỏ luôn user_id/branch_id (định danh nội bộ có thể
    dùng để suy luận danh tính khi kết hợp nguồn khác) — E5 chỉ cần đủ để vận hành.
    """
    base = scrub_log_record(record)
    external_denied = {"user_id"}
    return {k: v for k, v in base.items() if k not in external_denied}
