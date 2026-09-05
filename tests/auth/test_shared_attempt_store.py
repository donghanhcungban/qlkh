"""Test store lần sai dùng chung + wiring sản xuất (QLKH-004, REQ-001, SD-29).

Điều kiện đóng SD-29 trong threat-model mục 6:
1. Adapter `AttemptStore` trên session store P2 với `shared = True`, đếm nguyên tử.
2. Cấu hình sản xuất fail-fast khi store không dùng chung.
3. Hai instance `AuthService` dùng chung store thì lần sai thứ 5 TỔNG CỘNG gây khóa.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qlkh.application.auth_service import AuthService, InMemoryAttemptStore
from qlkh.application.auth_wiring import (
    AuthFeatureFlags,
    FeatureDisabled,
    build_auth_service,
)
from qlkh.domain.auth import (
    ACCOUNT_POLICY,
    IP_POLICY,
    LOCKOUT_DURATION,
    MAX_FAILED_ATTEMPTS,
    AccountLocked,
    InvalidCredentials,
    Session,
    UserRecord,
)
from qlkh.infrastructure.attempt_store_redis import RedisAttemptStore

T0 = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
ON = AuthFeatureFlags(login_argon2=True)


class FakeRedis:
    """Giả lập tối thiểu INCR/EXPIRE/SET/TTL/DEL với đồng hồ tiêm được."""

    def __init__(self, clock) -> None:
        self._clock = clock
        self._values: dict[str, int] = {}
        self._expiry: dict[str, datetime] = {}

    def _gc(self, key: str) -> None:
        exp = self._expiry.get(key)
        if exp is not None and self._clock() >= exp:
            self._values.pop(key, None)
            self._expiry.pop(key, None)

    def incr_with_expiry(self, key: str, ttl_seconds: int) -> int:
        self._gc(key)
        self._values[key] = self._values.get(key, 0) + 1
        self._expiry.setdefault(key, self._clock() + timedelta(seconds=ttl_seconds))
        return self._values[key]

    def set_lock(self, key: str, ttl_seconds: int) -> None:
        self._values[key] = 1
        self._expiry[key] = self._clock() + timedelta(seconds=ttl_seconds)

    def lock_ttl(self, key: str) -> int | None:
        self._gc(key)
        if key not in self._values:
            return None
        return int((self._expiry[key] - self._clock()).total_seconds())

    def delete(self, *keys: str) -> None:
        for key in keys:
            self._values.pop(key, None)
            self._expiry.pop(key, None)


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class FakeHasher:
    def hash(self, password: str) -> str:
        return f"h:{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"h:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


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


TEACHER = UserRecord(
    user_id="u-teacher",
    email="teacher@example.vn",
    role="teacher",
    password_hash="h:correct-horse",
    branch_ids=(BRANCH_A,),
)


def make_service(clock, account_store, ip_store, environment="production", tag="a"):
    counter = {"n": 0}

    def sid() -> str:
        counter["n"] += 1
        return f"sid-{tag}-{counter['n']}"

    return build_auth_service(
        users=FakeUsers([TEACHER]),
        sessions=FakeSessions(),
        hasher=FakeHasher(),
        mfa=FakeMfa(),
        session_id_factory=sid,
        account_attempts=account_store,
        ip_attempts=ip_store,
        environment=environment,
        flags=ON,
        clock=clock,
    )


# --- SD-29 điều kiện 1: adapter dùng chung ----------------------------- #


def test_redis_attempt_store_is_shared_and_locks_at_threshold() -> None:
    clock = FakeClock()
    store = RedisAttemptStore(FakeRedis(clock), ACCOUNT_POLICY)
    assert store.shared is True

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        store.register_failure("teacher@example.vn", clock())
    assert store.retry_after("teacher@example.vn", clock()) is None

    store.register_failure("teacher@example.vn", clock())
    retry = store.retry_after("teacher@example.vn", clock())
    assert retry == int(LOCKOUT_DURATION.total_seconds())

    clock.advance(LOCKOUT_DURATION + timedelta(seconds=1))
    assert store.retry_after("teacher@example.vn", clock()) is None


def test_redis_attempt_store_ip_uses_backoff_not_hard_lock() -> None:
    clock = FakeClock()
    store = RedisAttemptStore(FakeRedis(clock), IP_POLICY, namespace="auth:ip")
    for _ in range(IP_POLICY.threshold):
        store.register_failure("203.0.113.9", clock())
    first = store.retry_after("203.0.113.9", clock())
    assert first == int(IP_POLICY.backoff_base.total_seconds())

    store.register_failure("203.0.113.9", clock())
    second = store.retry_after("203.0.113.9", clock())
    assert second is not None and first is not None and second > first
    assert second <= int(IP_POLICY.backoff_max.total_seconds())


def test_redis_attempt_store_reset_clears_counter_and_lock() -> None:
    clock = FakeClock()
    store = RedisAttemptStore(FakeRedis(clock), ACCOUNT_POLICY)
    for _ in range(MAX_FAILED_ATTEMPTS):
        store.register_failure("teacher@example.vn", clock())
    store.reset("teacher@example.vn")
    assert store.retry_after("teacher@example.vn", clock()) is None


# --- SD-29 điều kiện 2: sản xuất fail-fast ----------------------------- #


def test_production_wiring_rejects_in_memory_store() -> None:
    clock = FakeClock()
    with pytest.raises(RuntimeError, match="SD-29"):
        make_service(
            clock,
            InMemoryAttemptStore(ACCOUNT_POLICY),
            InMemoryAttemptStore(IP_POLICY),
        )


def test_development_wiring_allows_in_memory_store() -> None:
    clock = FakeClock()
    service = make_service(
        clock,
        InMemoryAttemptStore(ACCOUNT_POLICY),
        InMemoryAttemptStore(IP_POLICY),
        environment="development",
    )
    assert isinstance(service, AuthService)


def test_feature_flag_off_blocks_building_login() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    with pytest.raises(FeatureDisabled, match="SD-04"):
        build_auth_service(
            users=FakeUsers([TEACHER]),
            sessions=FakeSessions(),
            hasher=FakeHasher(),
            mfa=FakeMfa(),
            session_id_factory=lambda: "sid-x",
            account_attempts=RedisAttemptStore(redis, ACCOUNT_POLICY),
            ip_attempts=RedisAttemptStore(redis, IP_POLICY, namespace="auth:ip"),
            environment="production",
            flags=AuthFeatureFlags(login_argon2=False),
            clock=clock,
        )


def test_feature_flags_from_env_defaults_off_and_parses_truthy() -> None:
    assert AuthFeatureFlags.from_env({}).login_argon2 is False
    assert AuthFeatureFlags.from_env({"QLKH_FEATURE_LOGIN_ARGON2": "1"}).login_argon2
    assert AuthFeatureFlags.from_env({"QLKH_FEATURE_LOGIN_ARGON2": "no"}).login_argon2 is False


# --- SD-29 điều kiện 3: hai worker chung ngưỡng ------------------------ #


def test_two_workers_share_threshold_lock_at_fifth_total_failure() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    account = RedisAttemptStore(redis, ACCOUNT_POLICY)
    ip_store = RedisAttemptStore(redis, IP_POLICY, namespace="auth:ip")
    worker_a = make_service(clock, account, ip_store, tag="a")
    worker_b = make_service(clock, account, ip_store, tag="b")

    workers = [worker_a, worker_b, worker_a, worker_b]
    for worker in workers:
        with pytest.raises(InvalidCredentials):
            worker.login(email="teacher@example.vn", password="sai", ip="203.0.113.1")

    # Lần sai thứ 5 tổng cộng (không phải thứ 5 trên MỖI worker) gây khóa.
    with pytest.raises(InvalidCredentials):
        worker_a.login(email="teacher@example.vn", password="sai", ip="203.0.113.1")

    with pytest.raises(AccountLocked) as exc:
        worker_b.login(email="teacher@example.vn", password="correct-horse", ip="203.0.113.1")
    assert exc.value.status == 429
    assert exc.value.retry_after == int(LOCKOUT_DURATION.total_seconds())


def test_successful_login_on_one_worker_resets_shared_counter() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    account = RedisAttemptStore(redis, ACCOUNT_POLICY)
    ip_store = RedisAttemptStore(redis, IP_POLICY, namespace="auth:ip")
    worker_a = make_service(clock, account, ip_store, tag="a")
    worker_b = make_service(clock, account, ip_store, tag="b")

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(InvalidCredentials):
            worker_a.login(email="teacher@example.vn", password="sai", ip="203.0.113.1")

    session = worker_b.login(email="teacher@example.vn", password="correct-horse", ip="203.0.113.1")
    assert session.user_id == TEACHER.user_id
    assert account.retry_after("teacher@example.vn", clock()) is None
