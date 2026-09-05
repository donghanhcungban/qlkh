"""Lớp chuyển đổi HTTP <-> MaterialService (QLKH-010, REQ-007) — Problem
Details theo RFC 9457, cùng mẫu với `class_http.py`.

Không có framework HTTP thật trong repo (xem docstring `student_http.py`);
handler ở đây thuần Python, nhận request đã chuẩn hoá và trả (status, body,
headers) — khi có framework, việc còn lại chỉ là map request/response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qlkh.application.material_service import (
    ClassNotFound,
    ClassPermissionDenied,
    FileTooLarge,
    MaterialNotFound,
    MaterialPermissionDenied,
    MaterialService,
    UnsupportedFileType,
)
from qlkh.domain.subject_context import SubjectContext

_PROBLEM_BASE = "https://qlkh/errors"


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


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
    """Map record của repo/service -> body `Material`; không lộ `object_key`
    nội bộ (không phải trường trong contract, và cố ý không phơi ra để tránh
    lộ đường dẫn bucket)."""
    body = dict(record)
    body.pop("object_key", None)
    return body


class MaterialHttpHandlers:
    """Handler thuần Python cho /classes/{id}/materials, /materials/{id}/download."""

    def __init__(self, service: MaterialService) -> None:
        self._service = service

    def upload_material(
        self,
        ctx: SubjectContext,
        class_id: str,
        *,
        filename: str,
        content: bytes,
    ) -> HttpResult:
        try:
            record = self._service.upload_material(ctx, class_id, filename=filename, content=content)
        except ClassNotFound:
            return _problem(404, "not-found", "Not Found")
        except ClassPermissionDenied:
            return _problem(403, "forbidden", "Forbidden")
        except FileTooLarge as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        except UnsupportedFileType as exc:
            return _problem(
                415,
                "unsupported-media-type",
                "Unsupported Media Type",
                str(exc),
            )
        return HttpResult(status=201, body=_to_response_body(record))

    def download_material(self, ctx: SubjectContext, material_id: str) -> HttpResult:
        try:
            _material, signed_url = self._service.get_download_url(ctx, material_id)
        except MaterialNotFound:
            return _problem(404, "not-found", "Not Found")
        except MaterialPermissionDenied:
            return _problem(403, "forbidden", "Forbidden")
        return HttpResult(
            status=302,
            body={},
            headers={
                "Location": signed_url,
                "Content-Disposition": "attachment",
            },
        )
