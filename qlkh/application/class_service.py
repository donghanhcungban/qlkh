"""Dịch vụ lớp học và ghi danh (QLKH-006, REQ-004).

Cài đặt luồng GET/POST /classes, POST /classes/{id}/enrollments,
DELETE /classes/{id}/enrollments/{studentId} theo api-contract v1.2.0.
Không import ORM/HTTP: mọi phụ thuộc là Protocol, adapter hạ tầng hiện thực sau.

Threat refs: QLKH-T-07 (giáo viên thao tác lớp không phụ trách — BFLA/BOLA).

Quy tắc cốt lõi:
- `enrolled_at` KHÔNG BAO GIỜ nhận từ client; luôn do server sinh tại thời điểm
  ghi danh (đồng hồ server, `self._clock()`), đúng Gherkin của ticket.
- branch_id KHÔNG BAO GIỜ nhận từ tham số client; phạm vi cơ sở luôn lấy từ
  `SubjectContext` (ADR-004) và áp ở tầng repository (P3).
- Phân biệt hai lớp lỗi khi giáo viên thao tác một lớp:
  * Lớp không tồn tại hoặc ngoài cơ sở của phiên -> 404 (không lộ tồn tại).
  * Lớp tồn tại trong cơ sở nhưng giáo viên không được phân công phụ trách
    -> 403 (đúng Gherkin: "giáo viên không phụ trách lớp X -> 403").
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from qlkh.application.repository_ports import ClassRepository, EnrollmentConflict
from qlkh.domain.subject_context import SubjectContext

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuditSink(Protocol):
    """Đích ghi audit log. Adapter hạ tầng hiện thực sau (stdout JSON/OTel)."""

    def record(self, event: str, **fields: Any) -> None: ...


class ClassNotFound(Exception):
    """Lớp không tồn tại HOẶC ngoài phạm vi cơ sở của phiên — 404."""


class ClassPermissionDenied(Exception):
    """Lớp tồn tại trong cơ sở nhưng ctx không có quyền phụ trách — 403."""


class InvalidPagination(ValueError):
    """`limit` ngoài khoảng [1, MAX_LIMIT] (422)."""


class InvalidClassInput(ValueError):
    """Dữ liệu tạo lớp / ghi danh không hợp lệ (422)."""


class EnrollmentAlreadyExists(Exception):
    """Học viên đã ghi danh (còn active) — 409."""


class ClassService:
    """Ca dùng lớp học và ghi danh, kiểm quyền theo đối tượng lớp (BFLA/BOLA)."""

    def __init__(self, repo: ClassRepository, audit: AuditSink, clock: Any = utcnow) -> None:
        self._repo = repo
        self._audit = audit
        self._clock = clock

    # ------------------------------------------------------------------ #
    # GET /classes
    # ------------------------------------------------------------------ #
    def list_classes(
        self,
        ctx: SubjectContext,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        effective_limit = DEFAULT_LIMIT if limit is None else limit
        if effective_limit < 1 or effective_limit > MAX_LIMIT:
            raise InvalidPagination(
                f"limit phải trong [1, {MAX_LIMIT}], nhận {effective_limit}"
            )
        return self._repo.list_for_branch(ctx, cursor=cursor, limit=effective_limit)

    # ------------------------------------------------------------------ #
    # POST /classes
    # ------------------------------------------------------------------ #
    def create_class(
        self,
        ctx: SubjectContext,
        *,
        name: str,
        teacher_id: str | None = None,
    ) -> dict[str, Any]:
        if not name or not name.strip():
            raise InvalidClassInput("name không được rỗng")
        # Chỉ staff/admin được tạo lớp; giáo viên/phụ huynh không có quyền này
        # (contract createClass trả 403 — kiểm ở service, không phải mass-assign
        # branch_id: repository luôn gán branch_id từ ctx, không từ client).
        if ctx.role not in ("staff", "admin"):
            raise ClassPermissionDenied(
                f"role {ctx.role} không được tạo lớp"
            )
        return self._repo.create(ctx, name=name, teacher_id=teacher_id)

    # ------------------------------------------------------------------ #
    # Kiểm quyền chung cho các thao tác trên một lớp cụ thể
    # ------------------------------------------------------------------ #
    def _get_class_or_raise(self, ctx: SubjectContext, class_id: str) -> dict[str, Any]:
        record = self._repo.get_by_id(ctx, class_id)
        if record is None:
            # Không tồn tại HOẶC ngoài cơ sở của phiên — không phân biệt (404).
            raise ClassNotFound(class_id)
        if not ctx.can_access_class(class_id, record["branch_id"]):
            # Trong cơ sở nhưng không thuộc related_class_ids của phiên (giáo
            # viên không phụ trách lớp này) — Gherkin của ticket: 403.
            raise ClassPermissionDenied(
                f"user {ctx.user_id} (role={ctx.role}) không phụ trách lớp {class_id}"
            )
        return record

    # ------------------------------------------------------------------ #
    # POST /classes/{id}/enrollments
    # ------------------------------------------------------------------ #
    def enroll_student(
        self,
        ctx: SubjectContext,
        class_id: str,
        student_id: str,
    ) -> dict[str, Any]:
        if not student_id or not str(student_id).strip():
            raise InvalidClassInput("student_id không được rỗng")
        self._get_class_or_raise(ctx, class_id)
        # `enrolled_at` sinh tại đây, KHÔNG nhận tham số từ raw_body của client
        # ở tầng HTTP — chữ ký hàm này không có chỗ nào để truyền giá trị đó.
        enrolled_at = self._clock()
        try:
            record = self._repo.enroll(ctx, class_id, student_id, enrolled_at=enrolled_at)
        except EnrollmentConflict as exc:
            raise EnrollmentAlreadyExists(
                f"student {student_id} đã ghi danh lớp {class_id}"
            ) from exc
        self._audit.record(
            "class.enrollment.created",
            actor_id=ctx.user_id,
            actor_role=ctx.role,
            class_id=class_id,
            student_id=student_id,
            at=enrolled_at.isoformat() if hasattr(enrolled_at, "isoformat") else str(enrolled_at),
        )
        return record

    # ------------------------------------------------------------------ #
    # DELETE /classes/{id}/enrollments/{studentId}
    # ------------------------------------------------------------------ #
    def unenroll_student(self, ctx: SubjectContext, class_id: str, student_id: str) -> None:
        """Idempotent: không có gì để hủy vẫn không phải lỗi (204 ở tầng HTTP)."""
        self._get_class_or_raise(ctx, class_id)
        removed = self._repo.unenroll(ctx, class_id, student_id)
        self._audit.record(
            "class.enrollment.removed",
            actor_id=ctx.user_id,
            actor_role=ctx.role,
            class_id=class_id,
            student_id=student_id,
            removed=removed,
            at=self._clock().isoformat(),
        )
