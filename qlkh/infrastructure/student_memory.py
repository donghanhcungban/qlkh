"""Repository `StudentRepository` in-memory dùng chung cho test và devserver.

ADR-0012 (architecture/QLKH/adr/ADR-0012-dev-adapter.md): CR-DEV-001 cần một
cách chạy `python -m qlkh.devserver` mà không cần CSDL thật. Thay vì viết một
implementation mới, module này CHUYỂN NGUYÊN VẸN logic của `FakeRepo` từng
định nghĩa cục bộ trong `tests/application/test_student_http.py` sang đây —
không đổi hành vi, chỉ đổi vị trí/tên để test và devserver dùng chung một
nguồn sự thật cho repository giả lập.

Đây KHÔNG PHẢI adapter production — không có ràng buộc toàn vẹn, không bền
vững qua restart. Dùng cho môi trường thử nghiệm/test theo đúng phạm vi đã
khai báo trong ADR-0012.
"""

from __future__ import annotations

from typing import Any

from qlkh.domain.subject_context import SubjectContext


class InMemoryStudentRepository:
    """Triển khai `StudentRepository` (qlkh/application/repository_ports.py)
    bằng một dict trong RAM — tôn trọng SubjectContext như repo thật phải làm.
    """

    def __init__(self, students: dict[str, dict[str, Any]] | None = None) -> None:
        self._students: dict[str, dict[str, Any]] = students if students is not None else {}

    def get_by_id(self, ctx: SubjectContext, student_id: str) -> dict[str, Any] | None:
        record = self._students.get(student_id)
        if record is None or not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def list_for_branch(
        self,
        ctx: SubjectContext,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        visible = [s for s in self._students.values() if ctx.can_access_branch(s["branch_id"])]
        visible.sort(key=lambda s: s["id"])
        return visible[:limit], None

    def create(
        self,
        ctx: SubjectContext,
        *,
        full_name: str,
        date_of_birth: str,
        parent_phone: str | None = None,
    ) -> dict[str, Any]:
        new_id = "new-1"
        record = {
            "id": new_id,
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "parent_phone": parent_phone,
            "branch_id": ctx.allowed_branch_ids[0],
        }
        self._students[new_id] = record
        return record

    def patch(
        self,
        ctx: SubjectContext,
        student_id: str,
        *,
        full_name: str | None = None,
        parent_phone: str | None = None,
    ) -> dict[str, Any] | None:
        record = self._students.get(student_id)
        if record is None or not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        if full_name is not None:
            record["full_name"] = full_name
        if parent_phone is not None:
            record["parent_phone"] = parent_phone
        return record
