"""Dịch vụ xác thực (QLKH-004, REQ-001).

Cài đặt luồng POST /auth/login, POST /auth/logout, GET /auth/me theo
api-contract v1.0.0. Không import ORM/HTTP: mọi phụ thuộc là Protocol,
adapter hạ tầng hiện thực sau.

Threat refs: QLKH-T-04 (liệt kê tài khoản / brute-force), QLKH-T-03 (phiên cũ
của tài khoản bị vô hiệu hóa).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from qlkh.domain.auth import (
    MFA_REQUIRED_ROLES,
    SESSION_TTL,
    AccountLocked,
    FailureCounter,
    InvalidCredentials,
    Session,
    UserRecord,
    utcnow,
)
from qlkh.domain.subject_context import SubjectContext


class PasswordHasher(Protocol):
    """Băm/kiểm mật khẩu bằng thuật toán chậm (argon2id — ADR-002)."""

    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class UserRepository(Protocol):
    def get_by_email(self, email: str) -> UserRecord | None: ...


class SessionStore(Protocol):
    def create(self, session: Session) -> None: ...

    def get(self, session_id: str) -> Session | None: ...

    def delete(self, session_id: str) -> None: ...

    def delete_all_for_user(self, user_id: str) -> int: ...


class MfaVerifier(Protocol):
    def verify(self, secret: str, code: str) -> bool: ...


class Argon2idPasswordHasher:
    """Adapter argon2id. Yêu cầu gói `argon2-cffi` ở runtime.

    Tách riêng để domain không phụ thuộc thư viện; lỗi thiếu gói được nêu rõ
    thay vì âm thầm rơi về thuật toán yếu.
    """

    def __init__(self, **params: Any) -> None:
        try:
            from argon2 import PasswordHasher as _PH  # type: ignore
        except ImportError as exc:  # pragma: no cover - phụ thuộc runtime
            raise RuntimeError(
                "Thiếu phụ thuộc 'argon2-cffi' cho băm mật khẩu argon2id "
                "(ADR-002). Thêm vào requirements trước khi triển khai."
            ) from exc
        self._ph = _PH(**params) if params else _PH()

    def hash(self, password: str) -> str:  # pragma: no cover - cần argon2-cffi
        return str(self._ph.hash(password))

    def verify(self, password_hash: str, password: str) -> bool:  # pragma: no cover
        try:
            return bool(self._ph.verify(password_hash, password))
        except Exception:
            return False

    def needs_rehash(self, password_hash: str) -> bool:  # pragma: no cover
        return bool(self._ph.check_needs_rehash(password_hash))


class AuthService:
    """Logic đăng nhập/đăng xuất/phiên. Mọi lỗi trả về Problem đồng nhất."""

    def __init__(
        self,
        users: UserRepository,
        sessions: SessionStore,
        hasher: PasswordHasher,
        mfa: MfaVerifier,
        session_id_factory: Callable[[], str],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._hasher = hasher
        self._mfa = mfa
        self._new_session_id = session_id_factory
        self._clock = clock
        self._by_account: dict[str, FailureCounter] = {}
        self._by_ip: dict[str, FailureCounter] = {}

    # ----------------------------------------------------------------- #
    # Khóa tạm                                                          #
    # ----------------------------------------------------------------- #

    def _counters(self, email: str, ip: str) -> tuple[FailureCounter, FailureCounter]:
        account = self._by_account.setdefault(email.strip().lower(), FailureCounter())
        by_ip = self._by_ip.setdefault(ip, FailureCounter())
        return account, by_ip

    def _assert_not_locked(self, email: str, ip: str) -> None:
        now = self._clock()
        for counter in self._counters(email, ip):
            retry_after = counter.retry_after(now)
            if retry_after is not None:
                raise AccountLocked(retry_after)

    def _register_failure(self, email: str, ip: str) -> None:
        now = self._clock()
        for counter in self._counters(email, ip):
            counter.register_failure(now)

    # ----------------------------------------------------------------- #
    # Luồng chính                                                       #
    # ----------------------------------------------------------------- #

    def login(
        self,
        *,
        email: str,
        password: str,
        ip: str,
        mfa_code: str | None = None,
    ) -> Session:
        """Trả Session khi thành công; ném AuthError với Problem đồng nhất khi hỏng.

        Không phân biệt nguyên nhân trong thông điệp trả ra ngoài (T-04).
        """
        self._assert_not_locked(email, ip)

        user = self._users.get_by_email(email.strip().lower())
        if user is None:
            # Vẫn tốn thời gian băm để giảm chênh lệch thời gian phản hồi.
            self._hasher.verify("$argon2id$dummy", password)
            self._register_failure(email, ip)
            raise InvalidCredentials()

        if not self._hasher.verify(user.password_hash, password):
            self._register_failure(email, ip)
            raise InvalidCredentials()

        if not user.is_active:
            self._register_failure(email, ip)
            raise InvalidCredentials()

        if user.role in MFA_REQUIRED_ROLES:
            if (
                not mfa_code
                or not user.mfa_secret
                or not self._mfa.verify(user.mfa_secret, mfa_code)
            ):
                self._register_failure(email, ip)
                raise InvalidCredentials()

        account, by_ip = self._counters(email, ip)
        account.reset()
        by_ip.reset()

        now = self._clock()
        session = Session(
            session_id=self._new_session_id(),
            user_id=user.user_id,
            role=user.role,
            branch_ids=tuple(user.branch_ids),
            created_at=now,
            expires_at=now + SESSION_TTL,
        )
        self._sessions.create(session)
        return session

    def logout(self, session_id: str) -> None:
        """Hủy phiên hiện tại (idempotent: gọi lại không lỗi)."""
        self._sessions.delete(session_id)

    def resolve_session(self, session_id: str | None) -> Session:
        """Trả phiên hợp lệ hoặc ném InvalidCredentials (401).

        Phiên của tài khoản bị vô hiệu hóa đã bị thu hồi khỏi session store nên
        bị từ chối NGAY ở request kế tiếp (QLKH-T-03).
        """
        if not session_id:
            raise InvalidCredentials()
        session = self._sessions.get(session_id)
        if session is None or not session.is_valid_at(self._clock()):
            raise InvalidCredentials()
        return session

    def me(self, session_id: str | None) -> dict[str, Any]:
        """Payload cho GET /auth/me theo schema Me."""
        session = self.resolve_session(session_id)
        return {
            "user_id": session.user_id,
            "role": session.role,
            "branch_ids": list(session.branch_ids),
        }

    def subject_context(self, session_id: str | None) -> SubjectContext:
        """Dựng SubjectContext từ phiên — branch_id KHÔNG bao giờ từ client."""
        session = self.resolve_session(session_id)
        return SubjectContext(
            user_id=session.user_id,
            role=session.role,
            allowed_branch_ids=tuple(session.branch_ids),
        )

    def revoke_all_sessions(self, user_id: str) -> int:
        """Thu hồi toàn bộ phiên của một tài khoản (khi vô hiệu hóa)."""
        return self._sessions.delete_all_for_user(user_id)
