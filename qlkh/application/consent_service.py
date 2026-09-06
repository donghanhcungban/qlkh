"""Dịch vụ đồng ý của cha mẹ (QLKH-011, REQ-010).

Cài đặt `POST /consents`, `DELETE /consents/{id}`, `GET /students/{id}/consents`
theo api-contract (schema `Consent`). Không import ORM/HTTP: mọi phụ thuộc là
Protocol, adapter hạ tầng hiện thực sau.

Threat refs: QLKH-T-01/T-02 (rò rỉ chéo học viên/cơ sở — P3, ADR-004), RISK-6
(NĐ13/2023 — đồng ý phải tách theo mục đích và rút được).

Quy tắc cốt lõi (Gherkin của ticket):
- G1: Given phụ huynh đồng ý, When tạo bản ghi, Then lưu phiên bản văn bản
  (`document_version`) và thời điểm SERVER (`granted_at` do server sinh,
  không nhận từ client).
- G2: Given một ô đồng ý gộp nhiều mục đích, When gửi, Then 422. Một bản ghi
  CHỈ mang MỘT `purpose` hợp lệ (enum của contract); `purpose` là danh sách,
  chuỗi rỗng, hoặc không thuộc enum -> 422 (`InvalidConsentInput`).
- G3: Given đồng ý bị rút, When hệ thống xử lý theo mục đích đó, Then bị từ
  chối và ghi audit. `assert_purpose_granted` là điểm gọi DUY NHẤT các dịch
  vụ khác (thông báo, xuất bản ảnh, v.v.) dùng để kiểm trước khi xử lý dữ
  liệu theo một mục đích cụ thể — ghi audit `consent_processing_denied`
  TRƯỚC khi ném lỗi, không xử lý âm thầm (RISK-6, NFR-007).
"""

from __future__ import annotations

from typing import Any, Protocol

from qlkh.application.repository_ports import ConsentRepository
from qlkh.domain.subject_context import SubjectContext

VALID_PURPOSES: frozenset[str] = frozenset(
    {"service_delivery", "notification", "photo_publication"}
)


class AuditSink(Protocol):
    """Đích ghi audit log. Adapter hạ tầng hiện thực sau (stdout JSON/OTel)."""

    def record(self, event: str, **fields: Any) -> None: ...


class StudentNotFound(Exception):
    """Học viên không tồn tại HOẶC ngoài phạm vi ctx — không lộ tồn tại (404)."""


class ConsentNotFound(Exception):
    """Bản ghi đồng ý không tồn tại HOẶC ngoài phạm vi ctx — 404."""


class InvalidConsentInput(ValueError):
    """`purpose` gộp nhiều mục đích, rỗng, hoặc ngoài enum; thiếu
    `document_version`/`student_id` (422)."""


class ConsentWithdrawn(Exception):
    """Đồng ý cho mục đích này đã bị rút hoặc chưa từng được cấp — xử lý dữ
    liệu theo mục đích đó phải bị từ chối (Gherkin G3)."""


class ConsentService:
    """Ca dùng ghi nhận, rút, và xem đồng ý; kiểm quyền qua P3."""

    def __init__(self, consents: ConsentRepository, audit: AuditSink) -> None:
        self._consents = consents
        self._audit = audit

    # ------------------------------------------------------------------ #
    # POST /consents
    # ------------------------------------------------------------------ #
    def create_consent(
        self,
        ctx: SubjectContext,
        *,
        student_id: str,
        purpose: Any,
        document_version: str,
    ) -> dict[str, Any]:
        if not student_id or not str(student_id).strip():
            raise InvalidConsentInput("student_id không được rỗng")
        if not document_version or not str(document_version).strip():
            raise InvalidConsentInput("document_version không được rỗng")
        # G2: một bản ghi chỉ mang MỘT mục đích. purpose là list/tuple/set
        # (client gộp nhiều mục đích), hoặc chuỗi rỗng, hoặc ngoài enum -> 422.
        if not isinstance(purpose, str) or purpose not in VALID_PURPOSES:
            raise InvalidConsentInput(
                "purpose phải là đúng một giá trị trong "
                f"{sorted(VALID_PURPOSES)}, nhận được: {purpose!r}"
            )

        student_ref = self._consents.get_student_ref(ctx, student_id)
        if student_ref is None:
            raise StudentNotFound(student_id)

        record = self._consents.create(
            ctx,
            student_id=student_id,
            purpose=purpose,
            document_version=document_version,
        )
        self._audit.record(
            "consent_granted",
            actor_id=ctx.user_id,
            student_id=student_id,
            purpose=purpose,
            document_version=document_version,
            consent_id=record.get("id"),
        )
        return record

    # ------------------------------------------------------------------ #
    # DELETE /consents/{id}
    # ------------------------------------------------------------------ #
    def revoke_consent(self, ctx: SubjectContext, consent_id: str) -> None:
        """Rút một đồng ý (idempotent — 204 dù đã rút từ trước hoặc không
        tồn tại trong phạm vi ctx, theo contract)."""
        revoked = self._consents.revoke(ctx, consent_id)
        if revoked:
            self._audit.record(
                "consent_revoked",
                actor_id=ctx.user_id,
                consent_id=consent_id,
            )

    # ------------------------------------------------------------------ #
    # GET /students/{id}/consents
    # ------------------------------------------------------------------ #
    def list_student_consents(self, ctx: SubjectContext, student_id: str) -> list[dict[str, Any]]:
        student_ref = self._consents.get_student_ref(ctx, student_id)
        if student_ref is None:
            raise StudentNotFound(student_id)
        return self._consents.list_for_student(ctx, student_id)

    # ------------------------------------------------------------------ #
    # G3: cổng kiểm DUY NHẤT trước khi xử lý dữ liệu theo một mục đích
    # ------------------------------------------------------------------ #
    def assert_purpose_granted(
        self,
        ctx: SubjectContext,
        *,
        student_id: str,
        purpose: str,
    ) -> None:
        """Ném `ConsentWithdrawn` nếu mục đích này chưa từng được đồng ý hoặc
        đã bị rút; ghi audit TRƯỚC khi ném lỗi — không xử lý âm thầm."""
        active = self._consents.get_active_consent(ctx, student_id, purpose)
        if active is None:
            self._audit.record(
                "consent_processing_denied",
                actor_id=ctx.user_id,
                student_id=student_id,
                purpose=purpose,
            )
            raise ConsentWithdrawn(
                f"đồng ý cho mục đích '{purpose}' của học viên {student_id} "
                "đã bị rút hoặc chưa từng được cấp"
            )
