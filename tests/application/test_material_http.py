"""Test MaterialHttpHandlers — mã trạng thái/Problem Details (QLKH-010, REQ-007)."""

from __future__ import annotations

from typing import Any

import pytest

from qlkh.application.material_http import MaterialHttpHandlers
from qlkh.application.material_service import MaterialService
from qlkh.domain.subject_context import SubjectContext

BRANCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
CLASS_1 = "cccccccc-0000-0000-0000-000000000100"
CLASS_2 = "dddddddd-0000-0000-0000-000000000200"

REAL_PDF = b"%PDF-1.4\n%...\n"
FAKE_PDF_FROM_HTML = b"<html>gia mao</html>"


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

    def seed(self, record):
        self._materials[record["id"]] = record


class FakeBlobStorage:
    def put_object(self, object_key, content, *, content_type):
        pass

    def generate_signed_url(self, object_key, *, ttl_seconds):
        return f"https://blob.example.vn/{object_key}?ttl={ttl_seconds}"


class NullAudit:
    def record(self, event, **fields):
        pass


def ctx_teacher() -> SubjectContext:
    return SubjectContext(
        user_id="teacher-1",
        role="teacher",
        allowed_branch_ids=(BRANCH_A,),
        related_class_ids=(CLASS_1,),
    )


@pytest.fixture()
def handlers() -> MaterialHttpHandlers:
    classes = {
        CLASS_1: {"id": CLASS_1, "branch_id": BRANCH_A},
        CLASS_2: {"id": CLASS_2, "branch_id": BRANCH_A},
    }
    service = MaterialService(
        FakeClassRepo(classes), FakeMaterialRepo(), FakeBlobStorage(), NullAudit()
    )
    return MaterialHttpHandlers(service)


def test_upload_thanh_cong_201_khong_lo_object_key(handlers: MaterialHttpHandlers):
    result = handlers.upload_material(
        ctx_teacher(), CLASS_1, filename="bai1.pdf", content=REAL_PDF
    )
    assert result.status == 201
    assert "object_key" not in result.body


def test_upload_magic_bytes_khong_khop_tra_415(handlers: MaterialHttpHandlers):
    result = handlers.upload_material(
        ctx_teacher(), CLASS_1, filename="bai1.pdf", content=FAKE_PDF_FROM_HTML
    )
    assert result.status == 415
    assert result.body["type"] == "https://qlkh/errors/unsupported-media-type"


def test_upload_lop_khong_phu_trach_tra_403(handlers: MaterialHttpHandlers):
    result = handlers.upload_material(
        ctx_teacher(), CLASS_2, filename="bai1.pdf", content=REAL_PDF
    )
    assert result.status == 403


def test_download_khong_ton_tai_tra_404(handlers: MaterialHttpHandlers):
    result = handlers.download_material(ctx_teacher(), "khong-ton-tai")
    assert result.status == 404


def test_download_thanh_cong_302_co_location_va_content_disposition(
    handlers: MaterialHttpHandlers,
):
    upload_result = handlers.upload_material(
        ctx_teacher(), CLASS_1, filename="bai1.pdf", content=REAL_PDF
    )
    material_id = upload_result.body["id"]

    result = handlers.download_material(ctx_teacher(), material_id)

    assert result.status == 302
    assert result.headers["Location"].startswith("https://blob.example.vn/")
    assert result.headers["Content-Disposition"] == "attachment"
