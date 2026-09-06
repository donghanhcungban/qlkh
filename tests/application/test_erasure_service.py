"""Test ErasureRequestService (QLKH-012, REQ-011).

Tiêu chí Gherkin của ticket QLKH-012 (phần tạo yêu cầu — thực thi xóa xem
`test_retention_job.py`):
  G1: Given yêu cầu xóa, When tạo, Then `due_at` = `requested_at` + 30 ngày,
      cả hai do SERVER tính (client không gửi được).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from qlkh.application.erasure_service import (
    ErasureNotAuthorized,
    ErasureRequestService,
    InvalidErasureInput,
)
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
BRANCH_B = "bbbbbbbb-0000-0000-0000-000000000002"
STUDENT_SON = "aaaaaaaa-0000-0000-0000-000000000010"
STUDENT_OTHER = "bbbbbbbb-0000-0000-0000-000000000020"

FIXED_NOW = datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC)


class FakeErasureRepo:
    def __init__(self, students: dict[str, dict[str, Any]]) -> None:
        self._students = students
        self.created: list[dict[str, Any]] = []
        self._seq = 0

    def get_student_ref(self, ctx, student_id):
        record = self._students.get(student_id)
        if record is None:
            return None
        if not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def create(self, ctx, *, subject_student_id, requested_at, due_at):
        self._seq += 1
        record = {
            "id": f"erasure-{self._seq}",
            "subject_student_id": subject_student_id,
            "requested_at": requested_at.isoformat(),
            "due_at": due_at.isoformat(),
            "status": "pending",
        }
        self.created.append(record)
        return dict(record)


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


@pytest.fixture
def ctx_parent() -> SubjectContext:
    return SubjectContext(
        user_id="parent-1",
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=(STUDENT_SON,),
    )


@pytest.fixture
def students() -> dict[str, dict[str, Any]]:
    return {
        STUDENT_SON: {"id": STUDENT_SON, "branch_id": BRANCH_A},
        STUDENT_OTHER: {"id": STUDENT_OTHER, "branch_id": BRANCH_B},
    }


def test_g1_due_at_la_requested_at_cong_30_ngay_do_server_tinh(ctx_parent, students):
    repo = FakeErasureRepo(students)
    audit = RecordingAudit()
    service = ErasureRequestService(repo, audit, now=lambda: FIXED_NOW)

    record = service.create_erasure_request(ctx_parent, subject_student_id=STUDENT_SON)

    assert record["requested_at"] == FIXED_NOW.isoformat()
    assert record["due_at"] == (FIXED_NOW + timedelta(days=30)).isoformat()
    assert record["status"] == "pending"
    event_names = [name for name, _ in audit.events]
    assert "erasure_requested" in event_names


def test_yeu_cau_hoc_vien_khong_lien_quan_tra_forbidden(ctx_parent, students):
    repo = FakeErasureRepo(students)
    service = ErasureRequestService(repo, RecordingAudit(), now=lambda: FIXED_NOW)

    with pytest.raises(ErasureNotAuthorized):
        service.create_erasure_request(ctx_parent, subject_student_id=STUDENT_OTHER)

    assert repo.created == []


def test_subject_student_id_rong_bi_tu_choi(ctx_parent, students):
    repo = FakeErasureRepo(students)
    service = ErasureRequestService(repo, RecordingAudit(), now=lambda: FIXED_NOW)

    with pytest.raises(InvalidErasureInput):
        service.create_erasure_request(ctx_parent, subject_student_id="")

    assert repo.created == []
