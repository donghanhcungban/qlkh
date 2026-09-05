"""Test ConsentService (QLKH-011, REQ-010).

Tiêu chí Gherkin:
  G1: Given phụ huynh đồng ý, When tạo bản ghi, Then lưu document_version và
      granted_at do SERVER sinh (không nhận từ client).
  G2: Given một ô đồng ý gộp nhiều mục đích, When gửi, Then 422.
  G3: Given đồng ý bị rút, When hệ thống xử lý theo mục đích đó, Then bị từ
      chối và ghi audit.
"""

from __future__ import annotations

from typing import Any

import pytest

from qlkh.application.consent_service import (
    ConsentService,
    ConsentWithdrawn,
    InvalidConsentInput,
    StudentNotFound,
)
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
BRANCH_B = "bbbbbbbb-0000-0000-0000-000000000002"
STUDENT_SON = "aaaaaaaa-0000-0000-0000-000000000010"
STUDENT_OTHER = "bbbbbbbb-0000-0000-0000-000000000020"


class FakeConsentRepo:
    def __init__(self, students: dict[str, dict[str, Any]]) -> None:
        self._students = students
        self._consents: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def get_student_ref(self, ctx, student_id):
        record = self._students.get(student_id)
        if record is None:
            return None
        if not ctx.can_access_student(student_id, record["branch_id"]):
            return None
        return record

    def create(self, ctx, *, student_id, purpose, document_version):
        self._seq += 1
        cid = f"consent-{self._seq}"
        record = {
            "id": cid,
            "student_id": student_id,
            "purpose": purpose,
            "document_version": document_version,
            "granted_at": "2026-09-06T00:00:00Z",  # server-sinh, cố định cho test
            "status": "granted",
        }
        self._consents[cid] = record
        return dict(record)

    def get_by_id(self, ctx, consent_id):
        record = self._consents.get(consent_id)
        if record is None:
            return None
        student = self._students.get(record["student_id"])
        if student is None or not ctx.can_access_student(record["student_id"], student["branch_id"]):
            return None
        return record

    def revoke(self, ctx, consent_id):
        record = self.get_by_id(ctx, consent_id)
        if record is None or record["status"] == "withdrawn":
            return False
        self._consents[consent_id]["status"] = "withdrawn"
        return True

    def list_for_student(self, ctx, student_id):
        return [dict(r) for r in self._consents.values() if r["student_id"] == student_id]

    def get_active_consent(self, ctx, student_id, purpose):
        for r in self._consents.values():
            if (
                r["student_id"] == student_id
                and r["purpose"] == purpose
                and r["status"] == "granted"
            ):
                return dict(r)
        return None


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event, **fields):
        self.events.append((event, fields))


def _parent_ctx() -> SubjectContext:
    return SubjectContext(
        user_id="parent-1",
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=(STUDENT_SON,),
    )


def _students() -> dict[str, dict[str, Any]]:
    return {
        STUDENT_SON: {"id": STUDENT_SON, "branch_id": BRANCH_A},
        STUDENT_OTHER: {"id": STUDENT_OTHER, "branch_id": BRANCH_B},
    }


def _service():
    repo = FakeConsentRepo(_students())
    audit = FakeAudit()
    return ConsentService(repo, audit), repo, audit


# ---------------------------------------------------------------------- #
# G1: lưu phiên bản văn bản và thời điểm server
# ---------------------------------------------------------------------- #
def test_g1_create_consent_stores_document_version_and_server_granted_at():
    service, _repo, audit = _service()
    ctx = _parent_ctx()

    record = service.create_consent(
        ctx,
        student_id=STUDENT_SON,
        purpose="service_delivery",
        document_version="v2.1",
    )

    assert record["document_version"] == "v2.1"
    assert record["granted_at"]  # do server sinh
    assert record["status"] == "granted"
    events = [e for e, _f in audit.events]
    assert "consent_granted" in events


def test_g1_create_consent_student_out_of_scope_is_404():
    service, _repo, _audit = _service()
    ctx = _parent_ctx()

    with pytest.raises(StudentNotFound):
        service.create_consent(
            ctx,
            student_id=STUDENT_OTHER,
            purpose="service_delivery",
            document_version="v2.1",
        )


# ---------------------------------------------------------------------- #
# G2: gộp nhiều mục đích -> 422
# ---------------------------------------------------------------------- #
def test_g2_merged_purpose_list_is_422():
    service, _repo, _audit = _service()
    ctx = _parent_ctx()

    with pytest.raises(InvalidConsentInput):
        service.create_consent(
            ctx,
            student_id=STUDENT_SON,
            purpose=["service_delivery", "notification"],
            document_version="v2.1",
        )


def test_g2_purpose_outside_enum_is_422():
    service, _repo, _audit = _service()
    ctx = _parent_ctx()

    with pytest.raises(InvalidConsentInput):
        service.create_consent(
            ctx,
            student_id=STUDENT_SON,
            purpose="marketing",
            document_version="v2.1",
        )


def test_g2_empty_purpose_is_422():
    service, _repo, _audit = _service()
    ctx = _parent_ctx()

    with pytest.raises(InvalidConsentInput):
        service.create_consent(
            ctx,
            student_id=STUDENT_SON,
            purpose="",
            document_version="v2.1",
        )


# ---------------------------------------------------------------------- #
# G3: đồng ý bị rút -> xử lý theo mục đích đó bị từ chối, có audit
# ---------------------------------------------------------------------- #
def test_g3_processing_denied_after_revoke_and_audited():
    service, repo, audit = _service()
    ctx = _parent_ctx()

    created = service.create_consent(
        ctx,
        student_id=STUDENT_SON,
        purpose="photo_publication",
        document_version="v2.1",
    )
    service.revoke_consent(ctx, created["id"])

    with pytest.raises(ConsentWithdrawn):
        service.assert_purpose_granted(
            ctx, student_id=STUDENT_SON, purpose="photo_publication"
        )

    events = [e for e, _f in audit.events]
    assert "consent_revoked" in events
    assert "consent_processing_denied" in events
    # audit ghi TRƯỚC khi raise -> đã có mặt trong events dù exception được ném


def test_g3_processing_allowed_when_granted_and_not_revoked():
    service, _repo, _audit = _service()
    ctx = _parent_ctx()
    service.create_consent(
        ctx,
        student_id=STUDENT_SON,
        purpose="notification",
        document_version="v2.1",
    )

    # Không ném lỗi -> coi như pass
    service.assert_purpose_granted(ctx, student_id=STUDENT_SON, purpose="notification")


def test_g3_processing_denied_when_never_granted():
    service, _repo, audit = _service()
    ctx = _parent_ctx()

    with pytest.raises(ConsentWithdrawn):
        service.assert_purpose_granted(
            ctx, student_id=STUDENT_SON, purpose="notification"
        )
    assert any(e == "consent_processing_denied" for e, _f in audit.events)


# ---------------------------------------------------------------------- #
# Rút lại đồng ý idempotent + list theo học viên
# ---------------------------------------------------------------------- #
def test_revoke_is_idempotent_no_error_on_repeat():
    service, _repo, audit = _service()
    ctx = _parent_ctx()
    created = service.create_consent(
        ctx,
        student_id=STUDENT_SON,
        purpose="notification",
        document_version="v2.1",
    )
    service.revoke_consent(ctx, created["id"])
    # Gọi lại lần 2 không được lỗi, không phát sinh thêm audit "consent_revoked"
    service.revoke_consent(ctx, created["id"])
    revoked_count = sum(1 for e, _f in audit.events if e == "consent_revoked")
    assert revoked_count == 1


def test_revoke_unknown_consent_is_noop_not_error():
    service, _repo, _audit = _service()
    ctx = _parent_ctx()
    # Không tồn tại -> vẫn không raise (204 idempotent ở tầng HTTP)
    service.revoke_consent(ctx, "unknown-id")


def test_list_student_consents_out_of_scope_is_404():
    service, _repo, _audit = _service()
    ctx = _parent_ctx()
    with pytest.raises(StudentNotFound):
        service.list_student_consents(ctx, STUDENT_OTHER)


def test_list_student_consents_returns_records_for_own_child():
    service, _repo, _audit = _service()
    ctx = _parent_ctx()
    service.create_consent(
        ctx,
        student_id=STUDENT_SON,
        purpose="service_delivery",
        document_version="v2.1",
    )
    records = service.list_student_consents(ctx, STUDENT_SON)
    assert len(records) == 1
    assert records[0]["purpose"] == "service_delivery"
