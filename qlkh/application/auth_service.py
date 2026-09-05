"""Dịch vụ xác thực (QLKH-004, REQ-001).

Cài đặt luồng POST /auth/login, POST /auth/logout, GET /auth/me theo
api-contract v1.0.0. Không import ORM/HTTP: mọi phụ thuộc là Protocol,
adapter hạ tầng hiện thực sau.

Threat refs: QLKH-T-04 (liệt kê tài khoản / brute-force), QLKH-T-03 (phiên cũ
của tài khoản bị vô hiệu hóa), QLKH-T-13 (DoS).

Các khiếm khuyết của vòng trước được xử lý ở đây:
- SD-28: mã băm dummy là mã băm argon2id THẬT sinh lúc khởi động bằng cùng
  tham số, nên nhánh "tài khoản không tồn tại" tốn đúng một lần KDF như nhánh
  tài khoản tồn tại (test đo chênh lệch thời gian).
- SD-29: bộ đếm nằm sau `AttemptStore`. Bản in-memory CÓ GIỚI HẠN kích thước và
  tự dọn mục hết hạn; nó chỉ hợp lệ cho tiến trình đơn (dev/test). Sản xuất
  phải tiêm bản dựa trên session store P2 (Redis) — xem `require_shared_store`.
- SD-30: chính sách IP tách khỏi chính sách tài khoản, dùng throttle backoff
  chứ không khóa cứng.
- SD-33: khi đăng nhập thành công mà mã băm còn dùng tham số cũ, dịch vụ gọi
  `needs_rehash` và ghi lại mã băm mới qua `on_password_rehash` (nâng dần,
  ASVS 2.4). Lỗi khi ghi KHÔNG chặn đăng nhập nhưng phải để lại dấu vết.
- SD-35: khi đã bị khóa, dịch vụ VẪN chạy đủ một lần KDF trước khi trả 429, và
  bộ đếm tăng cho cả email không tồn tại, nên phản hồi 429 giống hệt nhau giữa
  email tồn tại và không tồn tại (không còn kênh phụ liệt kê tài khoản).
- Quan sát vòng 5 (threat-model v1.19 mục 6): `_maybe_rehash` bắt Exception
  rộng nên hỏng âm thầm. Nay mỗi lần hỏng phát metric
  `METRIC_REHASH_FAILED` qua `MetricsSink` để có alert, ngoài log warning.
"""

from __future__ import annotations

import logging
import secrets
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from qlkh.domain.auth import (
    ACCOUNT_POLICY,
    IP_POLICY,
    MFA_REQUIRED_ROLES,
    SESSION_TTL,
    AccountLocked,
    AttemptPolicy,
    FailureCounter,
    InvalidCredentials,
    Session,
    UserRecord,
    utcnow,
)
from qlkh.domain.subject_context import SubjectContext

logger = logging.getLogger(__name__)

#: Tên metric cho alert "nâng dần argon2id đang hỏng âm thầm" (ASVS 2.4).
METRIC_REHASH_FAILED = "auth_password_rehash_failed_total"


class MetricsSink(Protocol):
    """Đích phát metric. Adapter hạ tầng (OpenTelemetry) hiện thực sau."""

    def increment(self, name: str, value: int = 1) -> None: ...


class PasswordHasher(Protocol):
    """Băm/kiểm mật khẩu bằng thuật toán chậm (argon2id — ADR-002)."""

    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class UserRepository(Protocol):
    def get_by_email(self, email: str) -> UserRecord | None: ...

    def get_by_id(self, user_id: str) -> UserRecord | None: ...


class SessionStore(Protocol):
    def create(self, session: Session) -> None: ...

    def get(self, session_id: str) -> Session | None: ...

    def delete(self, session_id: str) -> None: ...

    def delete_all_for_user(self, user_id: str) -> int: ...


class MfaVerifier(Protocol):
    def verify(self, secret: str, code: str) -> bool: ...


class AttemptStore(Protocol):
    """Bộ đếm lần sai. Sản xuất: hiện thực trên Redis (P2), dùng chung mọi worker."""

    #: True nếu trạng thái dùng chung giữa các tiến trình/replica.
    shared: bool

    def register_failure(self, key: str, now: datetime) -> None: ...

    def retry_after(self, key: str, now: datetime) -> int | None: ...

    def reset(self, key: str) -> None: ...


class InMemoryAttemptStore:
    """Bộ đếm trong RAM tiến trình — CHỈ dùng cho dev/test (SD-29).

    Có trần số khóa và tự dọn mục hết hạn để không tăng bộ nhớ vô hạn theo số
    email/IP lạ (ASVS 12.1). Với nhiều worker, ngưỡng thực tế bị nhân lên theo
    số tiến trình, nên `shared = False` và `AuthService` từ chối khởi tạo ở chế
    độ sản xuất với store này.
    """

    shared = False

    def __init__(self, policy: AttemptPolicy, max_keys: int = 10_000) -> None:
        self._policy = policy
        self._max_keys = max_keys
        self._counters: OrderedDict[str, FailureCounter] = OrderedDict()

    def _sweep(self, now: datetime, keep: str | None = None) -> None:
        expired = [k for k, c in self._counters.items() if k != keep and c.is_expired(now)]
        for key in expired:
            del self._counters[key]
        # Trần cứng: mục ít dùng nhất bị loại trước (SD-29).
        while len(self._counters) > self._max_keys:
            oldest, _ = next(iter(self._counters.items()))
            if oldest == keep:
                self._counters.move_to_end(oldest)
                oldest, _ = next(iter(self._counters.items()))
            del self._counters[oldest]

    def _counter(self, key: str, now: datetime) -> FailureCounter:
        counter = self._counters.get(key)
        if counter is None:
            counter = FailureCounter(policy=self._policy)
            self._counters[key] = counter
        self._counters.move_to_end(key)
        self._sweep(now, keep=key)
        return counter

    def register_failure(self, key: str, now: datetime) -> None:
        self._counter(key, now).register_failure(now)

    def retry_after(self, key: str, now: datetime) -> int | None:
        return self._counter(key, now).retry_after(now)

    def reset(self, key: str) -> None:
        self._counters.pop(key, None)

    def __len__(self) -> int:
        return len(self._counters)


class Argon2idPasswordHasher:
    """Adapter argon2id. Yêu cầu gói `argon2-cffi` ở runtime.

    Tham số ghim tường minh (ASVS 2.4.1, SD-33) để mọi môi trường dùng cùng chi
    phí KDF; đổi tham số thì `needs_rehash` báo để nâng dần khi người dùng đăng
    nhập.
    """

    #: Ghim tường minh — đổi giá trị là thay đổi có kiểm soát, không mặc định ẩn.
    DEFAULT_PARAMS: dict[str, int] = {
        "time_cost": 3,
        "memory_cost": 65536,  # 64 MiB
        "parallelism": 4,
        "hash_len": 32,
        "salt_len": 16,
    }

    def __init__(self, **params: Any) -> None:
        try:
            from argon2 import PasswordHasher as _PH  # type: ignore
        except ImportError as exc:  # pragma: no cover - phụ thuộc runtime
            raise RuntimeError(
                "Thiếu phụ thuộc 'argon2-cffi' cho băm mật khẩu argon2id "
                "(ADR-002). Thêm vào requirements trước khi triển khai."
            ) from exc
        self.params = {**self.DEFAULT_PARAMS, **params}
        self._ph = _PH(**self.params)

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
        account_attempts: AttemptStore | None = None,
        ip_attempts: AttemptStore | None = None,
        require_shared_store: bool = False,
        on_password_rehash: Callable[[str, str], None] | None = None,
        metrics: MetricsSink | None = None,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._hasher = hasher
        self._mfa = mfa
        self._new_session_id = session_id_factory
        self._clock = clock
        self._on_password_rehash = on_password_rehash
        self._metrics = metrics
        self._account_attempts: AttemptStore = (
            InMemoryAttemptStore(ACCOUNT_POLICY) if account_attempts is None else account_attempts
        )
        self._ip_attempts: AttemptStore = InMemoryAttemptStore(IP_POLICY) if ip_attempts is None else ip_attempts
        if require_shared_store and not (self._account_attempts.shared and self._ip_attempts.shared):
            raise RuntimeError(
                "Khóa tạm phải nằm ở store dùng chung (session store P2) khi chạy nhiều tiến trình/replica — SD-29."
            )
        # SD-28: mã băm dummy THẬT, cùng tham số, sinh một lần lúc khởi động.
        self._dummy_hash = hasher.hash(secrets.token_urlsafe(32))

    # ----------------------------------------------------------------- #
    # Khóa tạm                                                          #
    # ----------------------------------------------------------------- #

    @staticmethod
    def _account_key(email: str) -> str:
        return email.strip().lower()

    def _locked_retry_after(self, email: str, ip: str) -> int | None:
        """Trả Retry-After nếu đang bị khóa/throttle, không ném lỗi tại chỗ.

        Người gọi phải hoàn tất công việc KDF trước khi trả 429 (SD-35), nếu
        không thì thời gian phản hồi lộ ra tài khoản có tồn tại hay không.
        """
        now = self._clock()
        for store, key in (
            (self._account_attempts, self._account_key(email)),
            (self._ip_attempts, ip),
        ):
            retry_after = store.retry_after(key, now)
            if retry_after is not None:
                return retry_after
        return None

    def _register_failure(self, email: str, ip: str) -> None:
        now = self._clock()
        self._account_attempts.register_failure(self._account_key(email), now)
        self._ip_attempts.register_failure(ip, now)

    def _emit(self, metric: str) -> None:
        """Phát metric; đích metric hỏng không bao giờ ảnh hưởng nghiệp vụ."""
        if self._metrics is None:
            return
        try:
            self._metrics.increment(metric)
        except Exception:  # pragma: no cover - phụ thuộc adapter
            logger.warning("metrics_emit_failed", extra={"metric": metric})

    def _maybe_rehash(self, user: UserRecord, password: str) -> None:
        """Nâng tham số KDF khi đăng nhập thành công (SD-33).

        Chỉ chạy khi có nơi ghi (`on_password_rehash`); lỗi khi ghi không được
        làm hỏng đăng nhập của người dùng hợp lệ, nhưng phải để lại dấu vết:
        log warning KHÔNG chứa PII và một metric đếm được để đặt alert (quan sát
        vòng 5 — nếu không thì việc nâng dần có thể hỏng vĩnh viễn mà im lặng).
        """
        if self._on_password_rehash is None:
            return
        if not self._hasher.needs_rehash(user.password_hash):
            return
        try:
            self._on_password_rehash(user.user_id, self._hasher.hash(password))
        except Exception:
            logger.warning(
                "password_rehash_failed",
                extra={"user_id": user.user_id},
                exc_info=True,
            )
            self._emit(METRIC_REHASH_FAILED)

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

        Không phân biệt nguyên nhân trong thông điệp trả ra ngoài (T-04), không
        phân biệt qua thời gian phản hồi (SD-28), và không phân biệt qua việc
        có bị khóa hay không (SD-35): bộ đếm tăng cho cả email không tồn tại nên
        cùng số lần sai sẽ cho cùng một phản hồi 429.
        """
        locked_retry_after = self._locked_retry_after(email, ip)

        user = self._users.get_by_email(email.strip().lower())
        password_hash = self._dummy_hash if user is None else user.password_hash
        # Luôn chạy đúng một lần KDF, kể cả khi đã biết là bị khóa (SD-35).
        password_ok = self._hasher.verify(password_hash, password)

        if locked_retry_after is not None:
            raise AccountLocked(locked_retry_after)

        if user is None or not password_ok or not user.is_active:
            self._register_failure(email, ip)
            raise InvalidCredentials()

        if user.role in MFA_REQUIRED_ROLES:
            if not mfa_code or not user.mfa_secret or not self._mfa.verify(user.mfa_secret, mfa_code):
                self._register_failure(email, ip)
                raise InvalidCredentials()

        self._account_attempts.reset(self._account_key(email))
        self._maybe_rehash(user, password)

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

        Ngoài việc thu hồi phiên khi vô hiệu hóa tài khoản, mỗi request còn kiểm
        lại `is_active` của chủ phiên để không phụ thuộc vào một điểm gọi duy
        nhất (QLKH-T-03, SD-31).
        """
        if not session_id:
            raise InvalidCredentials()
        session = self._sessions.get(session_id)
        if session is None or not session.is_valid_at(self._clock()):
            raise InvalidCredentials()
        user = self._users.get_by_id(session.user_id)
        if user is None or not user.is_active:
            self.revoke_all_sessions(session.user_id)
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

    def deactivate_account(self, user_id: str, deactivate: Callable[[str], Any]) -> int:
        """Điểm gọi tường minh của luồng vô hiệu hóa: đổi trạng thái rồi thu hồi.

        `deactivate` là thao tác ghi của tầng người dùng (repo/usecase khác);
        service chỉ bảo đảm thu hồi phiên xảy ra ngay sau đó (SD-31).
        """
        deactivate(user_id)
        return self.revoke_all_sessions(user_id)
