"""Rate limiter dùng chung trên session store P2 (Redis) — QLKH-007, REQ-005.

Cùng mẫu `attempt_store_redis.py`: đếm nguyên tử qua `AtomicCounterClient`
(một lệnh EVAL Lua ở `RedisScriptCounterClient`) nên ngưỡng 120/phút/tài
khoản và 600/phút/IP KHÔNG bị nhân theo số worker/replica (T-13).
"""

from __future__ import annotations

import math
from datetime import datetime

from qlkh.application.rate_limit import RateLimitPolicy
from qlkh.infrastructure.attempt_store_redis import AtomicCounterClient


class RedisRateLimiter:
    """Hiện thực `RateLimiter` (fixed-window) trên store dùng chung."""

    def __init__(
        self,
        client: AtomicCounterClient,
        policy: RateLimitPolicy,
        namespace: str,
    ) -> None:
        self._client = client
        self._policy = policy
        self._ns = namespace

    def _key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    def hit(self, key: str, now: datetime) -> int | None:
        window_seconds = int(self._policy.window.total_seconds())
        full_key = self._key(key)
        count = self._client.incr_with_expiry(full_key, window_seconds)
        if count <= self._policy.limit:
            return None
        ttl = self._client.lock_ttl(full_key)
        if ttl is None or ttl <= 0:
            return window_seconds
        return int(math.ceil(ttl))
