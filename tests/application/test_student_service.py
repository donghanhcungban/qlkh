"""Test StudentService (QLKH-005, REQ-003).

Tiêu chí Gherkin:
  G1: Given body chứa role hoặc branch_id, When PATCH /students/{id},
      Then trường đó bị bỏ qua và ghi audit.
  G2: Given giáo vụ cơ sở Quận 1, When GET /students (branch từ phiên),
      Then chỉ trả học viên Quận 1 (branch_id tham số client không tồn tại
      trong signature -> không thể lộ chéo cơ sở).
  G3: Given không truyền limit, When GET /students,
      Then trả tối đa 50 bản ghi kèm cursor; limit ngoài [1,200] bị từ chối.
"""

from __future__ import annotations

from typing import Any

import pytest

from qlkh.application.student_service import (
    InvalidPagination,
    InvalidStudentInput,
    StudentNotFound,
    StudentService,
)
from qlkh.domain.subject_context import SubjectContext

BRANCH_Q1 = "11111111-0000-0000-0000-000000000001"
BRANCH_THUDUC = "22222222-0000-0000-0000-000000000002"
STUDENT_A = "aaaaaaaa-0000-0000-0000-000000000010"
STUDENT_B = "bbbbbbbb-0000-0000-0000-000000000020"


class FakeStudentRepo:
    """Repository giả lập trong RAM — tôn trọng ctx như repo thật phải làm."""

    def __init__(self, students: dict[str, dict[str, Any]]) -> None:
        self._students = students
        self._seq = 0

    def get_by_id(self, ctx: SubjectContext, student_id: str) -> dict[str, Any] | None:
        record = self._students.get(student_id)
        if record is None:
            return None
        if not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def list_for_branch(
        self, ctx: SubjectContext, *, cursor: str | None = None, limit: int = 50
    ) -> tuple[list[dict[str, Any]], str | None]:
        visible = [
            s
            for s in self._students.values()
            if ctx.can_access_branch(s["branch_id"])
        ]
        visible.sort(key=lambda s: s["id"])
        page = visible[:limit]
        next_cursor = page[-1]["id"] if len(visible) > limit else None
        return page, next_cursor

    def create(
        self,
        ctx: SubjectContext,
        *,
        full_name: str,
        date_of_birth: str,
        parent_phone: str | None = None,
    ) -> dict[str, Any]:
        self._seq += 1
        new_id = f"new-{self._seq}"
        record = {
            "id": new_id,
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "parent_phone": parent_phone,
            "branch_id": ctx.allowed_branch_ids[0] if ctx.allowed_branch_ids else "unscoped",
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
        if record is None:
            return None
        if not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        if full_name is not None:
            record["full_name"] = full_name
        if parent_phone is not None:
            record["parent_phone"] = parent_phone
        return record


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


@pytest.fixture()
def students() -> dict[str, dict[str, Any]]:
    return {
        STUDENT_A: {"id": STUDENT_A, "full_name": "Bé A", "branch_id": BRANCH_Q1},
        STUDENT_B: {"id": STUDENT_B, "full_name": "Bé B", "branch_id": BRANCH_THUDUC},
    }


@pytest.fixture()
def repo(students: dict[str, dict[str, Any]]) -> FakeStudentRepo:
    return FakeStudentRepo(students)


@pytest.fixture()
def audit() -> FakeAudit:
    return FakeAudit()


@pytest.fixture()
def service(repo: FakeStudentRepo, audit: FakeAudit) -> StudentService:
    return StudentService(repo=repo, audit=audit)


@pytest.fixture()
def ctx_staff_q1() -> SubjectContext:
    return SubjectContext(user_id="staff-q1", role="staff", allowed_branch_ids=(BRANCH_Q1,))


@pytest.fixture()
def ctx_staff_thuduc() -> SubjectContext:
    return SubjectContext(
        user_id="staff-thuduc", role="staff", allowed_branch_ids=(BRANCH_THUDUC,)
    )


# ---------------------------------------------------------------------------
# G1 — chống mass assignment qua PATCH
# ---------------------------------------------------------------------------


class TestPatchMassAssignment:
    def test_role_bi_bo_qua_va_ghi_audit(
        self, service: StudentService, ctx_staff_q1: SubjectContext, audit: FakeAudit
    ):
        result = service.patch_student(
            ctx_staff_q1, STUDENT_A, {"full_name": "Bé A2", "role": "admin"}
        )
        assert result["full_name"] == "Bé A2"
        assert "role" not in result or result.get("role") != "admin"
        events = [e for e in audit.events if e[0] == "student.patch.field_ignored"]
        assert len(events) == 1
        assert events[0][1]["rejected_fields"] == ["role"]
        assert events[0][1]["student_id"] == STUDENT_A

    def test_branch_id_bi_bo_qua_va_ghi_audit(
        self, service: StudentService, ctx_staff_q1: SubjectContext, audit: FakeAudit
    ):
        result = service.patch_student(
            ctx_staff_q1, STUDENT_A, {"branch_id": BRANCH_THUDUC}
        )
        assert result["branch_id"] == BRANCH_Q1  # không đổi
        events = [e for e in audit.events if e[0] == "student.patch.field_ignored"]
        assert events[0][1]["rejected_fields"] == ["branch_id"]

    def test_is_teacher_bi_bo_qua_va_ghi_audit(
        self, service: StudentService, ctx_staff_q1: SubjectContext, audit: FakeAudit
    ):
        service.patch_student(ctx_staff_q1, STUDENT_A, {"is_teacher": True})
        events = [e for e in audit.events if e[0] == "student.patch.field_ignored"]
        assert events[0][1]["rejected_fields"] == ["is_teacher"]

    def test_truong_hop_le_khong_ghi_audit(
        self, service: StudentService, ctx_staff_q1: SubjectContext, audit: FakeAudit
    ):
        service.patch_student(ctx_staff_q1, STUDENT_A, {"full_name": "Bé A3"})
        assert audit.events == []

    def test_patch_khong_thay_ctx_khac_co_so_tra_404(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        with pytest.raises(StudentNotFound):
            service.patch_student(ctx_staff_q1, STUDENT_B, {"full_name": "Hack"})


# ---------------------------------------------------------------------------
# G2 — phạm vi theo cơ sở của phiên, không nhận branch_id từ client
# ---------------------------------------------------------------------------


class TestListScopedByBranch:
    def test_giao_vu_q1_chi_thay_hoc_vien_q1(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        data, _ = service.list_students(ctx_staff_q1)
        ids = [s["id"] for s in data]
        assert ids == [STUDENT_A]

    def test_giao_vu_thuduc_chi_thay_hoc_vien_thuduc(
        self, service: StudentService, ctx_staff_thuduc: SubjectContext
    ):
        data, _ = service.list_students(ctx_staff_thuduc)
        ids = [s["id"] for s in data]
        assert ids == [STUDENT_B]

    def test_khong_co_tham_so_branch_id_trong_signature(self, service: StudentService):
        """list_students không nhận branch_id — không có chỗ để client truyền."""
        import inspect

        sig = inspect.signature(service.list_students)
        assert "branch_id" not in sig.parameters

    def test_get_student_ngoai_pham_vi_tra_404_khong_lo_ton_tai(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        with pytest.raises(StudentNotFound):
            service.get_student(ctx_staff_q1, STUDENT_B)


# ---------------------------------------------------------------------------
# G3 — phân trang bắt buộc, mặc định 50, tối đa 200
# ---------------------------------------------------------------------------


class TestPagination:
    def test_khong_truyen_limit_dung_mac_dinh_50(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        data, cursor = service.list_students(ctx_staff_q1, cursor=None, limit=None)
        assert len(data) <= 50
        assert cursor is None or isinstance(cursor, str)

    def test_limit_qua_200_bi_tu_choi(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        with pytest.raises(InvalidPagination):
            service.list_students(ctx_staff_q1, limit=201)

    def test_limit_am_bi_tu_choi(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        with pytest.raises(InvalidPagination):
            service.list_students(ctx_staff_q1, limit=0)

    def test_limit_200_duoc_chap_nhan(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        data, _ = service.list_students(ctx_staff_q1, limit=200)
        assert isinstance(data, list)

    def test_nhieu_hon_limit_tra_next_cursor(
        self, repo: FakeStudentRepo, audit: FakeAudit, ctx_staff_q1: SubjectContext
    ):
        # Thêm nhiều học viên Q1 để vượt limit nhỏ
        for i in range(5):
            sid = f"extra-{i}"
            repo._students[sid] = {"id": sid, "full_name": f"Bé {i}", "branch_id": BRANCH_Q1}
        service = StudentService(repo=repo, audit=audit)
        data, cursor = service.list_students(ctx_staff_q1, limit=2)
        assert len(data) == 2
        assert cursor is not None


# ---------------------------------------------------------------------------
# create — validate biên, branch gán từ ctx
# ---------------------------------------------------------------------------


class TestCreateStudent:
    def test_tao_hoc_vien_gan_branch_tu_ctx(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        record = service.create_student(
            ctx_staff_q1, full_name="Bé Mới", date_of_birth="2018-01-01"
        )
        assert record["branch_id"] == BRANCH_Q1

    def test_full_name_rong_bi_tu_choi(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        with pytest.raises(InvalidStudentInput):
            service.create_student(ctx_staff_q1, full_name="  ", date_of_birth="2018-01-01")

    def test_date_of_birth_rong_bi_tu_choi(
        self, service: StudentService, ctx_staff_q1: SubjectContext
    ):
        with pytest.raises(InvalidStudentInput):
            service.create_student(ctx_staff_q1, full_name="Bé Mới", date_of_birth="")
