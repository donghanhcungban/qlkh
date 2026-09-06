"""Dịch vụ học liệu (QLKH-010, REQ-007).

Cài đặt POST /classes/{id}/materials và GET /materials/{id}/download theo
api-contract v1.3.0 (schema `Material`). Không import ORM/HTTP/SDK object
storage: mọi phụ thuộc là Protocol, adapter hạ tầng hiện thực sau.

Threat refs: RISK-5/ADR-005 (bucket public nhầm, tên đối tượng đoán được),
QLKH-T-05 (upload tệp giả mạo loại — chỉ tin magic bytes, không tin đuôi tệp
hay `Content-Type` client gửi), QLKH-T-07 (giáo viên/phụ huynh thao tác lớp
không liên quan — BFLA/BOLA).

Quy tắc cốt lõi (Gherkin của ticket):
- Upload: dùng lại đúng phân biệt lỗi của `ClassService` cho lớp đích
  (404 không tồn tại/ngoài cơ sở, 403 không phụ trách); sau đó kiểm kích
  thước (422 nếu > 25 MiB) RỒI kiểm magic bytes (415 nếu không khớp allowlist)
  — `.pdf` giả đổi đuôi từ `.html` không có magic bytes PDF thật sẽ bị 415
  dù tên tệp hợp lệ.
- `object_key` luôn sinh ngẫu nhiên (`material_policy.generate_object_key`),
  không bao giờ suy từ `filename` — chặn đoán/liệt kê object trong bucket.
- Download: kiểm quyền TRƯỚC khi cấp URL ký — dùng lại `ctx.can_access_class`
  (staff/admin theo branch, giáo viên theo lớp phụ trách, phụ huynh theo lớp
  có con đang ghi danh active — quan hệ này nạp sẵn vào
  `ctx.related_class_ids` khi dựng SubjectContext, ngoài phạm vi ticket này).
  Lớp chứa material không tồn tại/ngoài cơ sở -> 404 (không lộ tồn tại);
  lớp tồn tại nhưng ctx không có quyền (vd phụ huynh không ghi danh) -> 403
  (đúng Gherkin của ticket, KHÔNG gộp chung vào 404).
- TTL URL ký luôn <= 15 phút, ép bằng `material_policy.clamp_signed_url_ttl`
  ngay tại service — không phụ thuộc adapter/cấu hình có tôn trọng hay không.
"""

from __future__ import annotations

from typing import Any, Protocol

from qlkh.application.repository_ports import BlobStorage, ClassRepository, MaterialRepository
from qlkh.domain.material_policy import (
    ALLOWED_MIME_TYPES,
    MAX_SIGNED_URL_TTL_SECONDS,
    MAX_SIZE_BYTES,
    clamp_signed_url_ttl,
    generate_object_key,
    sniff_mime_type,
)
from qlkh.domain.subject_context import SubjectContext


class AuditSink(Protocol):
    """Đích ghi audit log. Adapter hạ tầng hiện thực sau (stdout JSON/OTel)."""

    def record(self, event: str, **fields: Any) -> None: ...


class ClassNotFound(Exception):
    """Lớp không tồn tại HOẶC ngoài phạm vi cơ sở của phiên — 404."""


class ClassPermissionDenied(Exception):
    """Lớp tồn tại trong cơ sở nhưng ctx không có quyền truy cập — 403."""


class MaterialNotFound(Exception):
    """Học liệu không tồn tại HOẶC lớp chứa nó ngoài phạm vi cơ sở — 404
    (không lộ tồn tại, cùng khuôn mẫu ADR-004)."""


class MaterialPermissionDenied(Exception):
    """Lớp chứa học liệu tồn tại trong cơ sở nhưng ctx không có quyền (giáo
    viên không phụ trách, phụ huynh không có con ghi danh active) — 403."""


class UnsupportedFileType(Exception):
    """Magic bytes không khớp allowlist MIME cho phép — 415."""


class FileTooLarge(Exception):
    """Tệp vượt kích thước tối đa cho phép (25 MiB) — 422."""


class MaterialService:
    """Ca dùng upload và phát học liệu, kiểm quyền theo đối tượng lớp."""

    def __init__(
        self,
        classes: ClassRepository,
        materials: MaterialRepository,
        blobs: BlobStorage,
        audit: AuditSink,
    ) -> None:
        self._classes = classes
        self._materials = materials
        self._blobs = blobs
        self._audit = audit

    # ------------------------------------------------------------------ #
    # Kiểm quyền dùng lại cho cả upload và download (một nguồn sự thật)
    # ------------------------------------------------------------------ #
    def _get_class_or_raise(self, ctx: SubjectContext, class_id: str) -> dict[str, Any]:
        record = self._classes.get_by_id(ctx, class_id)
        if record is None:
            # Không tồn tại HOẶC ngoài cơ sở của phiên — không phân biệt (404).
            raise ClassNotFound(class_id)
        if not ctx.can_access_class(class_id, record["branch_id"]):
            # Trong cơ sở nhưng ctx không có quyền (giáo viên không phụ
            # trách, phụ huynh không có con ghi danh active) -> 403.
            raise ClassPermissionDenied(
                f"user {ctx.user_id} (role={ctx.role}) không có quyền lớp {class_id}"
            )
        return record

    # ------------------------------------------------------------------ #
    # POST /classes/{id}/materials
    # ------------------------------------------------------------------ #
    def upload_material(
        self,
        ctx: SubjectContext,
        class_id: str,
        *,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        self._get_class_or_raise(ctx, class_id)

        if len(content) > MAX_SIZE_BYTES:
            raise FileTooLarge(
                f"tệp {len(content)} bytes vượt tối đa {MAX_SIZE_BYTES} bytes"
            )

        # Chỉ tin magic bytes của NỘI DUNG tệp — không tin đuôi tệp hay
        # Content-Type client gửi (ADR-005, QLKH-T-05).
        mime_type = sniff_mime_type(content)
        if mime_type is None or mime_type not in ALLOWED_MIME_TYPES:
            raise UnsupportedFileType(
                f"magic bytes không khớp allowlist MIME cho phép (filename={filename!r})"
            )

        object_key = generate_object_key()
        self._blobs.put_object(object_key, content, content_type=mime_type)
        record = self._materials.create(
            ctx,
            class_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(content),
            object_key=object_key,
        )
        self._audit.record(
            "material.uploaded",
            class_id=class_id,
            actor_id=ctx.user_id,
            material_id=record.get("id"),
            mime_type=mime_type,
            size_bytes=len(content),
        )
        return record

    # ------------------------------------------------------------------ #
    # GET /materials/{id}/download
    # ------------------------------------------------------------------ #
    def get_download_url(
        self, ctx: SubjectContext, material_id: str
    ) -> tuple[dict[str, Any], str]:
        material = self._materials.get_by_id(ctx, material_id)
        if material is None:
            raise MaterialNotFound(material_id)

        # Kiểm quyền qua lớp chứa material — một nguồn sự thật duy nhất với
        # upload, tránh hai đường quyết định 403/404 khác nhau. "Lớp không
        # tồn tại/ngoài cơ sở" -> 404; "ctx không có quyền" (không ghi danh,
        # không phụ trách) -> 403 — KHÔNG gộp hai lỗi này (Gherkin ticket).
        try:
            self._get_class_or_raise(ctx, material["class_id"])
        except ClassNotFound as exc:
            raise MaterialNotFound(material_id) from exc
        except ClassPermissionDenied as exc:
            raise MaterialPermissionDenied(str(exc)) from exc

        ttl_seconds = clamp_signed_url_ttl(MAX_SIGNED_URL_TTL_SECONDS)
        url = self._blobs.generate_signed_url(material["object_key"], ttl_seconds=ttl_seconds)
        self._audit.record(
            "material.downloaded",
            material_id=material_id,
            class_id=material["class_id"],
            actor_id=ctx.user_id,
        )
        return material, url
