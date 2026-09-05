"""Rate limit theo cửa sổ cố định (QLKH-007, REQ-005, NFR-004/005).

Cùng mẫu với `AttemptStore` của `auth_service.py`: interface thuần Protocol,
adapter hạ tầng hiện thực sau (Redis, dùng chung mọi worker/replica — T-13).
Domain/application không phụ thuộc client Redis cụ thể.

Áp dụng cho POST /classes/{id}/attendance:
- 120 req/phút/tài khoản (khóa theo `user_id`).
- 600 req/phút/IP (khóa theo IP).
Vượt ngưỡng -> 429 kèm Retry-After (RFC 9457 Problem Details), theo contract.

Giới hạn đã biết: bản `InMemoryRateLimiter` chỉ hợp lệ cho một tiến trình
(dev/test), giống `InMemoryAttemptStore` (SD-29). Sản xuất PHẢI dùng adapter
dùng chung (`qlkh.infrastructure.rate_limiter_redis.RedisRateLimiter`); việc
enforce "không được chạy in-memory ở production" bằng wiring fail-fast (như
`auth_wiring.py` đã làm cho AttemptStore) nằm ngoài phạm vi ticket này và cần
được theo dõi như nợ kỹ thuật riêng nếu chưa có.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass(frozen=True)
class RateLimitPolicy:
    limit: int
    window: timedelta


class RateLimiter(Protocol):
    """Trả None nếu còn trong hạn mức; ngược lại số giây Retry-After."""

    def hit(self, key: str, now: datetime) -> int | None: ...


@dataclass
class _Window:
    count: int = 0
    window_started_at: datetime | None = None


class InMemoryRateLimiter:
    """Bộ đếm cửa sổ cố định trong RAM tiến trình — CHỈ dùng cho dev/test.

    Có trần số khóa và tự dọn mục cũ để không tăng bộ nhớ vô hạn theo số
    tài khoản/IP (ASVS 12.1), cùng kỹ thuật với `InMemoryAttemptStore`.
    """

    def __init__(self, policy: RateLimitPolicy, max_keys: int = 10_000) -> None:
        self._policy = policy
        self._max_keys = max_keys
        self._windows: OrderedDict[str, _Window] = OrderedDict()

    def _sweep(self, keep: str) -> None:
        while len(self._windows) > self._max_keys:
            oldest, _ = next(iter(self._windows.items()))
            if oldest == keep:
                self._windows.move_to_end(oldest)
                oldest, _ = next(iter(self._windows.items()))
            del self._windows[oldest]

    def hit(self, key: str, now: datetime) -> int | None:
        window = self._windows.get(key)
        if (
            window is None
            or window.window_started_at is None
            or now - window.window_started_at >= self._policy.window
        ):
            window = _Window(count=0, window_started_at=now)
        window.count += 1
        self._windows[key] = window
        self._windows.move_to_end(key)
        self._sweep(keep=key)
        if window.count <= self._policy.limit:
            return None
        remaining = window.window_started_at + self._policy.window - now
        return max(1, int(remaining.total_seconds()))
