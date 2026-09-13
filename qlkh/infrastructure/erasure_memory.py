"""Repository dùng cho `ErasureRequestService` in-memory, dùng chung cho test
và devserver.

ADR-0012 (architecture/QLKH/adr/ADR-0012-dev-adapter.md): CR-DEV-001 cần một
cách chạy `python -m qlkh.devserver` mà không cần CSDL thật. Module này
CHUYỂN NGUYÊN VẸN logic của `FakeRepo` từng định nghĩa cục bộ trong
`tests/application/test_erasure_http.py` sang đây — không đổi hành vi, chỉ
đổi vị trí/tên để test và devserver dùng chung một nguồn sự thật.

Đây KHÔNG PHẢI adapter production — không có ràng buộc toàn vẹn, không bền
vững qua restart. Dùng cho môi trường thử nghiệm/test theo đúng phạm vi đã
khai báo trong ADR-0012.
"""

from __future__ import annotations

from typing import Any

from qlkh.domain.subject_context import SubjectContext


class InMemoryErasureRepository:
    """Repo giả lập cho `ErasureRequestService`: tra cứu học viên (giới hạn
    theo ctx) và tạo yêu cầu xoá.
    """

    def __init__(self, students: dict[str, dict[str, Any]] | None = None) -> None:
        self._students: dict[str, dict[str, Any]] = students if students is not None else {}
        self._seq = 0

    def get_student_ref(self, ctx: SubjectContext, student_id: str) -> dict[str, Any] | None:
        record = self._students.get(student_id)
        if record is None or not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def create(
        self,
        ctx: SubjectContext,
        *,
        subject_student_id: str,
        requested_at: Any,
        due_at: Any,
    ) -> dict[str, Any]:
        self._seq += 1
        return {
            "id": f"erasure-{self._seq}",
            "subject_student_id": subject_student_id,
            "requested_at": requested_at.isoformat(),
            "due_at": due_at.isoformat(),
            "status": "pending",
        }
