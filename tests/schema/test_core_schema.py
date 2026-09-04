"""Test schema lõi QLKH-002 / REQ-002.

Gherkin 1: apply rồi rollback trên DB rỗng không lỗi, schema về trạng thái ban đầu
           -> kiểm tĩnh: mọi đối tượng up tạo đều được down xóa, cả hai chiều idempotent.
Gherkin 2: mọi cột PII có retention và mục đích khai báo.
Gherkin 3: truy vấn danh sách theo branch_id có index phục vụ (không seq scan).
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.schema_meta import (
    check_directory,
    check_idempotent,
    check_migration_pair,
    check_pii_metadata,
    main,
    parse_columns,
    parse_objects,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_DIR = REPO_ROOT / "db"
UP_SQL = (DB_DIR / "migrations" / "0002_core_schema.up.sql").read_text(encoding="utf-8")
DOWN_SQL = (DB_DIR / "migrations" / "0002_core_schema.down.sql").read_text(encoding="utf-8")
METADATA = json.loads((DB_DIR / "pii_metadata.json").read_text(encoding="utf-8"))

SCOPE_TABLES = {
    "branches",
    "users",
    "roles",
    "user_branch_scope",
    "teachers",
    "students",
    "parents",
    "parent_student",
    "classes",
    "enrollments",
}


def test_schema_hien_tai_khong_vi_pham():
    assert check_directory(DB_DIR) == []


def test_du_bang_trong_pham_vi_ticket():
    assert SCOPE_TABLES <= set(parse_objects(UP_SQL)["tables_created"])


def test_apply_roi_rollback_ve_trang_thai_ban_dau():
    up, down = parse_objects(UP_SQL), parse_objects(DOWN_SQL)
    assert set(up["tables_created"]) == set(down["tables_dropped"])
    assert set(up["indexes_created"]) == set(down["indexes_dropped"])
    assert check_migration_pair(UP_SQL, DOWN_SQL) == []


def test_migration_thieu_if_not_exists_bi_bat():
    messages = [v.message for v in check_idempotent("CREATE TABLE foo (id uuid);")]
    assert messages == ["CREATE TABLE foo thiếu IF NOT EXISTS: không idempotent"]


def test_rollback_thieu_drop_bi_bat():
    up = "CREATE TABLE IF NOT EXISTS foo (id uuid);"
    messages = [v.message for v in check_migration_pair(up, "")]
    assert messages == ["rollback thiếu DROP TABLE cho 'foo'"]


def test_rollback_xoa_bang_la_bi_bat():
    messages = [v.message for v in check_migration_pair("", "DROP TABLE IF EXISTS other;")]
    assert messages == ["rollback xóa 'other' không do migration này tạo"]


def test_moi_cot_pii_co_muc_dich_va_retention():
    for entry in METADATA["columns"]:
        assert entry["purpose"]
        assert entry["legal_basis"]
        assert 0 < entry["retention_days"] <= 730
        assert entry["access_roles"]


def test_cot_dinh_danh_nhay_cam_deu_duoc_khai_bao():
    declared = {(e["table"], e["column"]) for e in METADATA["columns"]}
    for expected in [
        ("students", "full_name"),
        ("students", "date_of_birth"),
        ("parents", "phone_enc"),
        ("parents", "full_name"),
        ("users", "email"),
    ]:
        assert expected in declared


def test_so_dien_thoai_phu_huynh_khong_luu_dang_thuong():
    columns = parse_columns(UP_SQL)["parents"]
    assert "phone_enc" in columns and "phone" not in columns
    protection = {e["column"]: e["protection"] for e in METADATA["columns"] if e["table"] == "parents"}
    assert protection["phone_enc"] == "encrypted_at_rest"


def test_metadata_tro_toi_cot_khong_ton_tai_bi_bat():
    bad = {"columns": [{"table": "students", "column": "ho_ten", **_meta()}]}
    messages = [v.message for v in check_pii_metadata(bad, parse_columns(UP_SQL))]
    assert messages == ["metadata trỏ tới cột không tồn tại: students.ho_ten"]


def test_metadata_thieu_retention_bi_bat():
    meta = _meta()
    meta.pop("retention_days")
    bad = {"columns": [{"table": "students", "column": "full_name", **meta}]}
    messages = [v.message for v in check_pii_metadata(bad, parse_columns(UP_SQL))]
    assert messages == ["students.full_name thiếu 'retention_days'"]


def test_retention_vuot_hai_nam_bi_bat():
    bad = {"columns": [{"table": "students", "column": "full_name", **_meta(retention_days=1000)}]}
    messages = [v.message for v in check_pii_metadata(bad, parse_columns(UP_SQL))]
    assert messages == ["students.full_name retention 1000 ngày vượt 730"]


def test_metadata_trung_bi_bat():
    entry = {"table": "students", "column": "full_name", **_meta()}
    messages = [v.message for v in check_pii_metadata({"columns": [entry, entry]}, parse_columns(UP_SQL))]
    assert messages == ["metadata trùng cho students.full_name"]


def test_index_danh_sach_theo_branch_id():
    body = UP_SQL.replace("\n", " ")
    assert "students_branch_created_idx" in parse_objects(UP_SQL)["indexes_created"]
    assert "ON students (branch_id, created_at DESC, id DESC)" in body
    assert "classes_branch_created_idx" in parse_objects(UP_SQL)["indexes_created"]


def test_index_danh_sach_theo_lop():
    assert "enrollments_class_student_idx" in parse_objects(UP_SQL)["indexes_created"]


def test_rang_buoc_toan_ven_dat_o_db():
    body = UP_SQL.replace("\n", " ")
    assert "REFERENCES branches (id)" in body
    assert "enrollments_class_student_uniq UNIQUE (class_id, student_id)" in body
    assert "timestamptz" in body and "timestamp " not in body


def test_main_tra_ve_exit_code_dung(tmp_path):
    assert main([str(DB_DIR)]) == 0
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001_x.up.sql").write_text("CREATE TABLE foo (id uuid);", encoding="utf-8")
    (tmp_path / "pii_metadata.json").write_text("{}", encoding="utf-8")
    assert main([str(tmp_path)]) == 1


def test_thu_muc_khong_co_migration_bi_bat(tmp_path):
    (tmp_path / "migrations").mkdir()
    assert [v.message for v in check_directory(tmp_path)] == ["không tìm thấy migration nào"]


def _meta(**overrides):
    base = {
        "legal_basis": "dong_y_cua_cha_me",
        "purpose": "cung_cap_dich_vu_dao_tao",
        "retention_days": 730,
        "retention_anchor": "created_at",
        "enforced_by": "QLKH-014:job_retention_p4",
        "access_roles": ["admin"],
    }
    base.update(overrides)
    return base
