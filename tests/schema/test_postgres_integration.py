"""Test tích hợp Postgres cho QLKH-002 / REQ-002.

Gherkin 1 (thật): apply rồi rollback trên DB rỗng không lỗi, schema về trạng thái ban đầu.
Gherkin 3 (thật): truy vấn danh sách theo branch_id có index phục vụ (không seq scan).

YÊU CẦU MÔI TRƯỜNG:
  - Biến môi trường QLKH_TEST_PG_DSN phải được đặt, ví dụ:
      QLKH_TEST_PG_DSN=postgresql://user:pass@localhost:5432/qlkh_test
  - Nếu không có biến này hoặc không kết nối được, toàn bộ file bị skip.
  - CI: cần thêm service postgres vào workflow (xem .github/workflows/ci.yml).
    Cho đến khi infra-agent cấp service Postgres trong CI, các test này chạy
    local và trên staging DB — đây là nợ kỹ thuật đã ghi nhận (SD-25).

TRẠNG THÁI: skip nếu không có Postgres (verified_by = null trong PR cho đến khi
infra cấp service CI — ghi rõ trong PR description).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_DIR = REPO_ROOT / "db"
MIGRATIONS_DIR = DB_DIR / "migrations"

PG_DSN = os.environ.get("QLKH_TEST_PG_DSN", "")

# Skip toàn bộ module nếu không có DSN
pytestmark = pytest.mark.skipif(
    not PG_DSN,
    reason=(
        "QLKH_TEST_PG_DSN không được đặt — test Postgres thật bị skip. "
        "Đặt QLKH_TEST_PG_DSN=postgresql://... để chạy. "
        "SD-25: cần infra-agent cấp service Postgres trong CI."
    ),
)


def _psql(sql: str, dsn: str = PG_DSN) -> subprocess.CompletedProcess:
    """Chạy SQL qua psql, trả về CompletedProcess."""
    return subprocess.run(
        ["psql", dsn, "-c", sql, "--no-psqlrc", "-v", "ON_ERROR_STOP=1"],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _psql_file(path: Path, dsn: str = PG_DSN) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-f", str(path), "--no-psqlrc", "-v", "ON_ERROR_STOP=1"],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _check_psql_available() -> bool:
    try:
        r = subprocess.run(["psql", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="module")
def pg_dsn():
    """DSN Postgres test — skip nếu psql không cài hoặc không kết nối được."""
    if not _check_psql_available():
        pytest.skip("psql không tìm thấy trong PATH")
    # Kiểm kết nối
    r = _psql("SELECT 1;")
    if r.returncode != 0:
        pytest.skip(f"Không kết nối được Postgres ({PG_DSN}): {r.stderr[:200]}")
    return PG_DSN


@pytest.fixture()
def clean_schema(pg_dsn):
    """Đảm bảo schema test sạch trước và sau mỗi test."""
    # Teardown trước (phòng test trước bị gián đoạn)
    _psql_file(MIGRATIONS_DIR / "0003_pii_key_and_consent.down.sql", pg_dsn)
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.down.sql", pg_dsn)
    yield pg_dsn
    # Teardown sau
    _psql_file(MIGRATIONS_DIR / "0003_pii_key_and_consent.down.sql", pg_dsn)
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.down.sql", pg_dsn)


# ─────────────────────────────────────────────────────────────────────────────
# Gherkin 1 — apply/rollback thật trên DB rỗng
# ─────────────────────────────────────────────────────────────────────────────


def test_gherkin1_apply_0002_khong_loi(clean_schema):
    """Given DB rỗng, When apply 0002, Then không lỗi."""
    r = _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    assert r.returncode == 0, f"0002.up.sql lỗi:\n{r.stderr}"


def test_gherkin1_apply_0003_khong_loi(clean_schema):
    """Given 0002 đã apply, When apply 0003, Then không lỗi."""
    r0 = _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    assert r0.returncode == 0, f"0002.up.sql lỗi:\n{r0.stderr}"
    r1 = _psql_file(MIGRATIONS_DIR / "0003_pii_key_and_consent.up.sql", clean_schema)
    assert r1.returncode == 0, f"0003.up.sql lỗi:\n{r1.stderr}"


def test_gherkin1_idempotent_apply_0002(clean_schema):
    """Chạy 0002.up.sql hai lần không lỗi (IF NOT EXISTS)."""
    for _ in range(2):
        r = _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
        assert r.returncode == 0, f"0002.up.sql lỗi lần 2:\n{r.stderr}"


def test_gherkin1_idempotent_apply_0003(clean_schema):
    """Chạy 0003.up.sql hai lần không lỗi (IF NOT EXISTS / DROP CONSTRAINT IF EXISTS)."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    for _ in range(2):
        r = _psql_file(MIGRATIONS_DIR / "0003_pii_key_and_consent.up.sql", clean_schema)
        assert r.returncode == 0, f"0003.up.sql lỗi lần 2:\n{r.stderr}"


def test_gherkin1_rollback_0003_khong_loi(clean_schema):
    """Given 0003 đã apply, When rollback 0003, Then không lỗi."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    _psql_file(MIGRATIONS_DIR / "0003_pii_key_and_consent.up.sql", clean_schema)
    r = _psql_file(MIGRATIONS_DIR / "0003_pii_key_and_consent.down.sql", clean_schema)
    assert r.returncode == 0, f"0003.down.sql lỗi:\n{r.stderr}"


def test_gherkin1_rollback_0002_khong_loi(clean_schema):
    """Given 0002 đã apply, When rollback 0002, Then không lỗi và schema sạch."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    r = _psql_file(MIGRATIONS_DIR / "0002_core_schema.down.sql", clean_schema)
    assert r.returncode == 0, f"0002.down.sql lỗi:\n{r.stderr}"
    # Xác nhận bảng không còn
    r2 = _psql("SELECT to_regclass('public.students');", clean_schema)
    assert r2.returncode == 0
    assert "NULL" in r2.stdout or "(null)" in r2.stdout.lower(), (
        "Bảng students vẫn còn sau rollback 0002"
    )


def test_gherkin1_apply_rollback_full_cycle(clean_schema):
    """Full cycle: apply 0002 → 0003 → rollback 0003 → rollback 0002 → schema sạch."""
    for up in ["0002_core_schema.up.sql", "0003_pii_key_and_consent.up.sql"]:
        r = _psql_file(MIGRATIONS_DIR / up, clean_schema)
        assert r.returncode == 0, f"{up} lỗi:\n{r.stderr}"
    for down in ["0003_pii_key_and_consent.down.sql", "0002_core_schema.down.sql"]:
        r = _psql_file(MIGRATIONS_DIR / down, clean_schema)
        assert r.returncode == 0, f"{down} lỗi:\n{r.stderr}"
    # Sau full cycle, không còn bảng nào của schema
    r = _psql("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';", clean_schema)
    assert r.returncode == 0
    assert " 0 " in r.stdout or "|0" in r.stdout or r.stdout.strip().endswith("0"), (
        f"Vẫn còn bảng sau full cycle rollback:\n{r.stdout}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Block-1 thật: phone_key_version IS NULL được phép sau migration 0003
# ─────────────────────────────────────────────────────────────────────────────


def test_pg_phone_key_version_null_duoc_phep(clean_schema):
    """Dòng có phone_key_version IS NULL phải được INSERT thành công (expand phase)."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    _psql_file(MIGRATIONS_DIR / "0003_pii_key_and_consent.up.sql", clean_schema)

    # Tạo branch
    setup_sql = """
    INSERT INTO branches (id, code, name) VALUES
        ('00000000-0000-0000-0000-000000000001', 'BR01', 'Chi nhanh test');
    """
    r = _psql(setup_sql, clean_schema)
    assert r.returncode == 0, r.stderr

    # Insert parent với phone_key_version NULL (trạng thái trung gian hợp lệ)
    # phone_enc phải >= 32 byte và không phải plaintext số điện thoại
    insert_sql = r"""
    INSERT INTO parents (id, branch_id, full_name, phone_enc, phone_last4, phone_key_version)
    VALUES (
        '00000000-0000-0000-0000-000000000002',
        '00000000-0000-0000-0000-000000000001',
        'Nguyen Van A',
        decode(repeat('ab', 32), 'hex'),
        '1234',
        NULL
    );
    """
    r = _psql(insert_sql, clean_schema)
    assert r.returncode == 0, (
        f"INSERT với phone_key_version=NULL phải thành công ở expand phase:\n{r.stderr}"
    )


def test_pg_phone_key_version_invalid_bi_reject(clean_schema):
    """Giá trị phone_key_version không khớp '^v[0-9]+$' phải bị CHECK reject."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    _psql_file(MIGRATIONS_DIR / "0003_pii_key_and_consent.up.sql", clean_schema)

    _psql("""
    INSERT INTO branches (id, code, name) VALUES
        ('00000000-0000-0000-0000-000000000001', 'BR01', 'Chi nhanh test');
    """, clean_schema)

    insert_sql = r"""
    INSERT INTO parents (id, branch_id, full_name, phone_enc, phone_last4, phone_key_version)
    VALUES (
        '00000000-0000-0000-0000-000000000003',
        '00000000-0000-0000-0000-000000000001',
        'Tran Thi B',
        decode(repeat('ab', 32), 'hex'),
        '5678',
        'invalid_version'
    );
    """
    r = _psql(insert_sql, clean_schema)
    assert r.returncode != 0, "Giá trị phone_key_version='invalid_version' phải bị CHECK reject"


# ─────────────────────────────────────────────────────────────────────────────
# Block-4 thật: CHECK constraints — đường lỗi trên DB thật
# ─────────────────────────────────────────────────────────────────────────────


def test_pg_role_code_invalid_bi_reject(clean_schema):
    """users.role_code không hợp lệ bị FK/CHECK reject."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    _psql("""
    INSERT INTO roles (code, description) VALUES ('admin', 'Quan tri');
    """, clean_schema)
    r = _psql("""
    INSERT INTO users (email, password_hash, role_code)
    VALUES ('test@ex.com', 'hash', 'superuser');
    """, clean_schema)
    assert r.returncode != 0, "role_code='superuser' phải bị reject (không có trong roles)"


def test_pg_relation_invalid_bi_reject(clean_schema):
    """parent_student.relation không trong (father, mother, guardian) bị reject."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    _psql("""
    INSERT INTO branches (id, code, name) VALUES ('00000000-0000-0000-0000-000000000001','BR01','Test');
    INSERT INTO students (id, branch_id, full_name, date_of_birth)
    VALUES ('00000000-0000-0000-0000-000000000010','00000000-0000-0000-0000-000000000001','Hoc vien','2010-01-01');
    INSERT INTO parents (id, branch_id, full_name, phone_enc, phone_last4)
    VALUES ('00000000-0000-0000-0000-000000000020','00000000-0000-0000-0000-000000000001','PH',
            decode(repeat('ab',32),'hex'),'1234');
    """, clean_schema)
    r = _psql("""
    INSERT INTO parent_student (parent_id, student_id, relation)
    VALUES ('00000000-0000-0000-0000-000000000020',
            '00000000-0000-0000-0000-000000000010',
            'sibling');
    """, clean_schema)
    assert r.returncode != 0, "relation='sibling' phải bị CHECK reject"


def test_pg_classes_name_unique_per_branch(clean_schema):
    """UNIQUE(branch_id, name) trên classes — tên lớp trùng trong cùng cơ sở bị reject."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    _psql("""
    INSERT INTO branches (id, code, name) VALUES ('00000000-0000-0000-0000-000000000001','BR01','Test');
    INSERT INTO classes (id, branch_id, name)
    VALUES ('00000000-0000-0000-0000-000000000030','00000000-0000-0000-0000-000000000001','Lop A');
    """, clean_schema)
    r = _psql("""
    INSERT INTO classes (id, branch_id, name)
    VALUES ('00000000-0000-0000-0000-000000000031','00000000-0000-0000-0000-000000000001','Lop A');
    """, clean_schema)
    assert r.returncode != 0, "Tên lớp trùng trong cùng branch phải bị UNIQUE reject"


def test_pg_enrollments_unique_class_student(clean_schema):
    """UNIQUE(class_id, student_id) trên enrollments — ghi danh trùng bị reject (→ 409)."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    _psql("""
    INSERT INTO branches (id, code, name) VALUES ('00000000-0000-0000-0000-000000000001','BR01','Test');
    INSERT INTO students (id, branch_id, full_name, date_of_birth)
    VALUES ('00000000-0000-0000-0000-000000000010','00000000-0000-0000-0000-000000000001','HV','2010-01-01');
    INSERT INTO classes (id, branch_id, name)
    VALUES ('00000000-0000-0000-0000-000000000030','00000000-0000-0000-0000-000000000001','Lop A');
    INSERT INTO enrollments (id, class_id, student_id)
    VALUES ('00000000-0000-0000-0000-000000000040',
            '00000000-0000-0000-0000-000000000030',
            '00000000-0000-0000-0000-000000000010');
    """, clean_schema)
    r = _psql("""
    INSERT INTO enrollments (id, class_id, student_id)
    VALUES ('00000000-0000-0000-0000-000000000041',
            '00000000-0000-0000-0000-000000000030',
            '00000000-0000-0000-0000-000000000010');
    """, clean_schema)
    assert r.returncode != 0, "Ghi danh trùng phải bị UNIQUE reject"


# ─────────────────────────────────────────────────────────────────────────────
# Gherkin 3 — EXPLAIN không seq scan với 1.200 học viên
# ─────────────────────────────────────────────────────────────────────────────


def test_gherkin3_query_branch_id_dung_index(clean_schema):
    """Given 1.200 học viên, When EXPLAIN truy vấn theo branch_id, Then không Seq Scan."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)

    # Tạo branch
    _psql("""
    INSERT INTO branches (id, code, name) VALUES
        ('00000000-0000-0000-0000-000000000001', 'BR01', 'Chi nhanh 1');
    """, clean_schema)

    # Seed 1.200 học viên
    seed_sql = """
    INSERT INTO students (id, branch_id, full_name, date_of_birth)
    SELECT
        gen_random_uuid(),
        '00000000-0000-0000-0000-000000000001',
        'Hoc vien ' || i,
        '2010-01-01'::date + (i % 3000) * interval '1 day'
    FROM generate_series(1, 1200) AS s(i);
    """
    r = _psql(seed_sql, clean_schema)
    assert r.returncode == 0, f"Seed lỗi:\n{r.stderr}"

    # Cập nhật thống kê
    _psql("ANALYZE students;", clean_schema)

    # EXPLAIN truy vấn danh sách theo branch_id
    explain_sql = """
    EXPLAIN SELECT id, full_name, branch_id, created_at
    FROM students
    WHERE branch_id = '00000000-0000-0000-0000-000000000001'
      AND deleted_at IS NULL
    ORDER BY created_at DESC, id DESC
    LIMIT 50;
    """
    r = _psql(explain_sql, clean_schema)
    assert r.returncode == 0, f"EXPLAIN lỗi:\n{r.stderr}"
    plan = r.stdout.lower()
    assert "seq scan on students" not in plan, (
        f"Truy vấn theo branch_id dùng Seq Scan — index không được dùng:\n{r.stdout}"
    )
    assert "index" in plan, (
        f"EXPLAIN plan không dùng bất kỳ index nào:\n{r.stdout}"
    )


def test_gherkin3_query_classes_branch_id_dung_index(clean_schema):
    """GET /classes — truy vấn theo branch_id không seq scan."""
    _psql_file(MIGRATIONS_DIR / "0002_core_schema.up.sql", clean_schema)
    _psql("""
    INSERT INTO branches (id, code, name) VALUES
        ('00000000-0000-0000-0000-000000000001', 'BR01', 'Chi nhanh 1');
    INSERT INTO classes (id, branch_id, name)
    SELECT gen_random_uuid(), '00000000-0000-0000-0000-000000000001', 'Lop ' || i
    FROM generate_series(1, 100) AS s(i);
    """, clean_schema)
    _psql("ANALYZE classes;", clean_schema)

    r = _psql("""
    EXPLAIN SELECT id, name, branch_id, created_at
    FROM classes
    WHERE branch_id = '00000000-0000-0000-0000-000000000001'
    ORDER BY created_at DESC, id DESC
    LIMIT 50;
    """, clean_schema)
    assert r.returncode == 0, r.stderr
    plan = r.stdout.lower()
    assert "seq scan on classes" not in plan, f"Truy vấn classes theo branch_id dùng Seq Scan:\n{r.stdout}"
