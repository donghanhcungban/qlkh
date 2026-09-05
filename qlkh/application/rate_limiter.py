"""Rate limiter cửa sổ cố định cho endpoint ghi (QLKH-007, REQ-005).

Dùng chung `AtomicCounterClient` (đã có ở `redis_counter_client.py`/`RedisAttemptStore`
cho SD-29): một lệnh nguyên tử INCR + EXPIRE-nếu-chưa-có-TTL, nên ngưỡng không bị
nhân theo số worker/replica (T-04, T-13, NFR-004/005).

Hai ngưỡng độc lập theo contract:
- 120 req/phút/tài khoản
- 600 req/phút/IP

Vượt ngưỡng -> 429 kèm Retry-After (số giây tới khi cửa sổ hiện tại hết hạn).
"""

from __future__ import annotations

from typing import Protocol

WINDOW_SECONDS = 60
DEFAULT_ACCOUNT_LIMIT = 120
DEFAULT_IP_LIMIT = 600


class AtomicCounterClient(Protocol):
    """Tập lệnh tối thiểu cần từ session store dùng chung (Redis)."""

    def incr_with_expiry(self, key: str, ttl_seconds: int) -> int: ...

    def lock_ttl(self, key: str) -> int | None: ...


class RateLimitExceeded(Exception):
    """Vượt ngưỡng rate limit; mang theo số giây chờ (Retry-After)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"vượt rate limit, thử lại sau {retry_after}s")
        self.retry_after = retry_after


class FixedWindowRateLimiter:
    """Bộ giới hạn tốc độ cửa sổ cố định trên store dùng chung.

    `check(key, limit)` tăng bộ đếm nguyên tử; nếu vượt `limit` trong cửa sổ
    hiện tại thì ném `RateLimitExceeded(retry_after)`. `retry_after` là ước
    lượng số giây còn lại của cửa sổ hiện tại (không cần chính xác tuyệt đối,
    chỉ cần là số dương hợp lý để client backoff — RFC 9110/9457).
    """

    def __init__(
        self,
        client: AtomicCounterClient,
        namespace: str = "ratelimit",
        window_seconds: int = WINDOW_SECONDS,
    ) -> None:
        self._client = client
        self._ns = namespace
        self._window = window_seconds

    def check(self, key: str, limit: int) -> None:
        count = self._client.incr_with_expiry(f"{self._ns}:{key}", self._window)
        if count > limit:
            retry_after = self._client.lock_ttl(f"{self._ns}:{key}")
            if retry_after is None or retry_after <= 0:
                retry_after = self._window
            raise RateLimitExceeded(retry_after)
