"""Test AttendanceService (QLKH-007, REQ-005).

Tiêu chí Gherkin:
  G1: Given client gửi attendance_at lùi ngày, When POST attendance,
      Then giá trị bị bỏ qua (server luôn dùng đồng hồ server).
  (BFLA/BOLA, cùng mẫu ClassService): giáo viên không phụ trách lớp -> 403;
  lớp ngoài cơ sở -> 404.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from qlkh.application.attendance_service import (
    AttendanceService,
    ClassNotFound,
    ClassPermissionDenied,
    InvalidAttendanceInput,
    InvalidPagination,
)
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
BRANCH_B = "bbbbbbbb-0000-0000-0000-000000000002"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"  # giáo viên phụ trách
CLASS_2 = "dddddddd-0000-0000-0000-000000000200"  # cùng cơ sở, KHÔNG phụ trách
STUDENT_A = "aaaaaaaa-0000-0000-0000-000000000010"
STUDENT_B = "bbbbbbbb-0000-0000-0000-000000000020"

FIXED_NOW = datetime(2026, 9, 5, 17, 30, 0, tzinfo=UTC)
BACKDATED = "2000-01-01T00:00:00Z"


class FakeClassRepo:
    def __init__(self, classes: dict[str, dict[str, Any]]) -> None:
        self._classes = classes

    def get_by_id(self, ctx, class_id):
        record = self._classes.get(class_id)
        if record is None or not ctx.can_access_branch(record["branch_id"]):
            return None
        return record

    # Các phương thức khác của ClassRepository không cần cho test này.
    def list_for_branch(self, ctx, *, cursor=None, limit=50):
        raise NotImplementedError

    def create(self, ctx, *, name, teacher_id=None):
        raise NotImplementedError

    def enroll(self, ctx, class_id, student_id, *, enrolled_at):
        raise NotImplementedError

    def unenroll(self, ctx, class_id, student_id):
        raise NotImplementedError


class FakeAttendanceRepo:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._seq = 0

    def bulk_insert(self, ctx, class_id, entries, *, attendance_at):
        out = []
        for entry in entries:
            self._seq += 1
            record = {
                "id": f"att-{self._seq}",
                "class_id": class_id,
                "student_id": entry["student_id"],
                "status": entry["status"],
                "attendance_at": attendance_at,
            }
            self.records.append(record)
            out.append(record)
        return out

    def list_for_class(self, ctx, class_id, *, cursor=None, limit=50):
        visible = [r for r in self.records if r["class_id"] == class_id]
        return visible[:limit], None


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
def class_repo(classes) -> FakeClassRepo:
    return FakeClassRepo(classes)


@pytest.fixture()
def attendance_repo() -> FakeAttendanceRepo:
    return FakeAttendanceRepo()


@pytest.fixture()
def audit() -> FakeAudit:
    return FakeAudit()


@pytest.fixture()
def service(class_repo, attendance_repo, audit) -> AttendanceService:
    return AttendanceService(
        classes=class_repo, attendance=attendance_repo, audit=audit, clock=lambda: FIXED_NOW
    )


@pytest.fixture()
def ctx_teacher_class1() -> SubjectContext:
    return SubjectContext(
        user_id="teacher-1",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=(CLASS_1,),
    )


class TestBulkAttendancePermission:
    def test_giao_vien_khong_phu_trach_lop_403(self, service, ctx_teacher_class1):
        with pytest.raises(ClassPermissionDenied):
            service.bulk_attendance(
                ctx_teacher_class1, CLASS_2, [{"student_id": STUDENT_A, "status": "present"}]
            )

    def test_lop_ngoai_pham_vi_404(self, service):
        other_ctx = SubjectContext(user_id="staff-2", role="staff", allowed_branch_ids=(BRANCH_B,))
        with pytest.raises(ClassNotFound):
            service.bulk_attendance(
                other_ctx, CLASS_1, [{"student_id": STUDENT_A, "status": "present"}]
            )


class TestBulkAttendanceServerClock:
    def test_attendance_at_luon_la_dong_ho_server(
        self, service, ctx_teacher_class1, attendance_repo
    ):
        records = service.bulk_attendance(
            ctx_teacher_class1, CLASS_1, [{"student_id": STUDENT_A, "status": "present"}]
        )
        assert records[0]["attendance_at"] == FIXED_NOW

    def test_client_gui_attendance_at_lui_ngay_bi_bo_qua(
        self, service, ctx_teacher_class1, attendance_repo
    ):
        """G1: entries kèm attendance_at lùi ngày -> giá trị đó không có đường
        nào lọt tới bản ghi; repo chỉ nhận attendance_at do service tính."""
        records = service.bulk_attendance(
            ctx_teacher_class1,
            CLASS_1,
            [
                {
                    "student_id": STUDENT_A,
                    "status": "present",
                    "attendance_at": BACKDATED,
                }
            ],
        )
        assert records[0]["attendance_at"] == FIXED_NOW
        assert records[0]["attendance_at"] != BACKDATED
        # Bản ghi trong repo cũng không hề chứa giá trị client gửi.
        assert all(r["attendance_at"] == FIXED_NOW for r in attendance_repo.records)

    def test_ca_lo_dung_chung_mot_moc_thoi_gian(self, service, ctx_teacher_class1):
        records = service.bulk_attendance(
            ctx_teacher_class1,
            CLASS_1,
            [
                {"student_id": STUDENT_A, "status": "present"},
                {"student_id": STUDENT_B, "status": "late"},
            ],
        )
        assert {r["attendance_at"] for r in records} == {FIXED_NOW}


class TestBulkAttendanceValidation:
    def test_entries_rong_422(self, service, ctx_teacher_class1):
        with pytest.raises(InvalidAttendanceInput):
            service.bulk_attendance(ctx_teacher_class1, CLASS_1, [])

    def test_entries_vuot_tran_422(self, service, ctx_teacher_class1):
        entries = [{"student_id": f"s-{i}", "status": "present"} for i in range(201)]
        with pytest.raises(InvalidAttendanceInput):
            service.bulk_attendance(ctx_teacher_class1, CLASS_1, entries)

    def test_status_khong_hop_le_422(self, service, ctx_teacher_class1):
        with pytest.raises(InvalidAttendanceInput):
            service.bulk_attendance(
                ctx_teacher_class1, CLASS_1, [{"student_id": STUDENT_A, "status": "unknown"}]
            )

    def test_thieu_student_id_422(self, service, ctx_teacher_class1):
        with pytest.raises(InvalidAttendanceInput):
            service.bulk_attendance(ctx_teacher_class1, CLASS_1, [{"status": "present"}])


class TestListAttendance:
    def test_giao_vien_khong_phu_trach_lop_403(self, service, ctx_teacher_class1):
        with pytest.raises(ClassPermissionDenied):
            service.list_attendance(ctx_teacher_class1, CLASS_2)

    def test_liet_ke_thanh_cong(self, service, ctx_teacher_class1):
        service.bulk_attendance(
            ctx_teacher_class1, CLASS_1, [{"student_id": STUDENT_A, "status": "present"}]
        )
        data, next_cursor = service.list_attendance(ctx_teacher_class1, CLASS_1)
        assert len(data) == 1
        assert next_cursor is None

    def test_limit_ngoai_khoang_422(self, service, ctx_teacher_class1):
        with pytest.raises(InvalidPagination):
            service.list_attendance(ctx_teacher_class1, CLASS_1, limit=0)
