"""Bộ đếm lần sai dùng chung trên session store P2 (Redis) — đóng SD-29 (a).

Không import client Redis cụ thể: adapter làm việc qua Protocol
`AtomicCounterClient`, thao tác đếm là nguyên tử (INCR + EXPIRE) nên ngưỡng
chống brute-force KHÔNG bị nhân theo số worker (giả định bảo mật #2 của
threat-model, T-04/T-13).

Ánh xạ sang lệnh Redis thật (adapter hạ tầng hiện thực Protocol này):
- `incr_with_expiry` → `INCR key` + `EXPIRE key ttl NX` (hoặc script Lua).
- `set_lock` → `SET key 1 EX ttl`.
- `lock_ttl` → `TTL key` (None nếu khóa không tồn tại).
- `delete` → `DEL`.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Protocol

from qlkh.domain.auth import AttemptPolicy


class AtomicCounterClient(Protocol):
    """Tập lệnh tối thiểu cần từ session store dùng chung."""

    def incr_with_expiry(self, key: str, ttl_seconds: int) -> int: ...

    def set_lock(self, key: str, ttl_seconds: int) -> None: ...

    def lock_ttl(self, key: str) -> int | None: ...

    def delete(self, *keys: str) -> None: ...


class RedisAttemptStore:
    """Hiện thực `AttemptStore` trên store dùng chung (`shared = True`).

    Khóa Redis không chứa PII thô: người gọi truyền sẵn khóa đã chuẩn hóa
    (email hạ chữ hoặc IP); tiền tố `namespace` tách bộ đếm tài khoản và IP.
    """

    shared = True

    def __init__(
        self,
        client: AtomicCounterClient,
        policy: AttemptPolicy,
        namespace: str = "auth:attempts",
    ) -> None:
        self._client = client
        self._policy = policy
        self._ns = namespace

    def _counter_key(self, key: str) -> str:
        return f"{self._ns}:c:{key}"

    def _lock_key(self, key: str) -> str:
        return f"{self._ns}:l:{key}"

    def _block_seconds(self, count: int) -> int:
        if self._policy.mode == "lock":
            return int(self._policy.lockout.total_seconds())
        over = max(0, count - self._policy.threshold)
        backoff = self._policy.backoff_base.total_seconds() * (2**over)
        return int(min(backoff, self._policy.backoff_max.total_seconds()))

    def register_failure(self, key: str, now: datetime) -> None:
        window = int(self._policy.window.total_seconds())
        count = self._client.incr_with_expiry(self._counter_key(key), window)
        if count >= self._policy.threshold:
            self._client.set_lock(self._lock_key(key), self._block_seconds(count))

    def retry_after(self, key: str, now: datetime) -> int | None:
        ttl = self._client.lock_ttl(self._lock_key(key))
        if ttl is None or ttl <= 0:
            return None
        return int(math.ceil(ttl))

    def reset(self, key: str) -> None:
        self._client.delete(self._counter_key(key), self._lock_key(key))
