"""Lớp chuyển đổi HTTP <-> ErasureRequestService (QLKH-012, REQ-011) —
Problem Details theo RFC 9457, cùng mẫu với `consent_http.py`.

Không có framework HTTP thật trong repo; handler ở đây thuần Python, nhận
request đã chuẩn hoá (body dict) và trả (status, body).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qlkh.application.erasure_service import (
    ErasureNotAuthorized,
    ErasureRequestService,
    InvalidErasureInput,
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


class ErasureHttpHandlers:
    """Handler thuần Python cho POST /erasure-requests."""

    def __init__(self, service: ErasureRequestService) -> None:
        self._service = service

    def create_erasure_request(self, ctx: SubjectContext, raw_body: dict[str, Any]) -> HttpResult:
        subject_student_id = raw_body.get("subject_student_id", "")
        try:
            record = self._service.create_erasure_request(
                ctx, subject_student_id=subject_student_id
            )
        except InvalidErasureInput as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        except ErasureNotAuthorized:
            return _problem(403, "forbidden", "Forbidden")
        return HttpResult(status=202, body=dict(record))
