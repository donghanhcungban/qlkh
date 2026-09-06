"""Dịch vụ tạo yêu cầu xóa dữ liệu (QLKH-012, REQ-011, NFR-007).

Cài đặt `POST /erasure-requests` theo api-contract: 202 kèm `ErasureRequest`
(`due_at` = `requested_at` + 30 ngày — CẢ HAI do SERVER tính, client chỉ gửi
`subject_student_id`). Việc THỰC THI xóa (lan tới DB, log, backup, lưu trữ
lạnh) do `RetentionJob.run_erasure` (P4, xem `retention_job.py`) đảm nhận bất
đồng bộ — không chạy trong request (NFR-004/005: tác vụ dài không chạy trong
request; ở đây job chạy định kỳ, có SLA 30 ngày riêng).

Uỷ quyền theo contract (chỉ khai `403`, không khai `404`): người yêu cầu xóa
chỉ được làm vậy cho học viên có quan hệ với mình (phụ huynh: con mình;
staff/admin: học viên trong cơ sở phụ trách) — ngoài phạm vi -> 403, không
phải 404 (khác kiểu với /students/{id}, đây không phải đọc dữ liệu học viên
mà là một hành động, dùng ngữ nghĩa "không được phép làm việc này").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from qlkh.application.retention_job import ERASURE_SLA_DAYS
from qlkh.domain.subject_context import SubjectContext


class AuditSink(Protocol):
    """Đích ghi audit log (adapter hạ tầng hiện thực sau)."""

    def record(self, event: str, **fields: Any) -> None: ...


class ErasureRequestRepository(Protocol):
    """Port bắt buộc ngữ cảnh chủ thể (P3, ADR-004)."""

    def get_student_ref(
        self, ctx: SubjectContext, student_id: str
    ) -> dict[str, Any] | None:
        """Trả thông tin tối thiểu (id, branch_id) nếu ctx CÓ quan hệ với học
        viên này; None nếu không tồn tại HOẶC ngoài phạm vi ctx."""
        ...

    def create(
        self,
        ctx: SubjectContext,
        *,
        subject_student_id: str,
        requested_at: Any,
        due_at: Any,
    ) -> dict[str, Any]:
        """Tạo bản ghi yêu cầu xóa; `requested_at`/`due_at` do service truyền
        (đồng hồ server), không nhận từ client."""
        ...


class InvalidErasureInput(ValueError):
    """`subject_student_id` thiếu hoặc rỗng (422)."""


class ErasureNotAuthorized(Exception):
    """Người yêu cầu không có quan hệ với học viên (403, theo contract)."""


class ErasureRequestService:
    """Ca dùng tạo yêu cầu xóa; kiểm quan hệ qua P3 trước khi ghi nhận."""

    def __init__(
        self,
        repo: ErasureRequestRepository,
        audit: AuditSink,
        *,
        now: Any = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._now = now or (lambda: datetime.now(UTC))

    def create_erasure_request(
        self, ctx: SubjectContext, *, subject_student_id: str
    ) -> dict[str, Any]:
        if not subject_student_id or not str(subject_student_id).strip():
            raise InvalidErasureInput("subject_student_id không được rỗng")

        student_ref = self._repo.get_student_ref(ctx, subject_student_id)
        if student_ref is None:
            raise ErasureNotAuthorized(subject_student_id)

        requested_at = self._now()
        due_at = requested_at + timedelta(days=ERASURE_SLA_DAYS)
        record = self._repo.create(
            ctx,
            subject_student_id=subject_student_id,
            requested_at=requested_at,
            due_at=due_at,
        )
        self._audit.record(
            "erasure_requested",
            actor_id=ctx.user_id,
            subject_student_id=subject_student_id,
            request_id=record.get("id"),
            requested_at=requested_at.isoformat(),
            due_at=due_at.isoformat(),
        )
        return record
