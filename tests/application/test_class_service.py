"""Test ClassService (QLKH-006, REQ-004).

Tiêu chí Gherkin:
  G1: Given giáo viên không phụ trách lớp X, When POST /classes/X/enrollments,
      Then 403.
  G2: Given client gửi enrolled_at, When ghi danh, Then server dùng đồng hồ
      server và bỏ giá trị client (chữ ký hàm không nhận enrolled_at từ đây).
  G3: Given học viên đã ghi danh, When ghi danh lại, Then 409 conflict.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from qlkh.application.class_service import (
    ClassNotFound,
    ClassPermissionDenied,
    ClassService,
    EnrollmentAlreadyExists,
    InvalidClassInput,
    InvalidPagination,
)
from qlkh.application.repository_ports import EnrollmentConflict
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
BRANCH_B = "bbbbbbbb-0000-0000-0000-000000000002"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"  # giáo viên phụ trách
CLASS_2 = "dddddddd-0000-0000-0000-000000000200"  # giáo viên KHÔNG phụ trách, cùng cơ sở
STUDENT_A = "aaaaaaaa-0000-0000-0000-000000000010"
STUDENT_B = "bbbbbbbb-0000-0000-0000-000000000020"

FIXED_NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC)


class FakeClassRepo:
    """Repository giả lập trong RAM — tôn trọng ctx như repo thật phải làm."""

    def __init__(self, classes: dict[str, dict[str, Any]]) -> None:
        self._classes = classes
        self._enrollments: dict[tuple[str, str], dict[str, Any]] = {}
        self._seq = 0

    def list_for_branch(self, ctx, *, cursor=None, limit=50):
        visible = [c for c in self._classes.values() if ctx.can_access_branch(c["branch_id"])]
        visible.sort(key=lambda c: c["id"])
        return visible[:limit], None

    def get_by_id(self, ctx, class_id):
        record = self._classes.get(class_id)
        if record is None:
            return None
        # Chỉ lọc theo branch — KHÔNG lọc theo lớp phụ trách (service quyết 403).
        if not ctx.can_access_branch(record["branch_id"]):
            return None
        return record

    def create(self, ctx, *, name, teacher_id=None):
        self._seq += 1
        new_id = f"new-class-{self._seq}"
        record = {
            "id": new_id,
            "name": name,
            "teacher_id": teacher_id,
            "branch_id": ctx.allowed_branch_ids[0] if ctx.allowed_branch_ids else "unscoped",
        }
        self._classes[new_id] = record
        return record

    def enroll(self, ctx, class_id, student_id, *, enrolled_at):
        key = (class_id, student_id)
        existing = self._enrollments.get(key)
        if existing is not None and existing["status"] == "active":
            raise EnrollmentConflict(f"{student_id} đã ghi danh {class_id}")
        record = {
            "id": f"enr-{class_id}-{student_id}",
            "class_id": class_id,
            "student_id": student_id,
            "enrolled_at": enrolled_at,
            "status": "active",
        }
        self._enrollments[key] = record
        return record

    def unenroll(self, ctx, class_id, student_id):
        key = (class_id, student_id)
        existing = self._enrollments.get(key)
        if existing is None or existing["status"] != "active":
            return False
        existing["status"] = "withdrawn"
        return True


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


@pytest.fixture()
def classes() -> dict[str, dict[str, Any]]:
    return {
        CLASS_1: {"id": CLASS_1, "name": "Lớp 1", "branch_id": BRANCH_A, "teacher_id": "teacher-1"},
        CLASS_2: {"id": CLASS_2, "name": "Lớp 2", "branch_id": BRANCH_A, "teacher_id": "teacher-2"},
    }


@pytest.fixture()
def repo(classes: dict[str, dict[str, Any]]) -> FakeClassRepo:
    return FakeClassRepo(classes)


@pytest.fixture()
def audit() -> FakeAudit:
    return FakeAudit()


@pytest.fixture()
def service(repo: FakeClassRepo, audit: FakeAudit) -> ClassService:
    return ClassService(repo=repo, audit=audit, clock=lambda: FIXED_NOW)


@pytest.fixture()
def ctx_teacher_class1() -> SubjectContext:
    """Giáo viên phụ trách CLASS_1, cùng cơ sở với CLASS_2 nhưng KHÔNG phụ trách."""
    return SubjectContext(
        user_id="teacher-1",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=(CLASS_1,),
    )


@pytest.fixture()
def ctx_staff_a() -> SubjectContext:
    return SubjectContext(user_id="staff-a", role="staff", allowed_branch_ids=(BRANCH_A,))


@pytest.fixture()
def ctx_staff_b() -> SubjectContext:
    return SubjectContext(user_id="staff-b", role="staff", allowed_branch_ids=(BRANCH_B,))


# ---------------------------------------------------------------------------
# G1 — giáo viên không phụ trách lớp -> 403
# ---------------------------------------------------------------------------


class TestEnrollPermission:
    def test_giao_vien_khong_phu_trach_lop_bi_403(
        self, service: ClassService, ctx_teacher_class1: SubjectContext
    ):
        with pytest.raises(ClassPermissionDenied):
            service.enroll_student(ctx_teacher_class1, CLASS_2, STUDENT_A)

    def test_giao_vien_phu_trach_lop_ghi_danh_thanh_cong(
        self, service: ClassService, ctx_teacher_class1: SubjectContext
    ):
        record = service.enroll_student(ctx_teacher_class1, CLASS_1, STUDENT_A)
        assert record["class_id"] == CLASS_1
        assert record["student_id"] == STUDENT_A

    def test_lop_ngoai_co_so_tra_404_khong_phai_403(
        self, service: ClassService, ctx_staff_b: SubjectContext
    ):
        """Lớp ở cơ sở khác (không thuộc phạm vi phiên) -> 404, không lộ tồn tại."""
        with pytest.raises(ClassNotFound):
            service.enroll_student(ctx_staff_b, CLASS_1, STUDENT_A)


# ---------------------------------------------------------------------------
# G2 — enrolled_at do server sinh, bỏ giá trị client
# ---------------------------------------------------------------------------


class TestEnrolledAtServerGenerated:
    def test_enroll_student_khong_nhan_tham_so_enrolled_at(
        self, service: ClassService, ctx_teacher_class1: SubjectContext
    ):
        """Chữ ký `enroll_student` không có chỗ để truyền enrolled_at của client
        — đây chính là cách bất biến này được đảm bảo (không có đường lách)."""
        import inspect

        sig = inspect.signature(service.enroll_student)
        assert "enrolled_at" not in sig.parameters

    def test_enrolled_at_dung_dong_ho_server(
        self, service: ClassService, ctx_teacher_class1: SubjectContext
    ):
        record = service.enroll_student(ctx_teacher_class1, CLASS_1, STUDENT_A)
        assert record["enrolled_at"] == FIXED_NOW


# ---------------------------------------------------------------------------
# G3 — ghi danh lại -> 409
# ---------------------------------------------------------------------------


class TestEnrollmentConflict:
    def test_ghi_danh_lai_hoc_vien_da_ghi_danh_409(
        self, service: ClassService, ctx_teacher_class1: SubjectContext
    ):
        service.enroll_student(ctx_teacher_class1, CLASS_1, STUDENT_A)
        with pytest.raises(EnrollmentAlreadyExists):
            service.enroll_student(ctx_teacher_class1, CLASS_1, STUDENT_A)

    def test_ghi_danh_lai_sau_khi_huy_khong_conflict(
        self, service: ClassService, ctx_teacher_class1: SubjectContext
    ):
        service.enroll_student(ctx_teacher_class1, CLASS_1, STUDENT_A)
        service.unenroll_student(ctx_teacher_class1, CLASS_1, STUDENT_A)
        record = service.enroll_student(ctx_teacher_class1, CLASS_1, STUDENT_A)
        assert record["status"] == "active"


# ---------------------------------------------------------------------------
# Các ca khác: tạo lớp, phân trang, hủy ghi danh idempotent
# ---------------------------------------------------------------------------


class TestCreateClass:
    def test_staff_tao_lop_thanh_cong(self, service: ClassService, ctx_staff_a: SubjectContext):
        record = service.create_class(ctx_staff_a, name="Lớp mới")
        assert record["branch_id"] == BRANCH_A

    def test_ten_lop_rong_bi_tu_choi(self, service: ClassService, ctx_staff_a: SubjectContext):
        with pytest.raises(InvalidClassInput):
            service.create_class(ctx_staff_a, name="   ")

    def test_giao_vien_khong_duoc_tao_lop(
        self, service: ClassService, ctx_teacher_class1: SubjectContext
    ):
        with pytest.raises(ClassPermissionDenied):
            service.create_class(ctx_teacher_class1, name="Lớp X")


class TestListClassesPagination:
    def test_limit_ngoai_khoang_bi_tu_choi(self, service: ClassService, ctx_staff_a: SubjectContext):
        with pytest.raises(InvalidPagination):
            service.list_classes(ctx_staff_a, limit=0)

    def test_khong_thay_lop_ngoai_co_so(self, service: ClassService, ctx_staff_b: SubjectContext):
        data, _ = service.list_classes(ctx_staff_b)
        assert data == []


class TestUnenrollIdempotent:
    def test_huy_ghi_danh_khong_ton_tai_khong_loi(
        self, service: ClassService, ctx_teacher_class1: SubjectContext
    ):
        # Không raise gì — idempotent, coi như đã hủy từ trước.
        service.unenroll_student(ctx_teacher_class1, CLASS_1, STUDENT_B)

    def test_giao_vien_khong_phu_trach_huy_ghi_danh_403(
        self, service: ClassService, ctx_teacher_class1: SubjectContext
    ):
        with pytest.raises(ClassPermissionDenied):
            service.unenroll_student(ctx_teacher_class1, CLASS_2, STUDENT_A)
