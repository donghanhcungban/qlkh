"""Cắt PII khỏi log trước khi ghi hoặc trước khi rời hệ thống tới E5 (giám sát bên ngoài).

Nguồn: QLKH-013 (NFR-006, NFR-007), threat-model T-13, RISK-9, LINDDUN.
Chiến lược: allowlist trường (không phải blocklist) — trường không nằm trong
allowlist bị loại khỏi bản ghi log, kể cả trường lạ chưa từng nghĩ tới.

v2 (retry 1, review findings):
- Phát hiện trường cấm không còn so khớp tên khóa chính xác: chuẩn hóa
  (lowercase, bỏ `.`/`_`/`-`) rồi so khớp theo prefix/suffix, bắt được
  `Authorization`, `password_hash`, `api_token`, `request.headers.authorization`.
- `scrub_for_external_sink` dùng ALLOWLIST RIÊNG, nghiêm hơn allowlist nội bộ —
  không còn kế thừa `branch_id`/`role`/`trace_id`/`request_id` mặc định. Chưa có
  data contract/DPIA chứng minh các định danh liên kết được là tối thiểu cần
  thiết cho E5, nên mặc định loại bỏ hết, chỉ giữ đúng nhóm vận hành thuần
  (không định danh) đã được rà ở đây.
"""

from __future__ import annotations

import re
from typing import Any

# Trường luôn bị cấm xuất hiện trong log dưới mọi hình thức, kể cả đã "mask".
# Đây là payload xác thực/OTP/secret — không có lý do nghiệp vụ nào cần chúng
# trong log. So khớp theo PREFIX/SUFFIX trên tên trường đã chuẩn hóa (không
# phân biệt hoa/thường, không phân biệt dấu nối `_`/`-`/`.`) để bắt được các
# biến thể như `Authorization`, `password_hash`, `api_token`,
# `request.headers.authorization`.
_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "password",
    "currentpassword",
    "newpassword",
    "otp",
    "mfacode",
    "totp",
    "token",
    "accesstoken",
    "refreshtoken",
    "apitoken",
    "apikey",
    "secret",
    "credential",
    "sessioncookie",
    "qlkhsession",
    "authorization",
    "bearer",
)

_FORBIDDEN_SUFFIXES: tuple[str, ...] = (
    "password",
    "passwordhash",
    "token",
    "apikey",
    "secret",
    "authorization",
    "otp",
    "mfacode",
)

# Giữ tập gốc để tương thích ngược cho code/test còn import trực tiếp.
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


def _canonicalize_key(key: str) -> str:
    """Chuẩn hóa tên trường: lowercase, bỏ '_'/'-'/'.' — để so khớp bất kể kiểu viết
    (`password_hash`, `Password-Hash`, `request.headers.authorization`...)."""
    return re.sub(r"[._\-]", "", key).lower()


def _is_forbidden_key(key: str) -> bool:
    canon = _canonicalize_key(key)
    if canon in {_canonicalize_key(f) for f in FORBIDDEN_FIELDS}:
        return True
    # segment cuối của khóa lồng nhau (a.b.authorization -> "authorization")
    last_segment = _canonicalize_key(key.split(".")[-1])
    for prefix in _FORBIDDEN_PREFIXES:
        if canon.startswith(prefix) or last_segment.startswith(prefix):
            return True
    for suffix in _FORBIDDEN_SUFFIXES:
        if canon.endswith(suffix) or last_segment.endswith(suffix):
            return True
    return False


# Allowlist trường được phép log nguyên văn (không chứa PII) — dùng cho log nội bộ.
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

# Allowlist NGHIÊM cho luồng ra E5 (giám sát bên thứ ba, TB-7). Không kế thừa
# ALLOWED_FIELDS: mọi định danh có thể liên kết được (user_id, branch_id, role,
# trace_id, request_id) bị loại theo mặc định cho tới khi có data
# contract/DPIA chứng minh là tối thiểu cần thiết cho nhà cung cấp giám sát.
EXTERNAL_SINK_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "event",
        "level",
        "route",
        "method",
        "status_code",
        "duration_ms",
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
# CCCD/CMND VN: 9 hoặc 12 chữ số liên tiếp (không phải một phần của số dài hơn).
_CCCD_RE = re.compile(r"(?<!\d)(\d{12}|\d{9})(?!\d)")


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


def mask_national_id(value: str) -> str:
    """Che số CCCD/CMND (9 hoặc 12 chữ số liên tiếp) xuất hiện tự do trong chuỗi.

    Best-effort: không thể phân biệt tuyệt đối với các dãy số khác (mã đơn hàng
    dài...); chấp nhận false-positive theo hướng an toàn hơn (che nhiều hơn cần).
    """

    def _mask_match(m: re.Match[str]) -> str:
        digits = m.group(0)
        return digits[:2] + "*" * (len(digits) - 4) + digits[-2:]

    return _CCCD_RE.sub(_mask_match, value)


def mask_pii_text(value: str) -> str:
    """Mask SĐT, email và CCCD/CMND xuất hiện tự do trong một chuỗi (message tự do,
    stack trace...). Không bao che các loại PII khác (họ tên, địa chỉ, ngày sinh
    dạng chữ) — regex không đủ để nhận diện an toàn; xem QLKH-013-a."""
    return mask_national_id(mask_email(mask_phone(value)))


class ForbiddenFieldError(ValueError):
    """Raised khi payload log chứa trường bị cấm tuyệt đối (mật khẩu, OTP, token, secret)."""


def scrub_log_record(record: dict[str, Any]) -> dict[str, Any]:
    """Áp allowlist + mask cho một bản ghi log có cấu trúc (dict).

    - Trường khớp `_is_forbidden_key` (prefix/suffix, đã chuẩn hóa): raise ngay,
      không log kể cả đã che — lỗi lập trình phải lộ ra ở CI/test, không được
      âm thầm lọc rồi cho qua.
    - Trường trong ALLOWED_FIELDS: giữ nguyên (chuỗi vẫn được quét mask phòng hờ).
    - Trường trong MASKABLE_FIELDS: mask trước khi giữ.
    - Trường khác (không nằm trong allowlist nào): loại bỏ (fail-closed).
    - `message` (chuỗi tự do) được quét mask SĐT/email/CCCD nhưng vẫn có thể
      chứa PII dạng chữ (họ tên, địa chỉ) — nợ mở QLKH-013-a, không giải quyết
      hết trong ticket này vì cần schema/message-template ở tầng gọi.
    """
    forbidden_present = [k for k in record if _is_forbidden_key(k)]
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

    Dùng allowlist RIÊNG (`EXTERNAL_SINK_ALLOWED_FIELDS`), nghiêm hơn hẳn log
    nội bộ: mọi định danh có thể liên kết được (user_id, branch_id, role,
    trace_id, request_id) bị loại theo mặc định — chưa có data contract/DPIA
    chứng minh nhà cung cấp E5 cần chúng ở mức tối thiểu.
    """
    forbidden_present = [k for k in record if _is_forbidden_key(k)]
    if forbidden_present:
        raise ForbiddenFieldError(
            f"log record chứa trường bị cấm tuyệt đối: {sorted(forbidden_present)}"
        )

    scrubbed: dict[str, Any] = {}
    for key, value in record.items():
        if key not in EXTERNAL_SINK_ALLOWED_FIELDS and key != "message":
            continue
        if isinstance(value, str):
            scrubbed[key] = mask_pii_text(value)
        else:
            scrubbed[key] = value
    return scrubbed
