"""Lớp chuyển đổi HTTP <-> ConsentService (QLKH-011, REQ-010) — Problem
Details theo RFC 9457, cùng mẫu với `grade_http.py`.

Không có framework HTTP thật trong repo (xem docstring `student_http.py`);
handler ở đây thuần Python, nhận request đã chuẩn hoá (query/body dict) và
trả (status, body) — khi có framework, việc còn lại chỉ là map request/response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qlkh.application.consent_service import (
    ConsentNotFound,
    ConsentService,
    InvalidConsentInput,
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


class ConsentHttpHandlers:
    """Handler thuần Python cho POST /consents, DELETE /consents/{id},
    GET /students/{id}/consents."""

    def __init__(self, service: ConsentService) -> None:
        self._service = service

    def create_consent(self, ctx: SubjectContext, raw_body: dict[str, Any]) -> HttpResult:
        student_id = raw_body.get("student_id", "")
        purpose = raw_body.get("purpose")
        document_version = raw_body.get("document_version", "")
        try:
            record = self._service.create_consent(
                ctx,
                student_id=student_id,
                purpose=purpose,
                document_version=document_version,
            )
        except InvalidConsentInput as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        except StudentNotFound:
            return _problem(404, "not-found", "Not Found")
        return HttpResult(status=201, body=_to_response_body(record))

    def revoke_consent(self, ctx: SubjectContext, consent_id: str) -> HttpResult:
        try:
            self._service.revoke_consent(ctx, consent_id)
        except ConsentNotFound:
            return _problem(404, "not-found", "Not Found")
        return HttpResult(status=204, body={})

    def list_student_consents(self, ctx: SubjectContext, student_id: str) -> HttpResult:
        try:
            records = self._service.list_student_consents(ctx, student_id)
        except StudentNotFound:
            return _problem(404, "not-found", "Not Found")
        return HttpResult(status=200, body={"data": [_to_response_body(r) for r in records]})
