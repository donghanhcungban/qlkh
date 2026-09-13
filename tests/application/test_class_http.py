"""Test lớp handler HTTP-agnostic cho /classes* (QLKH-006, REQ-004).

Không có framework HTTP thật trong repo (xem docstring `student_http.py`) nên
test gọi thẳng `ClassHttpHandlers` với request đã chuẩn hoá.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qlkh.application.class_http import ClassHttpHandlers
from qlkh.application.class_service import ClassService
from qlkh.domain.subject_context import SubjectContext
from qlkh.infrastructure.class_memory import InMemoryClassRepository as FakeRepo

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"
CLASS_2 = "dddddddd-0000-0000-0000-000000000200"
STUDENT_A = "aaaaaaaa-0000-0000-0000-000000000010"
FIXED_NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC)


class RecordingAudit:
    def __init__(self):
        self.events = []

    def record(self, event, **fields):
        self.events.append((event, fields))


@pytest.fixture()
def classes():
    return {
        CLASS_1: {"id": CLASS_1, "name": "Lớp 1", "branch_id": BRANCH_A, "teacher_id": "teacher-1"},
        CLASS_2: {"id": CLASS_2, "name": "Lớp 2", "branch_id": BRANCH_A, "teacher_id": "teacher-2"},
    }


@pytest.fixture()
def audit():
    return RecordingAudit()


@pytest.fixture()
def handlers(classes, audit):
    service = ClassService(repo=FakeRepo(classes), audit=audit, clock=lambda: FIXED_NOW)
    return ClassHttpHandlers(service)


@pytest.fixture()
def ctx_teacher_class1():
    return SubjectContext(
        user_id="teacher-1",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=(CLASS_1,),
    )


@pytest.fixture()
def ctx_staff_a():
    return SubjectContext(user_id="staff-a", role="staff", allowed_branch_ids=(BRANCH_A,))


class TestEnrollStudentHttp:
    def test_giao_vien_khong_phu_trach_lop_403(self, handlers, ctx_teacher_class1):
        result = handlers.enroll_student(ctx_teacher_class1, CLASS_2, {"student_id": STUDENT_A})
        assert result.status == 403
        assert result.body["type"] == "https://qlkh/errors/forbidden"

    def test_ghi_danh_thanh_cong_201_bo_qua_enrolled_at_client(self, handlers, ctx_teacher_class1):
        result = handlers.enroll_student(
            ctx_teacher_class1,
            CLASS_1,
            {"student_id": STUDENT_A, "enrolled_at": "2000-01-01T00:00:00Z"},
        )
        assert result.status == 201
        # Client gửi enrolled_at giả mạo quá khứ -> server vẫn dùng đồng hồ server.
        assert result.body["enrolled_at"] == FIXED_NOW.isoformat()

    def test_ghi_danh_lai_409(self, handlers, ctx_teacher_class1):
        handlers.enroll_student(ctx_teacher_class1, CLASS_1, {"student_id": STUDENT_A})
        result = handlers.enroll_student(ctx_teacher_class1, CLASS_1, {"student_id": STUDENT_A})
        assert result.status == 409

    def test_lop_ngoai_pham_vi_404(self, handlers):
        other_ctx = SubjectContext(user_id="staff-2", role="staff", allowed_branch_ids=("khac",))
        result = handlers.enroll_student(other_ctx, CLASS_1, {"student_id": STUDENT_A})
        assert result.status == 404


class TestUnenrollStudentHttp:
    def test_huy_ghi_danh_thanh_cong_204(self, handlers, ctx_teacher_class1):
        handlers.enroll_student(ctx_teacher_class1, CLASS_1, {"student_id": STUDENT_A})
        result = handlers.unenroll_student(ctx_teacher_class1, CLASS_1, STUDENT_A)
        assert result.status == 204

    def test_huy_ghi_danh_khong_ton_tai_van_204_idempotent(self, handlers, ctx_teacher_class1):
        result = handlers.unenroll_student(ctx_teacher_class1, CLASS_1, STUDENT_A)
        assert result.status == 204

    def test_giao_vien_khong_phu_trach_huy_403(self, handlers, ctx_teacher_class1):
        result = handlers.unenroll_student(ctx_teacher_class1, CLASS_2, STUDENT_A)
        assert result.status == 403


class TestListAndCreateClassHttp:
    def test_list_classes_200(self, handlers, ctx_staff_a):
        result = handlers.list_classes(ctx_staff_a, query={})
        assert result.status == 200
        assert len(result.body["data"]) == 2

    def test_create_class_201(self, handlers, ctx_staff_a):
        result = handlers.create_class(ctx_staff_a, {"name": "Lớp mới"})
        assert result.status == 201

    def test_create_class_giao_vien_403(self, handlers, ctx_teacher_class1):
        result = handlers.create_class(ctx_teacher_class1, {"name": "Lớp X"})
        assert result.status == 403
