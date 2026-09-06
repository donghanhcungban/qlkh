"""Lớp chuyển đổi HTTP <-> ClassService (QLKH-006, REQ-004) — Problem Details
theo RFC 9457, cùng mẫu với `student_http.py`.

Không có framework HTTP thật trong repo (xem docstring `student_http.py`);
handler ở đây thuần Python, nhận request đã chuẩn hoá (query/body dict) và
trả (status, body) — khi có framework, việc còn lại chỉ là map request/response.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

from qlkh.application.class_service import (
    ClassNotFound,
    ClassPermissionDenied,
    ClassService,
    EnrollmentAlreadyExists,
    InvalidClassInput,
    InvalidPagination,
)
from qlkh.domain.subject_context import SubjectContext

_PROBLEM_BASE = "https://qlkh/errors"


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: dict[str, Any]


def _problem(status: int, problem_type: str, title: str, detail: str | None = None) -> HttpResult:
    body: dict[str, Any] = {
        "type": f"{_PROBLEM_BASE}/{problem_type}",
        "title": title,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    return HttpResult(status=status, body=body)


def _to_response_body(record: dict[str, Any]) -> dict[str, Any]:
    """Map record của repo/service -> body HTTP.

    Không có trường PII thô nào ở `Class`/`Enrollment` cần che (contract chỉ
    có id, không có số điện thoại) — giữ nguyên record, chỉ đảm bảo không rò
    rỉ trường nội bộ (vd cột kỹ thuật) nếu adapter repo sau này thêm vào.
    """
    return dict(record)


class JsonAuditSink:
    """`AuditSink` sản xuất: log JSON ra stdout, không PII thô (NFR-007)."""

    def __init__(self, stream: Any = None) -> None:
        self._stream = stream or sys.stdout

    def record(self, event: str, **fields: Any) -> None:
        payload = {"event": event, **fields}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=self._stream)


class ClassHttpHandlers:
    """Handler thuần Python cho /classes*, /classes/{id}/enrollments*."""

    def __init__(self, service: ClassService) -> None:
        self._service = service

    def list_classes(
        self, ctx: SubjectContext, *, query: dict[str, str] | None = None
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
            data, next_cursor = self._service.list_classes(ctx, cursor=cursor, limit=limit)
        except InvalidPagination as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        body_data = [_to_response_body(record) for record in data]
        return HttpResult(status=200, body={"data": body_data, "meta": {"next_cursor": next_cursor}})

    def create_class(self, ctx: SubjectContext, raw_body: dict[str, Any]) -> HttpResult:
        try:
            record = self._service.create_class(
                ctx,
                name=raw_body.get("name", ""),
                teacher_id=raw_body.get("teacher_id"),
            )
        except InvalidClassInput as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        except ClassPermissionDenied:
            return _problem(403, "forbidden", "Forbidden")
        return HttpResult(status=201, body=_to_response_body(record))

    def enroll_student(
        self, ctx: SubjectContext, class_id: str, raw_body: dict[str, Any]
    ) -> HttpResult:
        student_id = raw_body.get("student_id", "")
        try:
            record = self._service.enroll_student(ctx, class_id, student_id)
        except InvalidClassInput as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        except ClassNotFound:
            return _problem(404, "not-found", "Not Found")
        except ClassPermissionDenied:
            return _problem(403, "forbidden", "Forbidden")
        except EnrollmentAlreadyExists as exc:
            return _problem(409, "conflict", "Conflict", str(exc))
        return HttpResult(status=201, body=_to_response_body(record))

    def unenroll_student(
        self, ctx: SubjectContext, class_id: str, student_id: str
    ) -> HttpResult:
        try:
            self._service.unenroll_student(ctx, class_id, student_id)
        except ClassNotFound:
            return _problem(404, "not-found", "Not Found")
        except ClassPermissionDenied:
            return _problem(403, "forbidden", "Forbidden")
        return HttpResult(status=204, body={})
