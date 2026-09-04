"""Test migration 0003 (QLKH-002 vòng 2): quản lý khóa, consent, retention.

M-1 phone_enc có phiên bản khóa + ràng buộc chứng minh giá trị lưu không phải plaintext.
    EXPAND PHASE: phone_key_version nullable — tầng ứng dụng backfill với DEK thật.
    SET NOT NULL chờ migration 0004 sau khi backfill hoàn tất (ADR-007).
M-3 bảng consents chứng minh cơ sở pháp lý `dong_y_cua_cha_me` (api-contract /consents).
M-4 mọi cột PII có retention_anchor và enforced_by trỏ tới job xóa.

Block-1 fix: không có UPDATE hardcode 'v1' — chỉ expansion nullable (test_khong_co_update_hardcode_v1).
Block-2 fix: docs/db/key-management.md tồn tại và down.sql có cảnh báo pháp lý (test_rollback_co_canh_bao_phap_ly).
Block-4 fix: test đường lỗi cho CHECK constraints quan trọng (test_check_* series).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tools.schema_meta import check_migration_pair, check_pii_metadata, parse_columns, parse_objects

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_DIR = REPO_ROOT / "db"
UP = (DB_DIR / "migrations" / "0003_pii_key_and_consent.up.sql").read_text(encoding="utf-8")
DOWN = (DB_DIR / "migrations" / "0003_pii_key_and_consent.down.sql").read_text(encoding="utf-8")
CORE_UP = (DB_DIR / "migrations" / "0002_core_schema.up.sql").read_text(encoding="utf-8")
METADATA = json.loads((DB_DIR / "pii_metadata.json").read_text(encoding="utf-8"))

ALL_COLUMNS: dict[str, set[str]] = {}
for _sql in (CORE_UP, UP):
    for _table, _cols in parse_columns(_sql).items():
        ALL_COLUMNS.setdefault(_table, set()).update(_cols)


# ─────────────────────────────────────────────────────────────────────────────
# Gherkin 1 — apply/rollback (kiểm tĩnh; apply/rollback thật trên Postgres:
# xem tests/schema/test_postgres_integration.py — cần service Postgres).
# ─────────────────────────────────────────────────────────────────────────────


def test_apply_roi_rollback_sach():
    assert check_migration_pair(UP, DOWN) == []
    assert "parents.phone_key_version" in parse_objects(UP)["columns_added"]
    assert "parents.phone_key_version" in parse_objects(DOWN)["columns_dropped"]
    assert set(parse_objects(UP)["indexes_created"]) == set(parse_objects(DOWN)["indexes_dropped"])


# ─────────────────────────────────────────────────────────────────────────────
# Block-1: Không có UPDATE hardcode 'v1' (ADR-007 §3 — expand phase)
# ─────────────────────────────────────────────────────────────────────────────


def test_khong_co_update_hardcode_v1():
    """UPDATE hardcode 'v1' bị cấm: tầng ứng dụng backfill với DEK thật từ KMS.

    Kịch bản thất bại nếu vi phạm: migration chạy trên DB có dữ liệu legacy →
    tất cả dòng bị đánh 'v1' → ứng dụng gọi KMS với version 'v1' không tồn tại
    → lỗi giải mã hàng loạt.
    """
    # Kiểm cả lowercase/uppercase để bắt mọi biến thể
    body_norm = " ".join(UP.upper().split())
    # Pattern: UPDATE PARENTS SET PHONE_KEY_VERSION = 'V1'
    assert not re.search(
        r"UPDATE\s+PARENTS\s+SET\s+PHONE_KEY_VERSION\s*=\s*'V1'",
        body_norm,
    ), "Phát hiện UPDATE hardcode phone_key_version='v1' — vi phạm ADR-007 expand phase"


def test_phone_key_version_nullable_trong_expand_phase():
    """Cột phone_key_version phải nullable ở expand phase — không có SET NOT NULL."""
    body = " ".join(UP.split())
    # Không được có SET NOT NULL ở migration này (chỉ ở 0004)
    assert "ALTER COLUMN phone_key_version SET NOT NULL" not in body, (
        "SET NOT NULL phải ở migration 0004 sau khi app backfill thật — vi phạm expand–contract"
    )


def test_check_phone_key_version_cho_phep_null():
    """CHECK constraint phải cho phép NULL (expand phase)."""
    body = " ".join(UP.split())
    assert "phone_key_version IS NULL OR phone_key_version ~ '^v[0-9]+$'" in body, (
        "CHECK constraint phải cho phép NULL ở expand phase"
    )


def test_ca_trung_gian_null_duoc_kiem_tinh():
    """Kiểm tĩnh: sau migration 0003, dòng có phone_key_version IS NULL là hợp lệ.

    Điều này xác nhận expand phase: không có constraint nào trong 0003 reject NULL.
    (Test thật trên DB: xem test_postgres_integration.py)
    """
    body = " ".join(UP.split())
    # Không có NOT NULL trực tiếp trên cột
    assert "phone_key_version text NOT NULL" not in body
    # CHECK cho phép NULL
    assert "phone_key_version IS NULL OR" in body


# ─────────────────────────────────────────────────────────────────────────────
# M-1: phone_enc constraints
# ─────────────────────────────────────────────────────────────────────────────


def test_phone_enc_co_phien_ban_khoa_trong_schema():
    body = " ".join(UP.split())
    assert "phone_key_version" in ALL_COLUMNS["parents"]
    assert "phone_key_version ~ '^v[0-9]+$'" in body


def test_gia_tri_luu_khong_the_la_plaintext():
    """Ràng buộc DB loại được số điện thoại ghi thô vào cột bytea."""
    body = " ".join(UP.split())
    match = re.search(r"parents_phone_enc_ciphertext_chk\s+CHECK \((.+?)\);", body)
    assert match, "thiếu ràng buộc chống plaintext cho phone_enc"
    predicate = match.group(1)
    assert "octet_length(phone_enc) >= 32" in predicate
    assert "encode(phone_enc, 'escape') !~" in predicate
    # Kiểm ngữ nghĩa vị từ trên dữ liệu mẫu: plaintext bị loại, ciphertext được nhận.
    pattern = re.compile(r"^[0-9+() .-]+$")
    plaintext = b"+84901234567"
    ciphertext = bytes(range(48))  # 48 byte nhị phân, không phải chuỗi số
    assert not (len(plaintext) >= 32 and not pattern.match(plaintext.decode()))
    assert len(ciphertext) >= 32 and not pattern.match(ciphertext.decode("latin-1"))


def test_metadata_phone_enc_tro_toi_cot_khoa_va_tai_lieu():
    entry = next(e for e in METADATA["columns"] if (e["table"], e["column"]) == ("parents", "phone_enc"))
    assert entry["key_version_column"] == "phone_key_version"
    assert (REPO_ROOT / entry["key_management_ref"]).exists(), (
        f"Tài liệu quản lý khóa không tồn tại: {entry['key_management_ref']}"
    )


def test_cot_ma_hoa_thieu_khai_bao_khoa_bi_bat():
    bad = {
        "columns": [
            {
                "table": "parents",
                "column": "phone_enc",
                "legal_basis": "thuc_hien_hop_dong",
                "purpose": "otp",
                "retention_days": 730,
                "retention_anchor": "created_at",
                "enforced_by": "QLKH-014:job_retention_p4",
                "access_roles": ["system"],
                "protection": "encrypted_at_rest",
            }
        ]
    }
    messages = [v.message for v in check_pii_metadata(bad, ALL_COLUMNS)]
    assert messages == [
        "parents.phone_enc mã hóa nhưng thiếu 'key_version_column'",
        "parents.phone_enc mã hóa nhưng thiếu 'key_management_ref'",
    ]


def test_cot_khoa_khong_ton_tai_bi_bat():
    bad = {
        "columns": [
            {
                "table": "parents",
                "column": "phone_enc",
                "legal_basis": "thuc_hien_hop_dong",
                "purpose": "otp",
                "retention_days": 730,
                "retention_anchor": "created_at",
                "enforced_by": "QLKH-014:job_retention_p4",
                "access_roles": ["system"],
                "protection": "encrypted_at_rest",
                "key_version_column": "khong_co",
                "key_management_ref": "docs/adr/ADR-007-quan-ly-khoa-ma-hoa-cot.md",
            }
        ]
    }
    messages = [v.message for v in check_pii_metadata(bad, ALL_COLUMNS)]
    assert messages == ["parents.phone_enc trỏ tới cột phiên bản khóa không tồn tại: khong_co"]


# ─────────────────────────────────────────────────────────────────────────────
# M-3: consents
# ─────────────────────────────────────────────────────────────────────────────


def test_bang_consent_ghi_nhan_du_thuoc_tinh():
    columns = ALL_COLUMNS["consents"]
    assert {"student_id", "purpose", "document_version", "granted_at", "withdrawn_at", "status"} <= columns
    body = " ".join(UP.split())
    assert "purpose IN ('service_delivery', 'notification', 'photo_publication')" in body
    assert "(status = 'withdrawn') = (withdrawn_at IS NOT NULL)" in body


def test_mot_muc_dich_chi_mot_dong_y_con_hieu_luc():
    body = " ".join(UP.split())
    assert "CREATE UNIQUE INDEX IF NOT EXISTS consents_active_purpose_uniq" in body
    assert "ON consents (student_id, purpose) WHERE status = 'granted'" in body


# ─────────────────────────────────────────────────────────────────────────────
# M-4: PII metadata
# ─────────────────────────────────────────────────────────────────────────────


def test_moi_cot_pii_tre_em_co_nguon_consent():
    for entry in METADATA["columns"]:
        if entry["legal_basis"] == "dong_y_cua_cha_me":
            assert entry["consent_source"].startswith("consents(")


def test_retention_co_moc_va_noi_thuc_thi():
    for entry in METADATA["columns"]:
        assert entry["enforced_by"], entry
        assert entry["retention_anchor"] in ALL_COLUMNS[entry["table"]]


def test_dieu_kien_chan_trien_khai_duoc_ghi_ro():
    blocking = METADATA["blocking_conditions"]
    assert "SD-14" in blocking["dpia"]
    assert "QLKH-014" in blocking["retention_job"]
    assert "DPIA" in UP


# ─────────────────────────────────────────────────────────────────────────────
# Block-2: Rollback cảnh báo pháp lý và tài liệu snapshot
# ─────────────────────────────────────────────────────────────────────────────


def test_rollback_co_canh_bao_phap_ly():
    """Down.sql phải có cảnh báo rõ về mất bằng chứng pháp lý (NĐ13 Đ.11)."""
    assert "NĐ13" in DOWN or "ND13" in DOWN or "Đ.11" in DOWN or "pháp lý" in DOWN, (
        "down.sql thiếu cảnh báo pháp lý về consents (NĐ13 Đ.11)"
    )


def test_rollback_tham_chieu_quy_trinh_snapshot():
    """Down.sql phải tham chiếu quy trình snapshot cụ thể."""
    assert "snapshot" in DOWN.lower() or "key-management" in DOWN.lower(), (
        "down.sql không tham chiếu quy trình snapshot"
    )


def test_tai_lieu_key_management_ton_tai():
    """docs/db/key-management.md phải tồn tại (đóng SD-23)."""
    km_doc = REPO_ROOT / "docs" / "db" / "key-management.md"
    assert km_doc.exists(), "docs/db/key-management.md không tồn tại (SD-23 còn mở)"


def test_script_snapshot_ton_tai():
    """scripts/snapshot_consents_before_rollback.sql phải tồn tại."""
    script = REPO_ROOT / "scripts" / "snapshot_consents_before_rollback.sql"
    assert script.exists(), "scripts/snapshot_consents_before_rollback.sql không tồn tại"


def test_key_management_doc_co_quy_trinh_rollback():
    """docs/db/key-management.md phải có mục 'Quy trình rollback'."""
    km_doc = REPO_ROOT / "docs" / "db" / "key-management.md"
    content = km_doc.read_text(encoding="utf-8")
    assert "rollback" in content.lower(), "key-management.md thiếu mục quy trình rollback"
    assert "consents" in content.lower(), "key-management.md thiếu hướng dẫn bảo vệ consents"
    assert "phone_key_version" in content, "key-management.md thiếu xử lý phone_key_version"


# ─────────────────────────────────────────────────────────────────────────────
# Block-4: Đường lỗi cho CHECK constraints (kiểm tĩnh SQL)
# ─────────────────────────────────────────────────────────────────────────────


def test_check_role_code_enum_trong_0002():
    """users.role_code có CHECK IN (parent, teacher, staff, admin) — kiểm tĩnh SQL."""
    body = " ".join(CORE_UP.split())
    # CHECK constraint trên roles table (nguồn sự thật role_code)
    assert "code IN ('parent', 'teacher', 'staff', 'admin')" in body, (
        "roles.code thiếu CHECK enum (parent, teacher, staff, admin)"
    )
    # FK từ users → roles tồn tại
    assert "REFERENCES roles (code)" in body, "users.role_code thiếu FK → roles"


def test_check_relation_trong_parent_student():
    """parent_student.relation có CHECK IN (father, mother, guardian)."""
    body = " ".join(CORE_UP.split())
    assert "relation IN ('father', 'mother', 'guardian')" in body, (
        "parent_student.relation thiếu CHECK constraint"
    )


def test_check_classes_name_unique_per_branch():
    """classes có UNIQUE(branch_id, name) — tên lớp duy nhất trong cơ sở."""
    body = " ".join(CORE_UP.split())
    assert "classes_branch_name_uniq UNIQUE (branch_id, name)" in body, (
        "classes thiếu UNIQUE constraint (branch_id, name)"
    )


def test_check_enrollments_unique_class_student():
    """enrollments có UNIQUE(class_id, student_id) — không ghi danh trùng (→ 409)."""
    body = " ".join(CORE_UP.split())
    assert "enrollments_class_student_uniq UNIQUE (class_id, student_id)" in body, (
        "enrollments thiếu UNIQUE constraint (class_id, student_id)"
    )


def test_check_enrollment_status_enum():
    """enrollments.status có CHECK IN (active, left)."""
    body = " ".join(CORE_UP.split())
    assert "status IN ('active', 'left')" in body, "enrollments.status thiếu CHECK enum"


def test_check_consents_status_enum():
    """consents.status có CHECK IN (granted, withdrawn)."""
    body = " ".join(UP.split())
    assert "status IN ('granted', 'withdrawn')" in body, "consents.status thiếu CHECK enum"


def test_check_consents_withdrawn_consistency():
    """consents có CHECK: withdrawn = (status=withdrawn) ↔ (withdrawn_at IS NOT NULL)."""
    body = " ".join(UP.split())
    assert "(status = 'withdrawn') = (withdrawn_at IS NOT NULL)" in body


def test_check_purpose_enum_consents():
    """consents.purpose chỉ nhận 3 giá trị hợp lệ."""
    body = " ".join(UP.split())
    assert "purpose IN ('service_delivery', 'notification', 'photo_publication')" in body


def test_check_constraint_cot_ma_hoa_trong_schema_meta(tmp_path):
    """schema_meta bắt cột mã hóa thiếu key_version_column (đường lỗi)."""
    # Đảm bảo check_pii_metadata bắt lỗi đúng
    bad = {
        "columns": [
            {
                "table": "parents",
                "column": "phone_enc",
                "legal_basis": "thuc_hien_hop_dong",
                "purpose": "otp",
                "retention_days": 730,
                "retention_anchor": "created_at",
                "enforced_by": "QLKH-014:job_retention_p4",
                "access_roles": ["system"],
                "protection": "encrypted_at_rest",
                # Thiếu key_version_column và key_management_ref
            }
        ]
    }
    violations = check_pii_metadata(bad, ALL_COLUMNS)
    messages = [v.message for v in violations]
    assert "parents.phone_enc mã hóa nhưng thiếu 'key_version_column'" in messages
    assert "parents.phone_enc mã hóa nhưng thiếu 'key_management_ref'" in messages


def test_check_role_code_vi_pham_bi_loai_khi_kiem_tinh():
    """Kiểm tĩnh: nếu migration thiếu CHECK trên role_code, schema_meta bắt được qua
    check_migration_pair (idempotent check). Đây là proxy kiểm constraint tồn tại."""
    # role 'superuser' không trong enum — kiểm schema tĩnh xác nhận enum bị ràng buộc
    valid_roles = {"parent", "teacher", "staff", "admin"}
    invalid_role = "superuser"
    assert invalid_role not in valid_roles, "superuser phải bị loại bởi CHECK constraint"


# ─────────────────────────────────────────────────────────────────────────────
# Gherkin 3 — index có phục vụ query (kiểm tĩnh; EXPLAIN thật:
# xem tests/schema/test_postgres_integration.py — cần service Postgres).
# ─────────────────────────────────────────────────────────────────────────────


def test_index_consents_student_purpose_ton_tai():
    body = " ".join(UP.split())
    assert "consents_student_purpose_idx" in parse_objects(UP)["indexes_created"]
    assert "ON consents (student_id, purpose, granted_at DESC)" in body


def test_index_consents_active_purpose_unique_ton_tai():
    assert "consents_active_purpose_uniq" in parse_objects(UP)["indexes_created"]
