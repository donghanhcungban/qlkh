"""Domain xác thực QLKH (QLKH-004, REQ-001, NFR-002, ADR-002).

Thuần domain: không import ORM/HTTP/framework (fitness function kiểm bằng AST).

Nguyên tắc:
- Thông điệp lỗi đăng nhập ĐỒNG NHẤT cho mọi nguyên nhân (không tồn tại, sai
  mật khẩu, tài khoản bị vô hiệu hóa, thiếu/sai MFA) — chống liệt kê tài khoản
  (threat QLKH-T-04). Kể cả kênh phụ thời gian: xem `AuthService._dummy_hash`.
- Khóa tạm theo TÀI KHOẢN: 5 lần sai trong 15 phút → khóa 15 phút.
- Theo IP: KHÔNG khóa cứng (gây DoS người dùng hợp lệ sau NAT — SD-30). Dùng
  ngưỡng cao hơn nhiều bậc + backoff tăng dần (throttle) với Retry-After ngắn.
- Phiên máy chủ: thu hồi tức thì khi tài khoản bị vô hiệu hóa (QLKH-T-03);
  mỗi request còn kiểm lại `is_active` của chủ phiên (SD-31).
- MFA bắt buộc cho vai trò admin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

Role = Literal["parent", "teacher", "staff", "admin"]

# --- Chính sách theo tài khoản (NFR-002) ------------------------------- #
MAX_FAILED_ATTEMPTS = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT_DURATION = timedelta(minutes=15)

# --- Chính sách theo IP (SD-30) ---------------------------------------- #
# Ngưỡng cao hơn nhiều bậc vì một IP có thể là NAT của cả trung tâm.
IP_THROTTLE_THRESHOLD = 50
IP_FAILURE_WINDOW = timedelta(minutes=15)
IP_BACKOFF_BASE = timedelta(seconds=2)
IP_BACKOFF_MAX = timedelta(seconds=60)

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


@dataclass(frozen=True)
class AttemptPolicy:
    """Chính sách đếm lần sai. `mode` phân biệt khóa cứng và throttle.

    - `lock`: đạt ngưỡng → chặn trọn `lockout` (dùng cho TÀI KHOẢN).
    - `throttle`: vượt ngưỡng → Retry-After tăng dần theo cấp số nhân, có trần;
      không khóa cứng để một IP dùng chung không làm DoS người dùng hợp lệ.
    """

    threshold: int
    window: timedelta
    mode: Literal["lock", "throttle"] = "lock"
    lockout: timedelta = LOCKOUT_DURATION
    backoff_base: timedelta = IP_BACKOFF_BASE
    backoff_max: timedelta = IP_BACKOFF_MAX


ACCOUNT_POLICY = AttemptPolicy(
    threshold=MAX_FAILED_ATTEMPTS,
    window=FAILURE_WINDOW,
    mode="lock",
    lockout=LOCKOUT_DURATION,
)
IP_POLICY = AttemptPolicy(
    threshold=IP_THROTTLE_THRESHOLD,
    window=IP_FAILURE_WINDOW,
    mode="throttle",
)


@dataclass
class FailureCounter:
    """Đếm lần sai trong cửa sổ trượt cho một khóa (tài khoản hoặc IP)."""

    policy: AttemptPolicy = ACCOUNT_POLICY
    timestamps: list[datetime] = field(default_factory=list)
    locked_until: datetime | None = None
    last_seen: datetime | None = None

    def prune(self, now: datetime) -> None:
        cutoff = now - self.policy.window
        # `>=` để không loại nhầm lần sai đúng ở biên cửa sổ.
        self.timestamps = [t for t in self.timestamps if t >= cutoff]

    def register_failure(self, now: datetime) -> None:
        self.prune(now)
        self.timestamps.append(now)
        self.last_seen = now
        if self.policy.mode == "lock" and len(self.timestamps) >= self.policy.threshold:
            self.locked_until = now + self.policy.lockout

    def retry_after(self, now: datetime) -> int | None:
        """Số giây phải chờ, hoặc None nếu được phép thử."""
        if self.policy.mode == "lock":
            if self.locked_until is None:
                return None
            if now >= self.locked_until:
                # Hết khóa: xóa hẳn trạng thái để bắt đầu cửa sổ mới.
                self.locked_until = None
                self.timestamps = []
                return None
            return max(1, int((self.locked_until - now).total_seconds()))

        # throttle
        self.prune(now)
        excess = len(self.timestamps) - self.policy.threshold
        if excess < 0 or not self.timestamps:
            return None
        delay = min(
            self.policy.backoff_max,
            self.policy.backoff_base * (2 ** min(excess, 16)),
        )
        elapsed = now - self.timestamps[-1]
        remaining = delay - elapsed
        if remaining <= timedelta(0):
            return None
        return max(1, int(remaining.total_seconds()))

    def is_expired(self, now: datetime) -> bool:
        """Không còn giá trị bảo mật → có thể thu hồi khỏi bộ nhớ (SD-29)."""
        if self.locked_until is not None and now < self.locked_until:
            return False
        self.prune(now)
        return not self.timestamps

    def reset(self) -> None:
        self.timestamps = []
        self.locked_until = None


def utcnow() -> datetime:
    """Thời gian UTC — tiêm được trong test."""
    return datetime.now(UTC)
