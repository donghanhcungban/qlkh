"""Port: giao diện repository bắt buộc ngữ cảnh chủ thể (P3).

Mọi repository truy cập bảng PII phải tuân giao diện này (ADR-004, REQ-009).
Infrastructure layer hiện thực; domain/application layer chỉ biết Protocol.

Không import ORM/HTTP/psycopg tại đây (fitness function kiểm bằng AST).
"""

from __future__ import annotations

from typing import Any, Protocol

from qlkh.domain.subject_context import SubjectContext


class StudentRepository(Protocol):
    """Giao diện truy cập bảng `students` — bắt buộc đi qua SubjectContext.

    Mọi phương thức nhận SubjectContext ở tham số đầu tiên (sau self).
    Không có phương thức nào cho phép truy vấn thô theo id mà không có ctx.
    """

    def get_by_id(
        self,
        ctx: SubjectContext,
        student_id: str,
    ) -> dict[str, Any] | None:
        """Lấy học viên theo id, áp bộ lọc ngữ cảnh.

        Trả None nếu không tìm thấy HOẶC nếu ctx không có quyền truy cập
        (không lộ sự tồn tại — contract /students/{id} trả 404 cả hai trường hợp).
        """
        ...

    def list_for_branch(
        self,
        ctx: SubjectContext,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Danh sách học viên trong branch của phiên; cursor-based pagination.

        Trả (data, next_cursor). branch_id LẤY TỪ ctx.allowed_branch_ids,
        không nhận từ tham số (ADR-004, T-02).
        """
        ...

    def create(
        self,
        ctx: SubjectContext,
        *,
        full_name: str,
        date_of_birth: str,
        parent_phone: str | None = None,
    ) -> dict[str, Any]:
        """Tạo học viên mới; branch_id gán từ ctx (không nhận từ client)."""
        ...

    def patch(
        self,
        ctx: SubjectContext,
        student_id: str,
        *,
        full_name: str | None = None,
        parent_phone: str | None = None,
    ) -> dict[str, Any] | None:
        """Cập nhật học viên theo allowlist; trả None nếu không có quyền."""
        ...
