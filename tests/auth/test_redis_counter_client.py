"""Test adapter Redis thật + kênh phụ 429 (QLKH-004, REQ-001, SD-29b, SD-35).

Bằng chứng cần cho SD-29 (b): đặt bộ đếm và TTL là MỘT lệnh nguyên tử. Test
kiểm adapter chỉ phát đúng một lời gọi `EVAL` cho mỗi thao tác đếm/khóa, và
script Lua có đủ INCR + EXPIRE có điều kiện.

Bằng chứng cần cho SD-35: sau khi vượt ngưỡng, phản hồi cho email TỒN TẠI và
email KHÔNG tồn tại giống hệt nhau (cùng status, cùng problem).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from qlkh.application.auth_service import AuthService, InMemoryAttemptStore
from qlkh.domain.auth import (
    ACCOUNT_POLICY,
    IP_POLICY,
    MAX_FAILED_ATTEMPTS,
    AccountLocked,
    InvalidCredentials,
    Session,
    UserRecord,
)
from qlkh.infrastructure.attempt_store_redis import RedisAttemptStore
from qlkh.infrastructure.redis_counter_client import RedisScriptCounterClient

T0 = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)


class RecordingRedis:
    """Client kiểu redis-py tối thiểu: ghi lại lệnh đã phát."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, ...]] = []
        self.counter = 0
        self.ttl_value = -2

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        self.calls.append(("eval", script, numkeys, *keys_and_args))
        self.counter += 1
        return self.counter

    def ttl(self, key: str) -> int:
        self.calls.append(("ttl", key))
        return self.ttl_value

    def delete(self, *keys: str) -> int:
        self.calls.append(("delete", *keys))
        return len(keys)


def test_incr_and_expiry_is_one_atomic_eval() -> None:
    redis = RecordingRedis()
    client = RedisScriptCounterClient(redis)

    assert client.incr_with_expiry("k", 900) == 1

    assert len(redis.calls) == 1
    kind, script, numkeys, key, ttl = redis.calls[0]
    assert (kind, numkeys, key, ttl) == ("eval", 1, "k", 900)
    assert "INCR" in script and "EXPIRE" in script and "TTL" in script


def test_set_lock_is_one_atomic_eval() -> None:
    redis = RecordingRedis()
    RedisScriptCounterClient(redis).set_lock("l", 900)

    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "eval"
    assert redis.calls[0][3:] == ("l", 900)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(-2, None), (-1, None), (0, 0), (42, 42)],
)
def test_lock_ttl_maps_redis_sentinels(raw: int, expected: int | None) -> None:
    redis = RecordingRedis()
    redis.ttl_value = raw
    assert RedisScriptCounterClient(redis).lock_ttl("l") == expected


def test_delete_noop_when_no_keys() -> None:
    redis = RecordingRedis()
    client = RedisScriptCounterClient(redis)
    client.delete()
    assert redis.calls == []
    client.delete("a", "b")
    assert redis.calls == [("delete", "a", "b")]


def test_store_on_real_client_shape_locks_at_threshold() -> None:
    """`RedisAttemptStore` chạy được trên adapter client thật (duck-typed)."""
    redis = RecordingRedis()
    store = RedisAttemptStore(RedisScriptCounterClient(redis), ACCOUNT_POLICY)

    for _ in range(MAX_FAILED_ATTEMPTS):
        store.register_failure("teacher@example.vn", T0)

    # Lần thứ 5 đạt ngưỡng ⇒ có thêm lệnh đặt khóa.
    evals = [c for c in redis.calls if c[0] == "eval"]
    assert len(evals) == MAX_FAILED_ATTEMPTS + 1

    redis.ttl_value = 900
    assert store.retry_after("teacher@example.vn", T0) == 900


# --------------------------- SD-35 --------------------------------------- #


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class FakeHasher:
    def __init__(self) -> None:
        self.verify_calls = 0

    def hash(self, password: str) -> str:
        return f"h:{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        self.verify_calls += 1
        return password_hash == f"h:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


class FakeUsers:
    def __init__(self, users: list[UserRecord]) -> None:
        self._by_email = {u.email: u for u in users}

    def get_by_email(self, email: str) -> UserRecord | None:
        return self._by_email.get(email)

    def get_by_id(self, user_id: str) -> UserRecord | None:
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
        return 0


class FakeMfa:
    def verify(self, secret: str, code: str) -> bool:
        return False


EXISTING = UserRecord(
    user_id="u-1",
    email="teacher@example.vn",
    role="teacher",
    password_hash="h:correct-horse",
)


def _service(clock: FakeClock, hasher: FakeHasher) -> AuthService:
    return AuthService(
        users=FakeUsers([EXISTING]),
        sessions=FakeSessions(),
        hasher=hasher,
        mfa=FakeMfa(),
        session_id_factory=lambda: "sid",
        clock=clock,
        account_attempts=InMemoryAttemptStore(ACCOUNT_POLICY),
        ip_attempts=InMemoryAttemptStore(IP_POLICY),
    )


def _lock_out(service: AuthService, email: str) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(InvalidCredentials):
            service.login(email=email, password="sai", ip="10.0.0.1")


def test_locked_response_identical_for_existing_and_unknown_email() -> None:
    """SD-35: 429 không được tiết lộ tài khoản có tồn tại hay không."""
    responses = []
    for email in ("teacher@example.vn", "khong-ton-tai@example.vn"):
        clock = FakeClock()
        service = _service(clock, FakeHasher())
        _lock_out(service, email)
        with pytest.raises(AccountLocked) as exc:
            service.login(email=email, password="sai", ip="10.0.0.1")
        responses.append((exc.value.status, exc.value.problem, exc.value.retry_after))

    assert responses[0] == responses[1]


def test_kdf_runs_even_when_locked() -> None:
    """SD-35: nhánh bị khóa vẫn tốn đúng một lần KDF ⇒ không có kênh phụ thời gian."""
    clock = FakeClock()
    hasher = FakeHasher()
    service = _service(clock, hasher)
    _lock_out(service, "teacher@example.vn")
    before = hasher.verify_calls

    with pytest.raises(AccountLocked):
        service.login(email="teacher@example.vn", password="sai", ip="10.0.0.1")

    assert hasher.verify_calls == before + 1
