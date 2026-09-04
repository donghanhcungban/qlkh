"""Domain xác thực QLKH (QLKH-004, REQ-001, NFR-002, ADR-002).

Thuần domain: không import ORM/HTTP/framework (fitness function kiểm bằng AST).

Nguyên tắc:
- Thông điệp lỗi đăng nhập ĐỒNG NHẤT cho mọi nguyên nhân (không tồn tại, sai
  mật khẩu, tài khoản bị vô hiệu hóa, thiếu/sai MFA) — chống liệt kê tài khoản
  (threat QLKH-T-04).
- Khóa tạm 15 phút sau 5 lần sai trong 15 phút, tính theo tài khoản VÀ theo IP.
- Phiên máy chủ: thu hồi tức thì khi tài khoản bị vô hiệu hóa (QLKH-T-03).
- MFA bắt buộc cho vai trò admin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

Role = Literal["parent", "teacher", "staff", "admin"]

# Chính sách khóa tạm (NFR-002)
MAX_FAILED_ATTEMPTS = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT_DURATION = timedelta(minutes=15)

# Vòng đời phiên máy chủ
SESSION_TTL = timedelta(hours=12)

# Vai trò bắt buộc MFA
MFA_REQUIRED_ROLES: frozenset[str] = frozenset({"admin"})

# Problem Details (RFC 9457) — dùng CHUNG cho mọi lỗi đăng nhập
INVALID_CREDENTIALS_PROBLEM: dict[str, object] = {
    "type": "https://qlkh/errors/unauthorized",
    "title": "Unauthorized",
    "status": 401,
    "detail": "Email hoặc mật khẩu không đúng.",
}
LOCKED_PROBLEM: dict[str, object] = {
    "type": "https://qlkh/errors/too-many-requests",
    "title": "Too Many Requests",
    "status": 429,
    "detail": "Quá nhiều lần đăng nhập sai. Thử lại sau ít phút.",
}


class AuthError(Exception):
    """Lỗi xác thực; mang sẵn Problem Details, không lộ nguyên nhân nội bộ."""

    def __init__(self, problem: dict[str, object], retry_after: int | None = None):
        super().__init__(str(problem.get("title", "Unauthorized")))
        self.problem = dict(problem)
        self.retry_after = retry_after

    @property
    def status(self) -> int:
        return int(self.problem["status"])  # type: ignore[arg-type]


class InvalidCredentials(AuthError):
    def __init__(self) -> None:
        super().__init__(INVALID_CREDENTIALS_PROBLEM)


class AccountLocked(AuthError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(LOCKED_PROBLEM, retry_after=retry_after_seconds)


@dataclass(frozen=True)
class UserRecord:
    """Bản ghi người dùng tối thiểu cho xác thực (không chứa PII thô ngoài email)."""

    user_id: str
    email: str
    role: Role
    password_hash: str
    is_active: bool = True
    mfa_secret: str | None = None
    branch_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Session:
    """Phiên máy chủ; định danh phiên là giá trị ngẫu nhiên do hạ tầng sinh."""

    session_id: str
    user_id: str
    role: Role
    branch_ids: tuple[str, ...]
    created_at: datetime
    expires_at: datetime

    def is_valid_at(self, now: datetime) -> bool:
        return now < self.expires_at


# Thuộc tính cookie bắt buộc (contract /auth/login 204)
SESSION_COOKIE_NAME = "qlkh_session"
SESSION_COOKIE_ATTRS: dict[str, object] = {
    "httponly": True,
    "secure": True,
    "samesite": "Lax",
    "path": "/",
}


@dataclass
class FailureCounter:
    """Đếm lần sai trong cửa sổ trượt cho một khóa (tài khoản hoặc IP)."""

    timestamps: list[datetime] = field(default_factory=list)
    locked_until: datetime | None = None

    def prune(self, now: datetime) -> None:
        cutoff = now - FAILURE_WINDOW
        self.timestamps = [t for t in self.timestamps if t > cutoff]

    def register_failure(self, now: datetime) -> None:
        self.prune(now)
        self.timestamps.append(now)
        if len(self.timestamps) >= MAX_FAILED_ATTEMPTS:
            self.locked_until = now + LOCKOUT_DURATION

    def retry_after(self, now: datetime) -> int | None:
        if self.locked_until is None:
            return None
        if now >= self.locked_until:
            self.locked_until = None
            self.timestamps = []
            return None
        return max(1, int((self.locked_until - now).total_seconds()))

    def reset(self) -> None:
        self.timestamps = []
        self.locked_until = None


def utcnow() -> datetime:
    """Thời gian UTC — tiêm được trong test."""
    return datetime.now(UTC)
