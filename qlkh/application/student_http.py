"""Lớp chuyển đổi HTTP <-> StudentService (QLKH-005, REQ-003) — đóng phần
"chưa có HTTP controller/schema enforcement" của QLKH-T-03 (CVSS 7.5).

QUAN TRỌNG — phạm vi thật của module này: kho mã QLKH CHƯA chọn framework
HTTP (không có FastAPI/Flask/Starlette trong `pyproject.toml`; `tools/fitness.py`
mới chỉ CHẶN domain import các framework đó, chưa có ticket nào chọn và thêm
framework — đó là quyết định kiến trúc chưa tồn tại, ngoài phạm vi ticket
QLKH-005 và ngoài năng lực agent backend tự quyết. Vì vậy module này KHÔNG
đăng ký route thật; nó cung cấp lớp handler THUẦN PYTHON, không phụ thuộc
framework, nhận request đã được framework tương lai chuẩn hoá thành
(headers, query, raw_body: dict) và trả (status, body_dict) theo RFC 9457.
Khi có framework, việc còn lại chỉ là map request/response — không còn logic
nghiệp vụ hay validate nào nằm ở tầng framework.

Việc handler này đóng so với PR trước:
1. Enforce `additionalProperties: false` của `StudentPatch` Ở BIÊN HTTP: mọi
   khoá JSON KHÔNG thuộc `ALLOWED_PATCH_FIELDS ∪ FORBIDDEN_PATCH_FIELDS` (tức
   hoàn toàn lạ, không phải chỉ role/branch_id) bị từ chối 422 — khớp contract
   (StudentPatch additionalProperties:false) thay vì chỉ lặng lẽ bỏ qua ở tầng
   service như trước. role/branch_id/is_teacher vẫn đi theo nhánh "bỏ qua +
   audit" của Gherkin (không phải lỗi), các trường lạ khác (không nằm trong
   schema client biết) là 422 để bắt lỗi tích hợp sớm.
2. Map lỗi domain -> Problem Details (RFC 9457) đúng `type` đã khai trong
   contract (`Problem.type`), không lộ chi tiết nội bộ trong `detail`.
3. `AuditSink` production ghi log JSON có `trace_id`, không log thô body — bản
   ghi audit không chứa parent_phone; chỉ chứa tên trường bị từ chối.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from typing import Any

from qlkh.application.student_service import (
    ALLOWED_PATCH_FIELDS,
    FORBIDDEN_PATCH_FIELDS,
    InvalidPagination,
    InvalidStudentInput,
    StudentNotFound,
    StudentService,
)
from qlkh.domain.subject_context import SubjectContext

#: Trường mà client được PHÉP biết tên (dù bị từ chối) theo StudentPatch +
#: allowlist nghiệp vụ. Bất kỳ khoá nào khác là request sai schema (422).
_KNOWN_PATCH_KEYS: frozenset[str] = ALLOWED_PATCH_FIELDS | FORBIDDEN_PATCH_FIELDS

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


class JsonAuditSink:
    """`AuditSink` sản xuất: log JSON ra stdout, không PII thô (NFR-007).

    Chỉ ghi tên trường bị từ chối (`rejected_fields`) — không bao giờ ghi giá
    trị gửi lên (giá trị có thể là PII hoặc dữ liệu nhạy cảm nghiệp vụ).
    """

    def __init__(self, stream: Any = None, logger: logging.Logger | None = None) -> None:
        self._stream = stream or sys.stdout
        self._logger = logger

    def record(self, event: str, **fields: Any) -> None:
        payload = {"event": event, **fields}
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if self._logger is not None:
            self._logger.info(line)
        else:
            print(line, file=self._stream)


def _validate_patch_schema(raw_body: dict[str, Any]) -> list[str]:
    """Trường hoàn toàn lạ với schema (không có trong contract) -> 422."""
    return sorted(k for k in raw_body if k not in _KNOWN_PATCH_KEYS)


class StudentHttpHandlers:
    """Handler thuần Python cho 4 operation `/students*` — không phụ thuộc framework."""

    def __init__(self, service: StudentService) -> None:
        self._service = service

    def list_students(
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
        # `branch_id` KHÔNG được đọc từ query ở đây dù client có gửi — không có
        # nhánh code nào map query["branch_id"] vào cuộc gọi service (T-02).
        try:
            data, next_cursor = self._service.list_students(ctx, cursor=cursor, limit=limit)
        except InvalidPagination as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        return HttpResult(status=200, body={"data": data, "meta": {"next_cursor": next_cursor}})

    def get_student(self, ctx: SubjectContext, student_id: str) -> HttpResult:
        try:
            record = self._service.get_student(ctx, student_id)
        except StudentNotFound:
            return _problem(404, "not-found", "Not Found")
        return HttpResult(status=200, body=record)

    def create_student(self, ctx: SubjectContext, raw_body: dict[str, Any]) -> HttpResult:
        try:
            record = self._service.create_student(
                ctx,
                full_name=raw_body.get("full_name", ""),
                date_of_birth=raw_body.get("date_of_birth", ""),
                parent_phone=raw_body.get("parent_phone"),
            )
        except InvalidStudentInput as exc:
            return _problem(422, "unprocessable", "Unprocessable", str(exc))
        return HttpResult(status=201, body=record)

    def patch_student(
        self, ctx: SubjectContext, student_id: str, raw_body: dict[str, Any]
    ) -> HttpResult:
        unknown_fields = _validate_patch_schema(raw_body)
        if unknown_fields:
            # additionalProperties:false của StudentPatch — trường hoàn toàn lạ
            # với contract là lỗi tích hợp của client, khác với role/branch_id
            # (trường "biết" nhưng bị cấm ghi, theo Gherkin phải im lặng+audit).
            return _problem(
                422,
                "unprocessable",
                "Unprocessable",
                f"trường không thuộc schema: {', '.join(unknown_fields)}",
            )
        try:
            record = self._service.patch_student(ctx, student_id, raw_body)
        except StudentNotFound:
            return _problem(404, "not-found", "Not Found")
        return HttpResult(status=200, body=record)
