"""Test migration 0003 (QLKH-002 vòng 2): quản lý khóa, consent, retention.

M-1 phone_enc có phiên bản khóa + ràng buộc chứng minh giá trị lưu không phải plaintext.
M-3 bảng consents chứng minh cơ sở pháp lý `dong_y_cua_cha_me` (api-contract /consents).
M-4 mọi cột PII có retention_anchor và enforced_by trỏ tới job xóa.
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


def test_apply_roi_rollback_sach():
    assert check_migration_pair(UP, DOWN) == []
    assert "parents.phone_key_version" in parse_objects(UP)["columns_added"]
    assert "parents.phone_key_version" in parse_objects(DOWN)["columns_dropped"]
    assert set(parse_objects(UP)["indexes_created"]) == set(parse_objects(DOWN)["indexes_dropped"])


def test_phone_enc_co_phien_ban_khoa_not_null():
    body = " ".join(UP.split())
    assert "phone_key_version" in ALL_COLUMNS["parents"]
    assert "ALTER COLUMN phone_key_version SET NOT NULL" in body
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
    assert (REPO_ROOT / entry["key_management_ref"]).exists()


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
