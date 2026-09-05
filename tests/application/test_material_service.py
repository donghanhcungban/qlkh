"""Test MaterialService (QLKH-010, REQ-007).

Tiêu chí Gherkin:
  G1: Given tệp .pdf đổi đuôi từ .html, When upload, Then 415 do magic bytes
      không khớp.
  G2: Given người không ghi danh lớp, When GET download, Then 403.
  G3: Given URL ký quá 15 phút, When truy cập, Then bị từ chối (ép ở domain,
      adapter không được nới TTL).
  G4: (bổ sung theo api-contract v1.3.0) lớp không tồn tại/ngoài cơ sở -> 404;
      tệp vượt 25 MiB -> 422.
"""

from __future__ import annotations

from typing import Any

import pytest

from qlkh.application.material_service import (
    ClassNotFound,
    ClassPermissionDenied,
    FileTooLarge,
    MaterialNotFound,
    MaterialPermissionDenied,
    MaterialService,
    UnsupportedFileType,
)
from qlkh.domain.material_policy import MAX_SIGNED_URL_TTL_SECONDS, MAX_SIZE_BYTES
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
BRANCH_B = "bbbbbbbb-0000-0000-0000-000000000002"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"  # giáo viên phụ trách / con ghi danh active
CLASS_2 = "dddddddd-0000-0000-0000-000000000200"  # cùng cơ sở, KHÔNG liên quan tới ctx
CLASS_OTHER_BRANCH = "eeeeeeee-0000-0000-0000-000000000900"

REAL_PDF = b"%PDF-1.4\n%...\n"
FAKE_PDF_FROM_HTML = b"<html><body>gia mao pdf</body></html>"


class FakeClassRepo:
    def __init__(self, classes: dict[str, dict[str, Any]]) -> None:
        self._classes = classes

    def get_by_id(self, ctx, class_id):
        record = self._classes.get(class_id)
        if record is None:
            return None
        if not ctx.can_access_branch(record["branch_id"]):
            return None
        return record

    # Các phương thức khác của Protocol không dùng trong test này.
    def list_for_branch(self, ctx, *, cursor=None, limit=50):  # pragma: no cover
        raise NotImplementedError

    def create(self, ctx, *, name, teacher_id=None):  # pragma: no cover
        raise NotImplementedError

    def enroll(self, ctx, class_id, student_id, *, enrolled_at):  # pragma: no cover
        raise NotImplementedError

    def unenroll(self, ctx, class_id, student_id):  # pragma: no cover
        raise NotImplementedError


class FakeMaterialRepo:
    def __init__(self) -> None:
        self._materials: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def create(self, ctx, class_id, *, filename, mime_type, size_bytes, object_key):
        self._seq += 1
        new_id = f"material-{self._seq}"
        record = {
            "id": new_id,
            "class_id": class_id,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "object_key": object_key,
        }
        self._materials[new_id] = record
        return record

    def get_by_id(self, ctx, material_id):
        return self._materials.get(material_id)

    def seed(self, record: dict[str, Any]) -> None:
        self._materials[record["id"]] = record


class FakeBlobStorage:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, bytes, str]] = []
        self.signed_url_calls: list[tuple[str, int]] = []

    def put_object(self, object_key, content, *, content_type):
        self.put_calls.append((object_key, content, content_type))

    def generate_signed_url(self, object_key, *, ttl_seconds):
        self.signed_url_calls.append((object_key, ttl_seconds))
        return f"https://blob.example.vn/{object_key}?ttl={ttl_seconds}"


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event, **fields):
        self.events.append((event, fields))


@pytest.fixture()
def classes() -> dict[str, dict[str, Any]]:
    return {
        CLASS_1: {"id": CLASS_1, "branch_id": BRANCH_A},
        CLASS_2: {"id": CLASS_2, "branch_id": BRANCH_A},
        CLASS_OTHER_BRANCH: {"id": CLASS_OTHER_BRANCH, "branch_id": BRANCH_B},
    }


@pytest.fixture()
def service(classes):
    return MaterialService(
        FakeClassRepo(classes), FakeMaterialRepo(), FakeBlobStorage(), RecordingAudit()
    )


def ctx_teacher() -> SubjectContext:
    return SubjectContext(
        user_id="teacher-1",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=(CLASS_1,),
    )


def ctx_parent_enrolled() -> SubjectContext:
    """Phụ huynh có con ghi danh active ở CLASS_1 — quan hệ nạp sẵn ở
    related_class_ids khi dựng SubjectContext (ngoài phạm vi ticket này)."""
    return SubjectContext(
        user_id="parent-1",
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=(CLASS_1,),
    )


def ctx_parent_not_enrolled() -> SubjectContext:
    return SubjectContext(
        user_id="parent-2",
        role="parent",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=(),
    )


def ctx_staff_branch_b() -> SubjectContext:
    return SubjectContext(user_id="staff-b", role="staff", allowed_branch_ids=(BRANCH_B,))


# ---------------------------------------------------------------------------
# POST /classes/{id}/materials
# ---------------------------------------------------------------------------


def test_upload_pdf_that_thanh_cong(service: MaterialService):
    record = service.upload_material(
        ctx_teacher(), CLASS_1, filename="bai1.pdf", content=REAL_PDF
    )
    assert record["mime_type"] == "application/pdf"
    assert record["class_id"] == CLASS_1
    assert record["object_key"] != "bai1.pdf"  # không suy từ filename (ADR-005)


def test_upload_pdf_gia_doi_duoi_tu_html_bi_tu_choi_415(service: MaterialService):
    """G1: .pdf đổi đuôi từ .html -> magic bytes không khớp -> 415."""
    with pytest.raises(UnsupportedFileType):
        service.upload_material(
            ctx_teacher(), CLASS_1, filename="bai1.pdf", content=FAKE_PDF_FROM_HTML
        )


def test_upload_lop_khong_ton_tai_hoac_ngoai_co_so_404(service: MaterialService):
    with pytest.raises(ClassNotFound):
        service.upload_material(
            ctx_staff_branch_b(), CLASS_1, filename="bai1.pdf", content=REAL_PDF
        )


def test_upload_giao_vien_khong_phu_trach_lop_403(service: MaterialService):
    with pytest.raises(ClassPermissionDenied):
        service.upload_material(
            ctx_teacher(), CLASS_2, filename="bai1.pdf", content=REAL_PDF
        )


def test_upload_tep_vuot_kich_thuoc_422(service: MaterialService):
    oversized = b"%PDF-1.4\n" + b"0" * (MAX_SIZE_BYTES + 1)
    with pytest.raises(FileTooLarge):
        service.upload_material(
            ctx_teacher(), CLASS_1, filename="bai1.pdf", content=oversized
        )


def test_upload_khong_luu_object_key_theo_filename(service: MaterialService):
    a = service.upload_material(ctx_teacher(), CLASS_1, filename="x.pdf", content=REAL_PDF)
    b = service.upload_material(ctx_teacher(), CLASS_1, filename="x.pdf", content=REAL_PDF)
    assert a["object_key"] != b["object_key"]


# ---------------------------------------------------------------------------
# GET /materials/{id}/download
# ---------------------------------------------------------------------------


def test_download_thanh_cong_tra_url_ky_ttl_toi_da_15_phut(
    classes: dict[str, dict[str, Any]]
):
    material_repo = FakeMaterialRepo()
    material_repo.seed(
        {
            "id": "material-1",
            "class_id": CLASS_1,
            "filename": "x.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 10,
            "object_key": "random-key-abc",
        }
    )
    blobs = FakeBlobStorage()
    service = MaterialService(FakeClassRepo(classes), material_repo, blobs, RecordingAudit())

    material, url = service.get_download_url(ctx_teacher(), "material-1")

    assert material["id"] == "material-1"
    assert url.endswith(f"ttl={MAX_SIGNED_URL_TTL_SECONDS}")
    # G3: TTL luôn <= 15 phút, ép ở domain — không phụ thuộc cấu hình adapter.
    assert blobs.signed_url_calls[0][1] <= MAX_SIGNED_URL_TTL_SECONDS


def test_download_nguoi_khong_ghi_danh_lop_403(classes: dict[str, dict[str, Any]]):
    """G2: phụ huynh không có con ghi danh lớp -> 403."""
    material_repo = FakeMaterialRepo()
    material_repo.seed(
        {
            "id": "material-1",
            "class_id": CLASS_1,
            "filename": "x.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 10,
            "object_key": "random-key-abc",
        }
    )
    service = MaterialService(
        FakeClassRepo(classes), material_repo, FakeBlobStorage(), RecordingAudit()
    )
    with pytest.raises(MaterialPermissionDenied):
        service.get_download_url(ctx_parent_not_enrolled(), "material-1")


def test_download_phu_huynh_co_con_ghi_danh_thanh_cong(classes: dict[str, dict[str, Any]]):
    material_repo = FakeMaterialRepo()
    material_repo.seed(
        {
            "id": "material-1",
            "class_id": CLASS_1,
            "filename": "x.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 10,
            "object_key": "random-key-abc",
        }
    )
    service = MaterialService(
        FakeClassRepo(classes), material_repo, FakeBlobStorage(), RecordingAudit()
    )
    material, url = service.get_download_url(ctx_parent_enrolled(), "material-1")
    assert material["id"] == "material-1"
    assert url


def test_download_material_khong_ton_tai_404(classes: dict[str, dict[str, Any]]):
    service = MaterialService(
        FakeClassRepo(classes), FakeMaterialRepo(), FakeBlobStorage(), RecordingAudit()
    )
    with pytest.raises(MaterialNotFound):
        service.get_download_url(ctx_teacher(), "khong-ton-tai")


def test_download_lop_ngoai_co_so_404_khong_lo_ton_tai(classes: dict[str, dict[str, Any]]):
    material_repo = FakeMaterialRepo()
    material_repo.seed(
        {
            "id": "material-2",
            "class_id": CLASS_OTHER_BRANCH,
            "filename": "x.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 10,
            "object_key": "random-key-def",
        }
    )
    service = MaterialService(
        FakeClassRepo(classes), material_repo, FakeBlobStorage(), RecordingAudit()
    )
    with pytest.raises(MaterialNotFound):
        service.get_download_url(ctx_teacher(), "material-2")
