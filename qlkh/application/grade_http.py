"""Lớp chuyển đổi HTTP <-> GradeService (QLKH-008, REQ-006) — Problem Details
theo RFC 9457, cùng mẫu với `class_http.py`/`attendance_http.py`.

Không có framework HTTP thật trong repo (xem docstring `student_http.py`);
handler ở đây thuần Python, nhận request đã chuẩn hoá (query/body dict) và
trả (status, body) — khi có framework, việc còn lại chỉ là map request/response.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

from qlkh.application.grade_service import (
    ClassNotFound,
    ClassPermissionDenied,
    GradeService,
    InvalidGradeInput,
    StudentNotFound,
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
    return dict(record)


class JsonAuditSink:
    """`AuditSink` sản xuất: log JSON ra stdout, không PII thô (NFR-007)."""

    def __init__(self, stream: Any = None) -> None:
        self._stream = stream or sys.stdout

    def record(self, event: str, **fields: Any) -> None:
        payload = {"event": event, **fields}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=self._stream)


class GradeHttpHandlers:
    """Handler thuần Python cho POST /classes/{id}/grades, GET /students/{id}/grades."""

    def __init__(self, service: GradeService) -> None:
        self._service = service

    def upsert_grade(
        self, ctx: SubjectContext, class_id: str, raw_body: dict[str, Any]
    ) -> HttpResult:
        student_id = raw_body.get("student_id", "")
        score = raw_body.get("score")
        publish = bool(raw_body.get("publish", False))
        reason = raw_body.get("reason")
        try:
            record = self._service.upsert_grade(
                ctx,
                class_id,
                student_id=student_id,
                score=score,
                publish=publish,
                reason=reason,
            )
        except InvalidGradeInput as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        except ClassNotFound:
            return _problem(404, "not-found", "Not Found")
        except ClassPermissionDenied:
            return _problem(403, "forbidden", "Forbidden")
        return HttpResult(status=201, body=_to_response_body(record))

    def list_student_grades(self, ctx: SubjectContext, student_id: str) -> HttpResult:
        try:
            records = self._service.list_student_grades(ctx, student_id)
        except StudentNotFound:
            return _problem(404, "not-found", "Not Found")
        return HttpResult(status=200, body={"data": [_to_response_body(r) for r in records]})
