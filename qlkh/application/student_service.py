"""Dịch vụ hồ sơ học viên (QLKH-005, REQ-003).

Cài đặt luồng GET/POST /students, GET/PATCH /students/{id} theo api-contract.
Không import ORM/HTTP: mọi phụ thuộc là Protocol, adapter hạ tầng hiện thực sau.

Threat refs: QLKH-T-02 (rò rỉ chéo cơ sở), QLKH-T-03 (mass assignment nâng
quyền qua endpoint hồ sơ).

Quy tắc cốt lõi:
- Mass assignment: `StudentPatch` chỉ cho phép `full_name`, `parent_phone`
  (đúng contract `additionalProperties: false`). Bất kỳ trường khác trong
  body (đặc biệt `role`, `branch_id`, `is_teacher`) đều bị BỎ QUA lặng lẽ với
  client (không lỗi 422 — theo Gherkin của ticket) nhưng được ghi audit.
- branch_id KHÔNG BAO GIỜ nhận từ tham số client (query hay path); phạm vi cơ
  sở luôn lấy từ `SubjectContext` (ADR-004) và áp ở tầng repository (P3).
- Phân trang bắt buộc: không truyền `limit` -> mặc định 50; `limit` phải
  trong [1, 200], ngoài khoảng bị từ chối (422 ở tầng HTTP).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from qlkh.application.repository_ports import StudentRepository
from qlkh.domain.subject_context import SubjectContext

#: Allowlist trường được ghi qua PATCH /students/{id} — khớp StudentPatch
#: (api-contract: additionalProperties: false).
ALLOWED_PATCH_FIELDS: frozenset[str] = frozenset({"full_name", "parent_phone"})

#: Trường không bao giờ được ghi qua endpoint hồ sơ, dù có mặt trong allowlist
#: của schema khác — chặn leo quyền (T-03).
FORBIDDEN_PATCH_FIELDS: frozenset[str] = frozenset({"role", "branch_id", "is_teacher"})

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuditSink(Protocol):
    """Đích ghi audit log. Adapter hạ tầng hiện thực sau (stdout JSON/OTel)."""

    def record(self, event: str, **fields: Any) -> None: ...


class StudentNotFound(Exception):
    """Không tồn tại HOẶC ngoài phạm vi ctx — không lộ sự tồn tại (404)."""


class InvalidPagination(ValueError):
    """`limit` ngoài khoảng [1, MAX_LIMIT] (422)."""


class InvalidStudentInput(ValueError):
    """Dữ liệu tạo/ sửa học viên không hợp lệ (422)."""


class StudentService:
    """Ca dùng CRUD học viên, chống mass assignment, phạm vi theo cơ sở."""

    def __init__(self, repo: StudentRepository, audit: AuditSink, clock: Any = utcnow) -> None:
        self._repo = repo
        self._audit = audit
        self._clock = clock

    # ------------------------------------------------------------------ #
    # GET /students
    # ------------------------------------------------------------------ #
    def list_students(
        self,
        ctx: SubjectContext,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Danh sách học viên trong phạm vi cơ sở của phiên.

        `branch_id` không phải tham số của thao tác này: phạm vi luôn lấy từ
        `ctx.allowed_branch_ids` (ADR-004). Nếu client gửi `branch_id` ở query
        string, tầng HTTP không map nó vào đây — không có chỗ để nhận.
        """
        effective_limit = DEFAULT_LIMIT if limit is None else limit
        if effective_limit < 1 or effective_limit > MAX_LIMIT:
            raise InvalidPagination(
                f"limit phải trong [1, {MAX_LIMIT}], nhận {effective_limit}"
            )
        return self._repo.list_for_branch(ctx, cursor=cursor, limit=effective_limit)

    # ------------------------------------------------------------------ #
    # GET /students/{id}
    # ------------------------------------------------------------------ #
    def get_student(self, ctx: SubjectContext, student_id: str) -> dict[str, Any]:
        record = self._repo.get_by_id(ctx, student_id)
        if record is None:
            raise StudentNotFound(student_id)
        return record

    # ------------------------------------------------------------------ #
    # POST /students
    # ------------------------------------------------------------------ #
    def create_student(
        self,
        ctx: SubjectContext,
        *,
        full_name: str,
        date_of_birth: str,
        parent_phone: str | None = None,
    ) -> dict[str, Any]:
        if not full_name or not full_name.strip():
            raise InvalidStudentInput("full_name không được rỗng")
        if not date_of_birth or not date_of_birth.strip():
            raise InvalidStudentInput("date_of_birth không được rỗng")
        return self._repo.create(
            ctx,
            full_name=full_name,
            date_of_birth=date_of_birth,
            parent_phone=parent_phone,
        )

    # ------------------------------------------------------------------ #
    # PATCH /students/{id}
    # ------------------------------------------------------------------ #
    def patch_student(
        self,
        ctx: SubjectContext,
        student_id: str,
        raw_body: dict[str, Any],
    ) -> dict[str, Any]:
        """Áp allowlist trước khi ghi; trường ngoài allowlist bị bỏ qua + audit.

        Gherkin của ticket: "body chứa role hoặc branch_id -> trường đó bị bỏ
        qua và ghi audit" — KHÔNG phải 422. Server không tin bất kỳ giá trị
        nhạy cảm nào từ client (role/branch_id/is_teacher), kể cả khi giá trị
        gửi lên trùng giá trị hiện tại.
        """
        rejected_fields = sorted(k for k in raw_body if k not in ALLOWED_PATCH_FIELDS)
        if rejected_fields:
            self._audit.record(
                "student.patch.field_ignored",
                actor_id=ctx.user_id,
                actor_role=ctx.role,
                student_id=student_id,
                rejected_fields=rejected_fields,
                at=self._clock().isoformat(),
            )

        allowed_kwargs = {k: v for k, v in raw_body.items() if k in ALLOWED_PATCH_FIELDS}
        record = self._repo.patch(ctx, student_id, **allowed_kwargs)
        if record is None:
            raise StudentNotFound(student_id)
        return record
