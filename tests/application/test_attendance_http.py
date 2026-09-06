"""Test lớp handler HTTP-agnostic cho /classes/{id}/attendance* (QLKH-007,
REQ-005).

Tiêu chí Gherkin:
  G1: Given client gửi attendance_at lùi ngày, When POST attendance,
      Then giá trị bị bỏ qua.
  G3: Given vượt 120 req/phút, When gọi tiếp, Then 429 kèm Retry-After.

Không có framework HTTP thật trong repo (xem docstring `student_http.py`) nên
test gọi thẳng `AttendanceHttpHandlers` với request đã chuẩn hoá.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from qlkh.application.attendance_http import AttendanceHttpHandlers
from qlkh.application.attendance_service import AttendanceService
from qlkh.application.rate_limit import InMemoryRateLimiter, RateLimitPolicy
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"
CLASS_2 = "dddddddd-0000-0000-0000-000000000200"
STUDENT_A = "aaaaaaaa-0000-0000-0000-000000000010"
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
                "attendance_at": attendance_at.isoformat(),
            }
            self.records.append(record)
            out.append(record)
        return out

    def list_for_class(self, ctx, class_id, *, cursor=None, limit=50):
        visible = [r for r in self.records if r["class_id"] == class_id]
        return visible[:limit], None


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
def service(classes):
    return AttendanceService(
        classes=FakeClassRepo(classes),
        attendance=FakeAttendanceRepo(),
        audit=RecordingAudit(),
        clock=lambda: FIXED_NOW,
    )


def make_handlers(service, *, account_limit=120, ip_limit=600):
    account_limiter = InMemoryRateLimiter(
        RateLimitPolicy(limit=account_limit, window=timedelta(minutes=1))
    )
    ip_limiter = InMemoryRateLimiter(RateLimitPolicy(limit=ip_limit, window=timedelta(minutes=1)))
    return AttendanceHttpHandlers(
        service, account_limiter=account_limiter, ip_limiter=ip_limiter, clock=lambda: FIXED_NOW
    )


@pytest.fixture()
def handlers(service):
    return make_handlers(service)


@pytest.fixture()
def ctx_teacher_class1():
    return SubjectContext(
        user_id="teacher-1",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=(CLASS_1,),
    )


class TestBulkAttendanceHttp:
    def test_giao_vien_khong_phu_trach_lop_403(self, handlers, ctx_teacher_class1):
        result = handlers.bulk_attendance(
            ctx_teacher_class1,
            CLASS_2,
            {"entries": [{"student_id": STUDENT_A, "status": "present"}]},
            ip="10.0.0.1",
        )
        assert result.status == 403

    def test_diem_danh_thanh_cong_201_bo_qua_attendance_at_lui_ngay(
        self, handlers, ctx_teacher_class1
    ):
        result = handlers.bulk_attendance(
            ctx_teacher_class1,
            CLASS_1,
            {
                "entries": [
                    {"student_id": STUDENT_A, "status": "present", "attendance_at": BACKDATED}
                ]
            },
            ip="10.0.0.1",
        )
        assert result.status == 201
        assert result.body["data"][0]["attendance_at"] == FIXED_NOW.isoformat()
        assert result.body["data"][0]["attendance_at"] != BACKDATED

    def test_status_khong_hop_le_422(self, handlers, ctx_teacher_class1):
        result = handlers.bulk_attendance(
            ctx_teacher_class1,
            CLASS_1,
            {"entries": [{"student_id": STUDENT_A, "status": "xyz"}]},
            ip="10.0.0.1",
        )
        assert result.status == 422

    def test_lop_ngoai_pham_vi_404(self, handlers):
        other_ctx = SubjectContext(user_id="staff-2", role="staff", allowed_branch_ids=("khac",))
        result = handlers.bulk_attendance(
            other_ctx,
            CLASS_1,
            {"entries": [{"student_id": STUDENT_A, "status": "present"}]},
            ip="10.0.0.1",
        )
        assert result.status == 404


class TestRateLimit:
    def test_vuot_120_req_phut_tra_429_kem_retry_after(self, service, ctx_teacher_class1):
        handlers = make_handlers(service, account_limit=120)
        body = {"entries": [{"student_id": STUDENT_A, "status": "present"}]}
        for _ in range(120):
            result = handlers.bulk_attendance(ctx_teacher_class1, CLASS_1, body, ip="10.0.0.1")
            assert result.status == 201
        result = handlers.bulk_attendance(ctx_teacher_class1, CLASS_1, body, ip="10.0.0.1")
        assert result.status == 429
        assert result.body["type"] == "https://qlkh/errors/too-many-requests"
        assert "Retry-After" in result.headers
        assert int(result.headers["Retry-After"]) > 0

    def test_vuot_ip_limit_tra_429_du_khac_tai_khoan(self, service):
        handlers = make_handlers(service, account_limit=1_000_000, ip_limit=3)
        ctx1 = SubjectContext(
            user_id="teacher-1",
            role="teacher",
            allowed_branch_ids=(BRANCH_A,),
            related_class_ids=(CLASS_1,),
        )
        body = {"entries": [{"student_id": STUDENT_A, "status": "present"}]}
        for _ in range(3):
            result = handlers.bulk_attendance(ctx1, CLASS_1, body, ip="10.0.0.9")
            assert result.status == 201
        result = handlers.bulk_attendance(ctx1, CLASS_1, body, ip="10.0.0.9")
        assert result.status == 429

    def test_tai_khoan_khac_khong_bi_anh_huong_boi_gioi_han_cua_nhau(self, service):
        handlers = make_handlers(service, account_limit=1)
        ctx1 = SubjectContext(
            user_id="teacher-1",
            role="teacher",
            allowed_branch_ids=(BRANCH_A,),
            related_class_ids=(CLASS_1,),
        )
        ctx2 = SubjectContext(
            user_id="teacher-2",
            role="teacher",
            allowed_branch_ids=(BRANCH_A,),
            related_class_ids=(CLASS_1,),
        )
        body = {"entries": [{"student_id": STUDENT_A, "status": "present"}]}
        assert handlers.bulk_attendance(ctx1, CLASS_1, body, ip="10.0.0.1").status == 201
        assert handlers.bulk_attendance(ctx1, CLASS_1, body, ip="10.0.0.2").status == 429
        # teacher-2 vẫn còn hạn mức riêng dù cùng lớp/IP khác.
        assert handlers.bulk_attendance(ctx2, CLASS_1, body, ip="10.0.0.3").status == 201
