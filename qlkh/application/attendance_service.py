"""Dịch vụ điểm danh (QLKH-007, REQ-005).

Cài đặt POST /classes/{id}/attendance (bulk) và GET /classes/{id}/attendance
theo api-contract v1.2.0 (schema `AttendanceBulk`). Không import ORM/HTTP:
mọi phụ thuộc là Protocol, adapter hạ tầng hiện thực sau.

Threat refs: QLKH-T-07 (giáo viên thao tác lớp không phụ trách — BFLA/BOLA).

Quy tắc cốt lõi (Gherkin của ticket):
- `attendance_at` do server sinh tại thời điểm gọi (`self._clock()`), áp dụng
  chung cho cả lô. Không có tham số nào của `bulk_attendance` nhận
  attendance_at từ bên ngoài, và vòng lặp chuẩn hoá entry KHÔNG BAO GIỜ đọc
  khoá `attendance_at` từ entry thô của client — dù client cố gửi kèm giá trị
  lùi ngày, nó không có đường nào lọt tới bản ghi (cùng nguyên tắc với
  `enrolled_at` ở QLKH-006).
- Giáo viên chỉ điểm danh/xem điểm danh được lớp mình phụ trách; dùng lại
  đúng logic phân biệt lỗi của `ClassService`:
  * Lớp không tồn tại hoặc ngoài cơ sở của phiên -> 404 (không lộ tồn tại).
  * Lớp tồn tại trong cơ sở nhưng giáo viên không phụ trách -> 403.
- entries tối đa `MAX_ENTRIES` mục/lần gọi (khớp `AttendanceBulk.maxItems`
  trong contract) — thiếu student_id hoặc status không hợp lệ -> 422.
- Rate limit (120/phút/tài khoản, 600/phút/IP) và kịch bản tải 60 phiên đồng
  thời (NFR-004) là quan tâm của tầng HTTP/hạ tầng (`attendance_http.py`,
  `rate_limit.py`), không thuộc domain này.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from qlkh.application.repository_ports import AttendanceRepository, ClassRepository
from qlkh.domain.subject_context import SubjectContext

MAX_ENTRIES = 200
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
VALID_STATUSES: frozenset[str] = frozenset({"present", "absent", "late", "excused"})


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuditSink(Protocol):
    """Đích ghi audit log. Adapter hạ tầng hiện thực sau (stdout JSON/OTel)."""

    def record(self, event: str, **fields: Any) -> None: ...


class ClassNotFound(Exception):
    """Lớp không tồn tại HOẶC ngoài phạm vi cơ sở của phiên — 404."""


class ClassPermissionDenied(Exception):
    """Lớp tồn tại trong cơ sở nhưng ctx không có quyền phụ trách — 403."""


class InvalidAttendanceInput(ValueError):
    """entries rỗng/vượt trần, thiếu student_id, hoặc status không hợp lệ (422)."""


class InvalidPagination(ValueError):
    """`limit` ngoài khoảng [1, MAX_LIMIT] (422)."""


class AttendanceService:
    """Ca dùng điểm danh, kiểm quyền theo đối tượng lớp (BFLA/BOLA)."""

    def __init__(
        self,
        classes: ClassRepository,
        attendance: AttendanceRepository,
        audit: AuditSink,
        clock: Any = utcnow,
    ) -> None:
        self._classes = classes
        self._attendance = attendance
        self._audit = audit
        self._clock = clock

    def _get_class_or_raise(self, ctx: SubjectContext, class_id: str) -> dict[str, Any]:
        record = self._classes.get_by_id(ctx, class_id)
        if record is None:
            # Không tồn tại HOẶC ngoài cơ sở của phiên — không phân biệt (404).
            raise ClassNotFound(class_id)
        if not ctx.can_access_class(class_id, record["branch_id"]):
            # Trong cơ sở nhưng không phụ trách lớp này -> 403.
            raise ClassPermissionDenied(
                f"user {ctx.user_id} (role={ctx.role}) không phụ trách lớp {class_id}"
            )
        return record

    # ------------------------------------------------------------------ #
    # POST /classes/{id}/attendance
    # ------------------------------------------------------------------ #
    def bulk_attendance(
        self,
        ctx: SubjectContext,
        class_id: str,
        entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self._get_class_or_raise(ctx, class_id)

        if not entries:
            raise InvalidAttendanceInput("entries không được rỗng")
        if len(entries) > MAX_ENTRIES:
            raise InvalidAttendanceInput(f"entries vượt tối đa {MAX_ENTRIES} mục")

        normalized: list[dict[str, Any]] = []
        for raw in entries:
            student_id = raw.get("student_id")
            status = raw.get("status")
            if not student_id or not str(student_id).strip():
                raise InvalidAttendanceInput("student_id không được rỗng")
            if status not in VALID_STATUSES:
                raise InvalidAttendanceInput(f"status không hợp lệ: {status!r}")
            # CHỦ Ý không đọc raw.get("attendance_at"): dù client có gửi kèm
            # trường này (kể cả giá trị lùi ngày), nó bị bỏ qua hoàn toàn.
            normalized.append({"student_id": str(student_id), "status": status})

        attendance_at = self._clock()
        records = self._attendance.bulk_insert(
            ctx, class_id, normalized, attendance_at=attendance_at
        )
        self._audit.record(
            "attendance.bulk_recorded",
            class_id=class_id,
            actor_id=ctx.user_id,
            count=len(records),
        )
        return records

    # ------------------------------------------------------------------ #
    # GET /classes/{id}/attendance
    # ------------------------------------------------------------------ #
    def list_attendance(
        self,
        ctx: SubjectContext,
        class_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._get_class_or_raise(ctx, class_id)
        effective_limit = DEFAULT_LIMIT if limit is None else limit
        if effective_limit < 1 or effective_limit > MAX_LIMIT:
            raise InvalidPagination(
                f"limit phải trong [1, {MAX_LIMIT}], nhận {effective_limit}"
            )
        return self._attendance.list_for_class(
            ctx, class_id, cursor=cursor, limit=effective_limit
        )
