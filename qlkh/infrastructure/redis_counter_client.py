"""Adapter nối `AtomicCounterClient` với client Redis thật — đóng SD-29 (a) và (b).

Vì sao có tệp này: `RedisAttemptStore` trước đây chỉ được kiểm bằng fake, và
`INCR` rồi `EXPIRE` là HAI lệnh — nếu lệnh thứ hai hỏng thì bộ đếm hoặc không
bao giờ hết hạn (khóa vĩnh viễn người dùng hợp lệ) hoặc mất TTL (né được ngưỡng).
Ở đây mọi thao tác đếm/khóa là MỘT lời gọi `EVAL` script Lua, chạy nguyên tử
trong Redis (T-04, T-13, SD-29).

Không import gói `redis`: client được tiêm và chỉ cần thoả `RedisCommandClient`
(redis-py đồng bộ thoả sẵn). Nhờ vậy module không thêm phụ thuộc runtime nào
(liên quan nợ SD-04/SD-13 đang mở của platform/infra).
"""

from __future__ import annotations

from typing import Any, Protocol

#: INCR + đặt TTL chỉ khi khóa chưa có TTL, trong một lần thực thi nguyên tử.
INCR_WITH_EXPIRY_LUA = """
local v = redis.call('INCR', KEYS[1])
if redis.call('TTL', KEYS[1]) < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return v
"""

#: Đặt khóa kèm TTL trong một lệnh (SET key 1 EX ttl).
SET_LOCK_LUA = """
redis.call('SET', KEYS[1], '1', 'EX', ARGV[1])
return 1
"""


class RedisCommandClient(Protocol):
    """Tập lệnh tối thiểu của client Redis đồng bộ (redis-py thoả sẵn)."""

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...

    def ttl(self, key: str) -> int: ...

    def delete(self, *keys: str) -> Any: ...


class RedisScriptCounterClient:
    """Hiện thực `AtomicCounterClient` bằng script Lua trên Redis thật.

    Mọi lời gọi ra ngoài phải có timeout: cấu hình ở client được tiêm
    (`socket_timeout`), không đặt ở đây để tránh hai nơi cấu hình.
    """

    def __init__(self, client: RedisCommandClient) -> None:
        self._client = client

    def incr_with_expiry(self, key: str, ttl_seconds: int) -> int:
        return int(self._client.eval(INCR_WITH_EXPIRY_LUA, 1, key, int(ttl_seconds)))

    def set_lock(self, key: str, ttl_seconds: int) -> None:
        self._client.eval(SET_LOCK_LUA, 1, key, int(ttl_seconds))

    def lock_ttl(self, key: str) -> int | None:
        ttl = int(self._client.ttl(key))
        # redis-py: -2 khóa không tồn tại, -1 khóa tồn tại nhưng không có TTL.
        if ttl < 0:
            return None
        return ttl

    def delete(self, *keys: str) -> None:
        if keys:
            self._client.delete(*keys)
