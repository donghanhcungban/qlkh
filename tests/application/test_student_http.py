"""Test lớp handler HTTP-agnostic cho /students* (QLKH-005, REQ-003, QLKH-T-03).

Không có framework HTTP thật trong repo (xem docstring module) nên test gọi
thẳng `StudentHttpHandlers` với request đã chuẩn hoá (query/body dict) — đúng
những gì một adapter framework tương lai sẽ truyền vào.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from qlkh.application.student_http import JsonAuditSink, StudentHttpHandlers
from qlkh.application.student_service import StudentService
from qlkh.domain.subject_context import SubjectContext

BRANCH_Q1 = "11111111-0000-0000-0000-000000000001"
STUDENT_A = "aaaaaaaa-0000-0000-0000-000000000010"


class FakeRepo:
    def __init__(self, students: dict[str, dict[str, Any]]) -> None:
        self._students = students

    def get_by_id(self, ctx, student_id):
        record = self._students.get(student_id)
        if record is None or not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def list_for_branch(self, ctx, *, cursor=None, limit=50):
        visible = [s for s in self._students.values() if ctx.can_access_branch(s["branch_id"])]
        visible.sort(key=lambda s: s["id"])
        return visible[:limit], None

    def create(self, ctx, *, full_name, date_of_birth, parent_phone=None):
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

    def patch(self, ctx, student_id, *, full_name=None, parent_phone=None):
        record = self._students.get(student_id)
        if record is None or not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        if full_name is not None:
            record["full_name"] = full_name
        if parent_phone is not None:
            record["parent_phone"] = parent_phone
        return record


class RecordingAudit:
    def __init__(self):
        self.events = []

    def record(self, event, **fields):
        self.events.append((event, fields))


@pytest.fixture()
def students():
    return {
        STUDENT_A: {
            "id": STUDENT_A,
            "full_name": "Bé A",
            "branch_id": BRANCH_Q1,
            "parent_phone": "+84901234567",
        }
    }


@pytest.fixture()
def audit():
    return RecordingAudit()


@pytest.fixture()
def handlers(students, audit):
    service = StudentService(repo=FakeRepo(students), audit=audit)
    return StudentHttpHandlers(service)


@pytest.fixture()
def ctx():
    return SubjectContext(user_id="staff-1", role="staff", allowed_branch_ids=(BRANCH_Q1,))


class TestPatchAdditionalPropertiesFalse:
    def test_truong_la_hoan_toan_bi_tu_choi_422(self, handlers, ctx):
        result = handlers.patch_student(ctx, STUDENT_A, {"full_name": "X", "hacker_field": "y"})
        assert result.status == 422
        assert result.body["type"] == "https://qlkh/errors/unprocessable"
        assert "hacker_field" in result.body["detail"]

    def test_role_khong_bi_422_ma_bi_bo_qua_va_audit(self, handlers, ctx, audit):
        result = handlers.patch_student(ctx, STUDENT_A, {"full_name": "X", "role": "admin"})
        assert result.status == 200
        assert result.body["full_name"] == "X"
        events = [e for e in audit.events if e[0] == "student.patch.field_ignored"]
        assert len(events) == 1
        assert events[0][1]["rejected_fields"] == ["role"]

    def test_branch_id_khong_bi_422_ma_bi_bo_qua(self, handlers, ctx):
        result = handlers.patch_student(ctx, STUDENT_A, {"branch_id": "khac"})
        assert result.status == 200

    def test_patch_ngoai_pham_vi_tra_404(self, handlers):
        other_ctx = SubjectContext(user_id="staff-2", role="staff", allowed_branch_ids=("khac",))
        result = handlers.patch_student(other_ctx, STUDENT_A, {"full_name": "X"})
        assert result.status == 404
        assert result.body["type"] == "https://qlkh/errors/not-found"


class TestListStudentsPagination:
    def test_khong_truyen_limit_dung_mac_dinh(self, handlers, ctx):
        result = handlers.list_students(ctx, query={})
        assert result.status == 200
        assert "next_cursor" in result.body["meta"]

    def test_limit_vuot_nguong_422(self, handlers, ctx):
        result = handlers.list_students(ctx, query={"limit": "999"})
        assert result.status == 422

    def test_limit_khong_phai_so_422(self, handlers, ctx):
        result = handlers.list_students(ctx, query={"limit": "abc"})
        assert result.status == 422

    def test_query_branch_id_bi_bo_qua_hoan_toan(self, handlers, ctx):
        """G2: client gửi branch_id qua query -> không có chỗ nào đọc nó."""
        result = handlers.list_students(ctx, query={"branch_id": "ThuDuc"})
        assert result.status == 200
        assert all(s["branch_id"] == BRANCH_Q1 for s in result.body["data"])


class TestGetStudent404KhongLoTonTai:
    def test_khong_ton_tai_hoac_ngoai_pham_vi_deu_404(self, handlers):
        other_ctx = SubjectContext(user_id="staff-2", role="staff", allowed_branch_ids=("khac",))
        result = handlers.get_student(other_ctx, STUDENT_A)
        assert result.status == 404


class TestParentPhoneMaskedTrenMoiResponse:
    """RISK-3/RISK-9/NFR-007: parent_phone thô KHÔNG bao giờ rời tầng HTTP."""

    def test_get_student_khong_co_parent_phone_tho(self, handlers, ctx):
        result = handlers.get_student(ctx, STUDENT_A)
        assert result.status == 200
        assert "parent_phone" not in result.body
        assert result.body["parent_phone_masked"] == "+84***567"

    def test_list_students_khong_co_parent_phone_tho(self, handlers, ctx):
        result = handlers.list_students(ctx, query={})
        assert result.status == 200
        for item in result.body["data"]:
            assert "parent_phone" not in item
            assert "parent_phone_masked" in item

    def test_create_student_khong_co_parent_phone_tho(self, handlers, ctx):
        result = handlers.create_student(
            ctx,
            {"full_name": "Bé B", "date_of_birth": "2015-01-01", "parent_phone": "+84987654321"},
        )
        assert result.status == 201
        assert "parent_phone" not in result.body
        assert result.body["parent_phone_masked"] == "+84***321"

    def test_patch_student_khong_co_parent_phone_tho(self, handlers, ctx):
        result = handlers.patch_student(ctx, STUDENT_A, {"parent_phone": "+84911111111"})
        assert result.status == 200
        assert "parent_phone" not in result.body
        assert result.body["parent_phone_masked"] == "+84***111"

    def test_khong_co_so_dien_thoai_thi_masked_la_none(self, handlers, ctx, students):
        students[STUDENT_A]["parent_phone"] = None
        result = handlers.get_student(ctx, STUDENT_A)
        assert result.status == 200
        assert result.body["parent_phone_masked"] is None


class TestJsonAuditSink:
    def test_ghi_json_hop_le(self):
        chunks: list[str] = []

        class Stream:
            def write(self, s):
                chunks.append(s)

            def flush(self):
                pass

        sink = JsonAuditSink(stream=Stream())
        sink.record(
            "student.patch.field_ignored",
            actor_id="staff-1",
            student_id=STUDENT_A,
            rejected_fields=["role", "branch_id"],
        )
        parsed = json.loads("".join(chunks))
        assert parsed["event"] == "student.patch.field_ignored"
        assert parsed["rejected_fields"] == ["role", "branch_id"]
