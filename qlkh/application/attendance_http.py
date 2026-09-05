"""Lớp chuyển đổi HTTP <-> AttendanceService (QLKH-007, REQ-005) — Problem
Details theo RFC 9457, cùng mẫu với `class_http.py`.

Không có framework HTTP thật trong repo (xem docstring `student_http.py`);
handler ở đây thuần Python, nhận request đã chuẩn hoá (query/body dict,
định danh tài khoản/IP đã trích từ phiên/kết nối) và trả (status, body,
headers) — khi có framework, việc còn lại chỉ là map request/response.

Rate limit (contract, REQ-005): 120 req/phút/tài khoản, 600 req/phút/IP.
Kiểm TRƯỚC khi chạm tới service/domain — vượt ngưỡng trả 429 kèm header
`Retry-After`, không tốn công kiểm quyền hay ghi dữ liệu. Kiểm theo tài khoản
trước (đặc thù của endpoint điểm danh — Gherkin ticket), rồi theo IP.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from qlkh.application.attendance_service import (
    AttendanceService,
    ClassNotFound,
    ClassPermissionDenied,
    InvalidAttendanceInput,
    InvalidPagination,
)
from qlkh.application.rate_limit import RateLimiter
from qlkh.domain.subject_context import SubjectContext

_PROBLEM_BASE = "https://qlkh/errors"

#: Ngưỡng theo contract api-contract v1.2.0 (mô tả rate limit mặc định) và
#: scope ticket QLKH-007: 120 req/phút/tài khoản, 600 req/phút/IP.
ACCOUNT_RATE_LIMIT_PER_MINUTE = 120
IP_RATE_LIMIT_PER_MINUTE = 600


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


def _problem(
    status: int,
    problem_type: str,
    title: str,
    detail: str | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> HttpResult:
    body: dict[str, Any] = {
        "type": f"{_PROBLEM_BASE}/{problem_type}",
        "title": title,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    return HttpResult(status=status, body=body, headers=headers or {})


def _too_many_requests(retry_after_seconds: int) -> HttpResult:
    return _problem(
        429,
        "too-many-requests",
        "Too Many Requests",
        "Vượt hạn mức số lần gọi, thử lại sau",
        headers={"Retry-After": str(retry_after_seconds)},
    )


def _to_response_body(record: dict[str, Any]) -> dict[str, Any]:
    return dict(record)


class JsonAuditSink:
    """`AuditSink` sản xuất: log JSON ra stdout, không PII thô (NFR-007)."""

    def __init__(self, stream: Any = None) -> None:
        self._stream = stream or sys.stdout

    def record(self, event: str, **fields: Any) -> None:
        payload = {"event": event, **fields}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=self._stream)


class AttendanceHttpHandlers:
    """Handler thuần Python cho /classes/{id}/attendance*.

    `account_limiter`/`ip_limiter` là bắt buộc (không có giá trị mặc định
    "tắt rate limit"): endpoint điểm danh PHẢI luôn được bảo vệ theo cả hai
    trục tài khoản và IP (contract + Gherkin ticket).
    """

    def __init__(
        self,
        service: AttendanceService,
        account_limiter: RateLimiter,
        ip_limiter: RateLimiter,
        clock: Any = lambda: datetime.now(UTC),
    ) -> None:
        self._service = service
        self._account_limiter = account_limiter
        self._ip_limiter = ip_limiter
        self._clock = clock

    def _check_rate_limits(self, ctx: SubjectContext, ip: str) -> HttpResult | None:
        now = self._clock()
        retry_after = self._account_limiter.hit(ctx.user_id, now)
        if retry_after is not None:
            return _too_many_requests(retry_after)
        retry_after = self._ip_limiter.hit(ip, now)
        if retry_after is not None:
            return _too_many_requests(retry_after)
        return None

    def bulk_attendance(
        self,
        ctx: SubjectContext,
        class_id: str,
        raw_body: dict[str, Any],
        *,
        ip: str,
    ) -> HttpResult:
        limited = self._check_rate_limits(ctx, ip)
        if limited is not None:
            return limited

        entries = raw_body.get("entries")
        if not isinstance(entries, list):
            return _problem(422, "unprocessable", "Unprocessable", "entries phải là mảng")
        try:
            records = self._service.bulk_attendance(ctx, class_id, entries)
        except InvalidAttendanceInput as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        except ClassNotFound:
            return _problem(404, "not-found", "Not Found")
        except ClassPermissionDenied:
            return _problem(403, "forbidden", "Forbidden")
        return HttpResult(
            status=201,
            body={"data": [_to_response_body(r) for r in records]},
        )

    def list_attendance(
        self,
        ctx: SubjectContext,
        class_id: str,
        *,
        query: dict[str, str] | None = None,
    ) -> HttpResult:
        query = query or {}
        cursor = query.get("cursor")
        raw_limit = query.get("limit")
        limit: int | None = None
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                return _problem(422, "unprocessable", "Unprocessable", "limit phải là số nguyên")
        try:
            data, next_cursor = self._service.list_attendance(
                ctx, class_id, cursor=cursor, limit=limit
            )
        except InvalidPagination as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        except ClassNotFound:
            return _problem(404, "not-found", "Not Found")
        except ClassPermissionDenied:
            return _problem(403, "forbidden", "Forbidden")
        body_data = [_to_response_body(record) for record in data]
        return HttpResult(status=200, body={"data": body_data, "meta": {"next_cursor": next_cursor}})
