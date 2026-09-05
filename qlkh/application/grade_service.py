"""Dịch vụ điểm số (QLKH-008, REQ-006; lịch sử+thông báo QLKH-009, REQ-008).

Cài đặt POST /classes/{id}/grades, GET /students/{id}/grades và
GET /grades/{id}/history theo api-contract v1.3.0 (schema `Grade`,
`GradeUpsert`, `GradeHistoryEntry`). Không import ORM/HTTP: mọi phụ thuộc là
Protocol, adapter hạ tầng hiện thực sau.

Threat refs: QLKH-T-01 (rò rỉ điểm chéo học viên), QLKH-T-07 (giáo viên thao
tác lớp không phụ trách — BFLA/BOLA), QLKH-T-06 (sửa điểm đã công bố không để
lại vết — mục tiêu chính của QLKH-009).

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
- (QLKH-009) Mỗi lần sửa một điểm đã tồn tại (bất kể đã công bố hay chưa) ghi
  thêm một bản ghi lịch sử append-only (giá trị cũ/mới, actor, thời điểm
  server, lý do). Bảng lịch sử không có đường update/delete ở Protocol này,
  và bị chặn ở tầng DB (trigger, xem db/migrations/0004_grade_history.up.sql).
- (QLKH-009) Sửa một điểm ĐÃ công bố -> kích hoạt thông báo cho phụ huynh của
  học viên đó. Lỗi ở kênh thông báo không được làm hỏng việc ghi điểm/lịch sử
  (best-effort, xem docstring `NotificationSink`).
"""

from __future__ import annotations

from typing import Any, Protocol

from qlkh.application.repository_ports import (
    ClassRepository,
    GradeHistoryRepository,
    GradeRepository,
    NotificationSink,
)
from qlkh.domain.subject_context import SubjectContext

MIN_SCORE = 0
MAX_SCORE = 10


class AuditSink(Protocol):
    """Đích ghi audit log. Adapter hạ tầng hiện thực sau (stdout JSON/OTel)."""

    def record(self, event: str, **fields: Any) -> None: ...


class ClassNotFound(Exception):
    """Lớp không tồn tại HOẶC ngoài phạm vi cơ sở của phiên — 404."""


class ClassPermissionDenied(Exception):
    """Lớp tồn tại trong cơ sở nhưng ctx không có quyền phụ trách — 403.

    Cũng dùng lại cho "không có quyền xem lịch sử điểm" (403) — cùng bản chất
    BFLA: role/quan hệ không đủ, không phải "không tồn tại".
    """


class StudentNotFound(Exception):
    """Học viên không tồn tại HOẶC ngoài phạm vi ctx — không lộ tồn tại (404)."""


class InvalidGradeInput(ValueError):
    """Điểm ngoài [0, 10], student_id rỗng, hoặc thiếu reason khi sửa điểm đã
    công bố (422)."""


class GradeService:
    """Ca dùng nhập điểm, xem điểm và xem lịch sử, kiểm quyền theo cả hai
    trục (P3)."""

    def __init__(
        self,
        classes: ClassRepository,
        grades: GradeRepository,
        audit: AuditSink,
        history: GradeHistoryRepository,
        notifier: NotificationSink,
    ) -> None:
        self._classes = classes
        self._grades = grades
        self._audit = audit
        self._history = history
        self._notifier = notifier

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
        was_published = bool(existing is not None and existing.get("published"))
        has_reason = bool(reason and reason.strip())
        if was_published and not has_reason:
            raise InvalidGradeInput("reason bắt buộc khi sửa điểm đã công bố")

        record = self._grades.upsert(
            ctx,
            class_id,
            student_id=student_id,
            score=score,
            publish=publish,
            reason=reason,
        )

        # (QLKH-009) Đây là một lần SỬA (đã có bản ghi trước) -> ghi lịch sử
        # append-only. Lần TẠO MỚI (existing is None) không có "giá trị cũ"
        # để so sánh nên không tạo lịch sử.
        if existing is not None:
            self._history.record(
                ctx,
                grade_id=record["id"],
                old_score=existing.get("score"),
                new_score=score,
                actor_id=ctx.user_id,
                reason=reason or "",
            )
            if was_published:
                # Điểm đã công bố bị sửa -> phụ huynh phải được báo. Kênh
                # thông báo là phụ thuộc ngoài (best-effort, có timeout/retry
                # riêng ở adapter) — không ném lỗi ra đây làm hỏng việc ghi
                # điểm/lịch sử đã thành công.
                self._notifier.notify_grade_revised(
                    ctx,
                    student_id=student_id,
                    class_id=class_id,
                    grade_id=record["id"],
                    old_score=existing.get("score"),
                    new_score=score,
                    reason=reason or "",
                )

        self._audit.record(
            "grade.upserted",
            actor_id=ctx.user_id,
            actor_role=ctx.role,
            class_id=class_id,
            student_id=student_id,
            published=record.get("published"),
            is_revision=existing is not None,
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

    # ------------------------------------------------------------------ #
    # GET /grades/{id}/history (QLKH-009, REQ-008)
    # ------------------------------------------------------------------ #
    def list_grade_history(self, ctx: SubjectContext, grade_id: str) -> list[dict[str, Any]]:
        """Lịch sử append-only của một điểm.

        Chỉ giáo viên/nhân viên/quản trị xem được lịch sử sửa điểm (đây là dữ
        liệu vận hành/audit nội bộ, không phải màn hình của phụ huynh — contract
        `/grades/{id}/history` chỉ khai báo 200/403, không có đường phụ huynh
        hợp lệ). `GradeHistoryRepository.list_for_grade` áp thêm bộ lọc P3
        theo cơ sở/lớp phụ trách của ctx; trả None nếu ngoài phạm vi -> 403
        (không lộ tồn tại của điểm/lớp nằm ngoài phạm vi qua kênh này).
        """
        if ctx.role not in ("teacher", "staff", "admin"):
            raise ClassPermissionDenied(f"role {ctx.role} không được xem lịch sử điểm")

        records = self._history.list_for_grade(ctx, grade_id)
        if records is None:
            raise ClassPermissionDenied(
                f"user {ctx.user_id} (role={ctx.role}) không có quyền xem lịch sử "
                f"của điểm {grade_id}"
            )
        return records
