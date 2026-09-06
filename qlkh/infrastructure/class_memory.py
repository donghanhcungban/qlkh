"""Repository `ClassRepository` in-memory dùng chung cho test và devserver.

ADR-0012 (architecture/QLKH/adr/ADR-0012-dev-adapter.md): CR-DEV-001 cần một
cách chạy `python -m qlkh.devserver` mà không cần CSDL thật. Module này
CHUYỂN NGUYÊN VẸN logic của `FakeRepo` từng định nghĩa cục bộ trong
`tests/application/test_class_http.py` sang đây — không đổi hành vi, chỉ đổi
vị trí/tên để test và devserver dùng chung một nguồn sự thật.

Đây KHÔNG PHẢI adapter production — không có ràng buộc toàn vẹn, không bền
vững qua restart. Dùng cho môi trường thử nghiệm/test theo đúng phạm vi đã
khai báo trong ADR-0012.
"""

from __future__ import annotations

from typing import Any

from qlkh.application.repository_ports import EnrollmentConflict
from qlkh.domain.subject_context import SubjectContext


class InMemoryClassRepository:
    """Triển khai `ClassRepository` (qlkh/application/repository_ports.py)
    bằng dict trong RAM — tôn trọng SubjectContext như repo thật phải làm.
    """

    def __init__(self, classes: dict[str, dict[str, Any]] | None = None) -> None:
        self._classes: dict[str, dict[str, Any]] = classes if classes is not None else {}
        self._enrollments: dict[tuple[str, str], dict[str, Any]] = {}

    def list_for_branch(
        self,
        ctx: SubjectContext,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        visible = [c for c in self._classes.values() if ctx.can_access_branch(c["branch_id"])]
        return visible[:limit], None

    def get_by_id(self, ctx: SubjectContext, class_id: str) -> dict[str, Any] | None:
        record = self._classes.get(class_id)
        if record is None or not ctx.can_access_branch(record["branch_id"]):
            return None
        return record

    def create(
        self,
        ctx: SubjectContext,
        *,
        name: str,
        teacher_id: str | None = None,
    ) -> dict[str, Any]:
        branch_id = ctx.allowed_branch_ids[0] if ctx.allowed_branch_ids else "unscoped"
        record = {"id": "new-1", "name": name, "teacher_id": teacher_id, "branch_id": branch_id}
        self._classes["new-1"] = record
        return record

    def enroll(
        self,
        ctx: SubjectContext,
        class_id: str,
        student_id: str,
        *,
        enrolled_at: Any,
    ) -> dict[str, Any]:
        key = (class_id, student_id)
        if self._enrollments.get(key, {}).get("status") == "active":
            raise EnrollmentConflict("dup")
        record = {
            "id": f"enr-{class_id}-{student_id}",
            "class_id": class_id,
            "student_id": student_id,
            "enrolled_at": enrolled_at.isoformat(),
            "status": "active",
        }
        self._enrollments[key] = record
        return record

    def unenroll(self, ctx: SubjectContext, class_id: str, student_id: str) -> bool:
        key = (class_id, student_id)
        existing = self._enrollments.get(key)
        if existing is None or existing["status"] != "active":
            return False
        existing["status"] = "withdrawn"
        return True
