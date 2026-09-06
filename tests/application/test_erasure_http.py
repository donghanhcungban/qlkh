"""Test ErasureHttpHandlers (QLKH-012) — mapping lỗi -> Problem Details."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from qlkh.application.erasure_http import ErasureHttpHandlers
from qlkh.application.erasure_service import ErasureRequestService
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
STUDENT_SON = "aaaaaaaa-0000-0000-0000-000000000010"
STUDENT_OTHER = "bbbbbbbb-0000-0000-0000-000000000020"
FIXED_NOW = datetime(2026, 9, 6, tzinfo=UTC)


class FakeRepo:
    def __init__(self, students: dict[str, dict[str, Any]]) -> None:
        self._students = students
        self._seq = 0

    def get_student_ref(self, ctx, student_id):
        record = self._students.get(student_id)
        if record is None or not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def create(self, ctx, *, subject_student_id, requested_at, due_at):
        self._seq += 1
        return {
            "id": f"erasure-{self._seq}",
            "subject_student_id": subject_student_id,
            "requested_at": requested_at.isoformat(),
            "due_at": due_at.isoformat(),
            "status": "pending",
        }


class NullAudit:
    def record(self, event, **fields):
        pass


@pytest.fixture
def ctx_parent() -> SubjectContext:
    return SubjectContext(
        user_id="parent-1",
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=(STUDENT_SON,),
    )


@pytest.fixture
def handlers() -> ErasureHttpHandlers:
    students = {STUDENT_SON: {"id": STUDENT_SON, "branch_id": BRANCH_A}}
    service = ErasureRequestService(FakeRepo(students), NullAudit(), now=lambda: FIXED_NOW)
    return ErasureHttpHandlers(service)


def test_tao_thanh_cong_tra_202(handlers, ctx_parent):
    result = handlers.create_erasure_request(ctx_parent, {"subject_student_id": STUDENT_SON})
    assert result.status == 202
    assert result.body["subject_student_id"] == STUDENT_SON


def test_khong_lien_quan_tra_403_problem_details(handlers, ctx_parent):
    result = handlers.create_erasure_request(ctx_parent, {"subject_student_id": STUDENT_OTHER})
    assert result.status == 403
    assert result.body["type"] == "https://qlkh/errors/forbidden"


def test_thieu_subject_student_id_tra_422(handlers, ctx_parent):
    result = handlers.create_erasure_request(ctx_parent, {})
    assert result.status == 422
    assert result.body["status"] == 422
