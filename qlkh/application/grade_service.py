"""Dịch vụ điểm số (QLKH-008, REQ-006).

Cài đặt POST /classes/{id}/grades và GET /students/{id}/grades theo
api-contract v1.3.0 (schema `Grade`, `GradeUpsert`). Không import ORM/HTTP:
mọi phụ thuộc là Protocol, adapter hạ tầng hiện thực sau.

Threat refs: QLKH-T-01 (rò rỉ điểm chéo học viên), QLKH-T-07 (giáo viên thao
tác lớp không phụ trách — BFLA/BOLA).

Quy tắc cốt lõi (Gherkin của ticket):
- Kiểm quyền theo CẢ HAI trục (P3): trục cơ sở (branch_id lấy từ ctx, không
  từ tham số client) và trục quan hệ (giáo viên phải phụ trách đúng lớp,
  phụ huynh chỉ xem được con mình).
- `POST /classes/{id}/grades`: dùng lại đúng phân biệt lỗi của
  `ClassService`/`AttendanceService`:
  * Lớp không tồn tại hoặc ngoài cơ sở của phiên -> 404 (không lộ tồn tại).
  * Lớp tồn tại trong cơ sở nhưng giáo viên không phụ trách -> 403.
- `GET /students/{id}/grades`: học viên không tồn tại hoặc ngoài phạm vi ctx
  (kể cả "phụ huynh A xem học viên B không phải con mình") -> 404, KHÔNG lộ
  sự tồn tại của học viên B (không phải 403).
- Trạng thái công bố điểm: phụ huynh CHỈ thấy các bản ghi có `published=True`;
  bản ghi chưa công bố hoàn toàn không xuất hiện trong response của phụ
  huynh (không phải trả kèm cờ ẩn). Giáo viên/nhân viên/quản trị xem được cả
  điểm chưa công bố (cần để quản lý/chỉnh sửa).
- Sửa một điểm ĐÃ công bố bắt buộc phải có `reason` (audit ai/khi nào/vì sao
  đổi điểm đã công khai) -> thiếu `reason` là 422.
"""

from __future__ import annotations

from typing import Any, Protocol

from qlkh.application.repository_ports import ClassRepository, GradeRepository
from qlkh.domain.subject_context import SubjectContext

MIN_SCORE = 0
MAX_SCORE = 10


class AuditSink(Protocol):
    """Đích ghi audit log. Adapter hạ tầng hiện thực sau (stdout JSON/OTel)."""

    def record(self, event: str, **fields: Any) -> None: ...


class ClassNotFound(Exception):
    """Lớp không tồn tại HOẶC ngoài phạm vi cơ sở của phiên — 404."""


class ClassPermissionDenied(Exception):
    """Lớp tồn tại trong cơ sở nhưng ctx không có quyền phụ trách — 403."""


class StudentNotFound(Exception):
    """Học viên không tồn tại HOẶC ngoài phạm vi ctx — không lộ tồn tại (404)."""


class InvalidGradeInput(ValueError):
    """Điểm ngoài [0, 10], student_id rỗng, hoặc thiếu reason khi sửa điểm đã
    công bố (422)."""


class GradeService:
    """Ca dùng nhập điểm và xem điểm, kiểm quyền theo cả hai trục (P3)."""

    def __init__(
        self,
        classes: ClassRepository,
        grades: GradeRepository,
        audit: AuditSink,
    ) -> None:
        self._classes = classes
        self._grades = grades
        self._audit = audit

    # ------------------------------------------------------------------ #
    # Kiểm quyền dùng lại cho POST /classes/{id}/grades
    # ------------------------------------------------------------------ #
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
    # POST /classes/{id}/grades
    # ------------------------------------------------------------------ #
    def upsert_grade(
        self,
        ctx: SubjectContext,
        class_id: str,
        *,
        student_id: str,
        score: float,
        publish: bool = False,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if not student_id or not str(student_id).strip():
            raise InvalidGradeInput("student_id không được rỗng")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise InvalidGradeInput("score phải là số")
        if score < MIN_SCORE or score > MAX_SCORE:
            raise InvalidGradeInput(f"score phải trong [{MIN_SCORE}, {MAX_SCORE}]")

        # Chỉ giáo viên/nhân viên/quản trị được nhập điểm; phụ huynh không có
        # đường nào tới đây (contract POST /classes/{id}/grades không dành
        # cho vai trò parent).
        if ctx.role not in ("teacher", "staff", "admin"):
            raise ClassPermissionDenied(f"role {ctx.role} không được nhập điểm")

        self._get_class_or_raise(ctx, class_id)

        existing = self._grades.get_existing(ctx, class_id, student_id)
        if existing is not None and existing.get("published") and not (reason and reason.strip()):
            raise InvalidGradeInput("reason bắt buộc khi sửa điểm đã công bố")

        record = self._grades.upsert(
            ctx,
            class_id,
            student_id=student_id,
            score=score,
            publish=publish,
            reason=reason,
        )
        self._audit.record(
            "grade.upserted",
            actor_id=ctx.user_id,
            actor_role=ctx.role,
            class_id=class_id,
            student_id=student_id,
            published=record.get("published"),
        )
        return record

    # ------------------------------------------------------------------ #
    # GET /students/{id}/grades
    # ------------------------------------------------------------------ #
    def list_student_grades(self, ctx: SubjectContext, student_id: str) -> list[dict[str, Any]]:
        """Phụ huynh chỉ xem được con mình; điểm chưa công bố không trả về.

        Kiểm quyền ở TRỤC QUAN HỆ + TRỤC CƠ SỞ cùng lúc qua
        `GradeRepository.get_student_ref` (tương đương `StudentRepository`,
        áp bộ lọc P3): trả None nếu học viên không tồn tại HOẶC ngoài phạm vi
        ctx (phụ huynh A xem học viên B -> None -> 404, không lộ tồn tại).
        """
        student_ref = self._grades.get_student_ref(ctx, student_id)
        if student_ref is None:
            raise StudentNotFound(student_id)

        records = self._grades.list_for_student(ctx, student_id)
        if ctx.role == "parent":
            # Điểm chưa công bố không được xuất hiện trong response của phụ
            # huynh — lọc hẳn ra, không trả kèm cờ "published=False".
            records = [r for r in records if r.get("published")]
        return records
