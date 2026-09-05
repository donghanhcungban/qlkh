"""Test ConsentHttpHandlers (QLKH-011, REQ-010) — Problem Details RFC 9457."""

from __future__ import annotations

from typing import Any

from qlkh.application.consent_http import ConsentHttpHandlers
from qlkh.application.consent_service import ConsentService
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
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
            "granted_at": "2026-09-06T00:00:00Z",
            "status": "granted",
        }
        self._consents[cid] = record
        return dict(record)

    def get_by_id(self, ctx, consent_id):
        return self._consents.get(consent_id)

    def revoke(self, ctx, consent_id):
        record = self._consents.get(consent_id)
        if record is None or record["status"] == "withdrawn":
            return False
        record["status"] = "withdrawn"
        return True

    def list_for_student(self, ctx, student_id):
        return [dict(r) for r in self._consents.values() if r["student_id"] == student_id]

    def get_active_consent(self, ctx, student_id, purpose):
        for r in self._consents.values():
            if r["student_id"] == student_id and r["purpose"] == purpose and r["status"] == "granted":
                return dict(r)
        return None


class FakeAudit:
    def record(self, event, **fields):
        pass


def _parent_ctx() -> SubjectContext:
    return SubjectContext(
        user_id="parent-1",
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_student_ids=(STUDENT_SON,),
    )


def _handlers():
    repo = FakeConsentRepo({STUDENT_SON: {"id": STUDENT_SON, "branch_id": BRANCH_A}})
    service = ConsentService(repo, FakeAudit())
    return ConsentHttpHandlers(service), repo


def test_create_consent_201():
    handlers, _repo = _handlers()
    ctx = _parent_ctx()
    result = handlers.create_consent(
        ctx,
        {
            "student_id": STUDENT_SON,
            "purpose": "service_delivery",
            "document_version": "v2.1",
        },
    )
    assert result.status == 201
    assert result.body["document_version"] == "v2.1"


def test_create_consent_merged_purpose_422():
    handlers, _repo = _handlers()
    ctx = _parent_ctx()
    result = handlers.create_consent(
        ctx,
        {
            "student_id": STUDENT_SON,
            "purpose": ["service_delivery", "notification"],
            "document_version": "v2.1",
        },
    )
    assert result.status == 422
    assert result.body["type"] == "https://qlkh/errors/unprocessable"


def test_create_consent_student_out_of_scope_404():
    handlers, _repo = _handlers()
    ctx = _parent_ctx()
    result = handlers.create_consent(
        ctx,
        {
            "student_id": STUDENT_OTHER,
            "purpose": "service_delivery",
            "document_version": "v2.1",
        },
    )
    assert result.status == 404


def test_revoke_consent_204():
    handlers, _repo = _handlers()
    ctx = _parent_ctx()
    created = handlers.create_consent(
        ctx,
        {
            "student_id": STUDENT_SON,
            "purpose": "notification",
            "document_version": "v2.1",
        },
    )
    result = handlers.revoke_consent(ctx, created.body["id"])
    assert result.status == 204


def test_revoke_unknown_consent_still_204_idempotent():
    handlers, _repo = _handlers()
    ctx = _parent_ctx()
    result = handlers.revoke_consent(ctx, "unknown-id")
    assert result.status == 204


def test_list_student_consents_200():
    handlers, _repo = _handlers()
    ctx = _parent_ctx()
    handlers.create_consent(
        ctx,
        {
            "student_id": STUDENT_SON,
            "purpose": "notification",
            "document_version": "v2.1",
        },
    )
    result = handlers.list_student_consents(ctx, STUDENT_SON)
    assert result.status == 200
    assert len(result.body["data"]) == 1


def test_list_student_consents_out_of_scope_404():
    handlers, _repo = _handlers()
    ctx = _parent_ctx()
    result = handlers.list_student_consents(ctx, STUDENT_OTHER)
    assert result.status == 404
