"""Test xác thực QLKH-004 / REQ-001 theo tiêu chí Gherkin của ticket.

G1: tài khoản không tồn tại và sai mật khẩu → thông điệp và mã lỗi giống hệt
    (kể cả thời gian phản hồi — SD-28).
G2: 5 lần sai trong 15 phút → lần 6 bị khóa 15 phút (theo TÀI KHOẢN); theo IP
    là throttle backoff ở ngưỡng cao hơn nhiều bậc (SD-30).
G3: giáo viên bị vô hiệu hóa dùng phiên cũ → 401 ngay lập tức (SD-31).
G4: tài khoản admin đăng nhập không có MFA → bị từ chối.

Threat refs: QLKH-T-04, QLKH-T-03, QLKH-T-13.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from qlkh.application.auth_service import AuthService, InMemoryAttemptStore
from qlkh.domain.auth import (
    ACCOUNT_POLICY,
    IP_POLICY,
    IP_THROTTLE_THRESHOLD,
    LOCKOUT_DURATION,
    MAX_FAILED_ATTEMPTS,
    SESSION_COOKIE_ATTRS,
    SESSION_COOKIE_NAME,
    AccountLocked,
    AuthError,
    InvalidCredentials,
    Session,
    UserRecord,
)

T0 = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class FakeHasher:
    """Băm giả lập: hash = 'h:' + password. Không dùng ngoài test."""

    def hash(self, password: str) -> str:
        return f"h:{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"h:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


class SlowHasher(FakeHasher):
    """Mô phỏng argon2id: KDF tốn thời gian, mã băm sai định dạng thì trả ngay.

    Đây chính là hành vi của `Argon2idPasswordHasher.verify` (bắt Exception khi
    parse lỗi) — dùng để phát hiện timing oracle ở nhánh tài khoản không tồn tại.
    """

    KDF_DELAY = 0.02

    def verify(self, password_hash: str, password: str) -> bool:
        if not password_hash.startswith("h:"):
            return False
        time.sleep(self.KDF_DELAY)
        return password_hash == f"h:{password}"


class FakeUsers:
    def __init__(self, users: list[UserRecord]) -> None:
        self._by_email = {u.email: u for u in users}

    def get_by_email(self, email: str) -> UserRecord | None:
        return self._by_email.get(email)

    def get_by_id(self, user_id: str) -> UserRecord | None:
        for user in self._by_email.values():
            if user.user_id == user_id:
                return user
        return None

    def deactivate(self, email: str) -> UserRecord:
        user = self._by_email[email]
        updated = UserRecord(
            user_id=user.user_id,
            email=user.email,
            role=user.role,
            password_hash=user.password_hash,
            is_active=False,
            mfa_secret=user.mfa_secret,
            branch_ids=user.branch_ids,
        )
        self._by_email[email] = updated
        return updated


class FakeSessions:
    def __init__(self) -> None:
        self.data: dict[str, Session] = {}

    def create(self, session: Session) -> None:
        self.data[session.session_id] = session

    def get(self, session_id: str) -> Session | None:
        return self.data.get(session_id)

    def delete(self, session_id: str) -> None:
        self.data.pop(session_id, None)

    def delete_all_for_user(self, user_id: str) -> int:
        victims = [k for k, s in self.data.items() if s.user_id == user_id]
        for k in victims:
            del self.data[k]
        return len(victims)


class FakeMfa:
    def verify(self, secret: str, code: str) -> bool:
        return code == f"code-{secret}"


class SharedAttemptStore(InMemoryAttemptStore):
    """Giả lập store dùng chung (Redis P2) cho test cấu hình sản xuất."""

    shared = True


TEACHER = UserRecord(
    user_id="u-teacher",
    email="teacher@example.vn",
    role="teacher",
    password_hash="h:correct-horse",
    branch_ids=(BRANCH_A,),
)
ADMIN = UserRecord(
    user_id="u-admin",
    email="admin@example.vn",
    role="admin",
    password_hash="h:admin-pass",
    mfa_secret="s3cr3t",
    branch_ids=(BRANCH_A,),
)


def build_service(hasher=None, clock=None, **kwargs):
    clock = clock or FakeClock()
    users = FakeUsers([TEACHER, ADMIN])
    sessions = FakeSessions()
    counter = {"n": 0}

    def sid() -> str:
        counter["n"] += 1
        return f"sess-{counter['n']}"

    service = AuthService(
        users=users,
        sessions=sessions,
        hasher=hasher or FakeHasher(),
        mfa=FakeMfa(),
        session_id_factory=sid,
        clock=clock,
        **kwargs,
    )
    return service, users, sessions, clock


@pytest.fixture()
def env():
    return build_service()


def test_login_success_creates_server_session(env):
    service, _, sessions, _ = env
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="1.1.1.1"
    )
    assert session.session_id in sessions.data
    assert session.role == "teacher"
    assert session.branch_ids == (BRANCH_A,)


def test_cookie_attributes_match_contract():
    assert SESSION_COOKIE_NAME == "qlkh_session"
    assert SESSION_COOKIE_ATTRS["httponly"] is True
    assert SESSION_COOKIE_ATTRS["secure"] is True
    assert SESSION_COOKIE_ATTRS["samesite"] == "Lax"


def test_g1_unknown_account_and_wrong_password_identical(env):
    """G1: hai nguyên nhân khác nhau nhưng lỗi trả ra phải giống hệt."""
    service, _, _, _ = env
    with pytest.raises(AuthError) as unknown:
        service.login(email="nobody@example.vn", password="x" * 12, ip="1.1.1.1")
    with pytest.raises(AuthError) as wrong:
        service.login(email="teacher@example.vn", password="wrong-pass", ip="2.2.2.2")
    assert unknown.value.problem == wrong.value.problem
    assert unknown.value.status == wrong.value.status == 401
    assert "teacher" not in str(unknown.value.problem)


def test_g1_disabled_account_same_message(env):
    service, users, _, _ = env
    users.deactivate("teacher@example.vn")
    with pytest.raises(AuthError) as disabled:
        service.login(
            email="teacher@example.vn", password="correct-horse", ip="3.3.3.3"
        )
    with pytest.raises(AuthError) as unknown:
        service.login(email="nobody@example.vn", password="x" * 12, ip="4.4.4.4")
    assert disabled.value.problem == unknown.value.problem


def test_g1_no_timing_oracle_between_unknown_and_existing_account():
    """SD-28: nhánh không tồn tại phải chạy đúng một lần KDF như nhánh tồn tại."""
    service, _, _, _ = build_service(hasher=SlowHasher())

    def elapsed(email: str, ip: str) -> float:
        start = time.perf_counter()
        with pytest.raises(AuthError):
            service.login(email=email, password="wrong-pass", ip=ip)
        return time.perf_counter() - start

    unknown = min(elapsed("nobody@example.vn", f"10.0.0.{i}") for i in range(3))
    existing = min(elapsed("teacher@example.vn", f"10.0.1.{i}") for i in range(3))
    # Chênh lệch phải nhỏ hơn nhiều so với chi phí một lần KDF.
    assert abs(unknown - existing) < SlowHasher.KDF_DELAY / 2


def test_g2_lockout_after_five_failures(env):
    service, _, _, clock = env
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(InvalidCredentials):
            service.login(
                email="teacher@example.vn", password="bad-pass-1", ip="5.5.5.5"
            )
    with pytest.raises(AccountLocked) as locked:
        service.login(
            email="teacher@example.vn", password="correct-horse", ip="5.5.5.5"
        )
    assert locked.value.status == 429
    assert 0 < locked.value.retry_after <= int(LOCKOUT_DURATION.total_seconds())

    # Vẫn khóa ngay trước khi hết 15 phút
    clock.advance(LOCKOUT_DURATION - timedelta(seconds=1))
    with pytest.raises(AccountLocked):
        service.login(
            email="teacher@example.vn", password="correct-horse", ip="5.5.5.5"
        )

    # Hết 15 phút thì mở khóa
    clock.advance(timedelta(seconds=2))
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="5.5.5.5"
    )
    assert session.user_id == "u-teacher"


def test_g2_failures_outside_window_do_not_lock(env):
    service, _, _, clock = env
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(InvalidCredentials):
            service.login(email="teacher@example.vn", password="bad", ip="6.6.6.6")
    clock.advance(timedelta(minutes=16))
    with pytest.raises(InvalidCredentials):
        service.login(email="teacher@example.vn", password="bad", ip="6.6.6.6")
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="6.6.6.6"
    )
    assert session.session_id


def test_g2_shared_ip_does_not_lock_out_legitimate_user(env):
    """SD-30: NAT dùng chung — 5 lần người khác gõ sai không được khóa IP."""
    service, _, _, _ = env
    for i in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(InvalidCredentials):
            service.login(email=f"u{i}@example.vn", password="bad-pass", ip="7.7.7.7")
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="7.7.7.7"
    )
    assert session.user_id == "u-teacher"


def test_g2_ip_throttle_is_backoff_not_hard_lock(env):
    """Vượt ngưỡng IP → chờ vài giây, KHÔNG khóa cứng 15 phút."""
    service, _, _, clock = env
    for i in range(IP_THROTTLE_THRESHOLD):
        with pytest.raises(InvalidCredentials):
            service.login(
                email=f"bulk{i}@example.vn", password="bad-pass", ip="7.7.7.8"
            )
    with pytest.raises(AccountLocked) as throttled:
        service.login(
            email="teacher@example.vn", password="correct-horse", ip="7.7.7.8"
        )
    assert throttled.value.status == 429
    assert 0 < throttled.value.retry_after <= 60

    clock.advance(timedelta(seconds=61))
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="7.7.7.8"
    )
    assert session.user_id == "u-teacher"


def test_attempt_store_is_bounded_in_size():
    """SD-29: bộ đếm không được tăng bộ nhớ vô hạn theo số email/IP lạ."""
    store = InMemoryAttemptStore(IP_POLICY, max_keys=50)
    now = T0
    for i in range(500):
        store.register_failure(f"ip-{i}", now)
    assert len(store) <= 50


def test_attempt_store_evicts_expired_entries():
    store = InMemoryAttemptStore(ACCOUNT_POLICY, max_keys=1000)
    store.register_failure("a@example.vn", T0)
    assert len(store) == 1
    store.register_failure("b@example.vn", T0 + timedelta(minutes=30))
    assert len(store) == 1  # mục cũ đã hết hạn và bị dọn


def test_production_requires_shared_attempt_store():
    """SD-29: chạy nhiều replica mà đếm trong RAM tiến trình là cấu hình sai."""
    with pytest.raises(RuntimeError):
        build_service(require_shared_store=True)
    service, _, _, _ = build_service(
        require_shared_store=True,
        account_attempts=SharedAttemptStore(ACCOUNT_POLICY),
        ip_attempts=SharedAttemptStore(IP_POLICY),
    )
    assert service.login(
        email="teacher@example.vn", password="correct-horse", ip="1.9.9.9"
    )


def test_g3_disabled_user_old_session_rejected_immediately(env):
    service, users, _, _ = env
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="9.9.9.9"
    )
    assert service.me(session.session_id)["user_id"] == "u-teacher"

    revoked = service.deactivate_account(
        "u-teacher", lambda _uid: users.deactivate("teacher@example.vn")
    )
    assert revoked == 1
    with pytest.raises(AuthError) as exc:
        service.me(session.session_id)
    assert exc.value.status == 401


def test_g3_session_rejected_even_if_revoke_was_missed(env):
    """SD-31: phiên còn trong store nhưng tài khoản đã tắt → vẫn 401."""
    service, users, sessions, _ = env
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="9.9.9.8"
    )
    users.deactivate("teacher@example.vn")  # cố ý KHÔNG gọi revoke
    assert session.session_id in sessions.data
    with pytest.raises(AuthError) as exc:
        service.me(session.session_id)
    assert exc.value.status == 401
    assert session.session_id not in sessions.data  # đã tự thu hồi


def test_g4_admin_without_mfa_rejected(env):
    service, _, _, _ = env
    with pytest.raises(AuthError) as missing:
        service.login(email="admin@example.vn", password="admin-pass", ip="1.2.3.4")
    assert missing.value.status == 401
    with pytest.raises(AuthError) as wrong_code:
        service.login(
            email="admin@example.vn",
            password="admin-pass",
            ip="1.2.3.5",
            mfa_code="000000",
        )
    assert wrong_code.value.problem == missing.value.problem


def test_g4_admin_with_valid_mfa_succeeds(env):
    service, _, _, _ = env
    session = service.login(
        email="admin@example.vn",
        password="admin-pass",
        ip="1.2.3.6",
        mfa_code="code-s3cr3t",
    )
    assert session.role == "admin"


def test_logout_is_idempotent(env):
    service, _, sessions, _ = env
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="1.2.3.7"
    )
    service.logout(session.session_id)
    service.logout(session.session_id)
    assert session.session_id not in sessions.data
    with pytest.raises(AuthError):
        service.me(session.session_id)


def test_expired_session_rejected(env):
    service, _, _, clock = env
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="1.2.3.8"
    )
    clock.advance(timedelta(hours=13))
    with pytest.raises(AuthError):
        service.me(session.session_id)


def test_missing_session_cookie_rejected(env):
    service, _, _, _ = env
    with pytest.raises(AuthError):
        service.me(None)


def test_subject_context_branches_come_from_session(env):
    service, _, _, _ = env
    session = service.login(
        email="teacher@example.vn", password="correct-horse", ip="1.2.3.9"
    )
    ctx = service.subject_context(session.session_id)
    assert ctx.allowed_branch_ids == (BRANCH_A,)
    assert ctx.can_access_branch("bbbbbbbb-0000-0000-0000-000000000002") is False


def test_email_is_case_and_space_insensitive(env):
    service, _, _, _ = env
    assert service.login(
        email="  Teacher@Example.VN ", password="correct-horse", ip="1.2.3.10"
    )
