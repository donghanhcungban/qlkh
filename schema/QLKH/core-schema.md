# Schema lõi QLKH — v4 (QLKH-002, REQ-002, vòng 4 — TCK-ADRDEBT-01)

Nguồn: architecture C4 L2, api-contract v1.0.0, ADR-004, ADR-007, NFR-006/007.
File chính:
- `db/migrations/0002_core_schema.{up,down}.sql`
- `db/migrations/0003_pii_key_and_consent.{up,down}.sql`
- `db/pii_metadata.json`
- `docs/adr/ADR-007-quan-ly-khoa-ma-hoa-cot.md`
- `docs/db/key-management.md` (đóng SD-23)
- `scripts/snapshot_consents_before_rollback.sql`
- `.github/workflows/ci.yml` (**sửa vòng 4** — thêm service Postgres thật cho job `test`, đóng SD-25)

## Vòng 4 (TCK-ADRDEBT-01, CR-ADR-DEBT-001) — SD-25: PostgreSQL service thật trong CI

`.github/workflows/ci.yml` job `test` giờ có `services.postgres` (image `postgres:16`,
health-check `pg_isready`) và đặt `QLKH_TEST_PG_DSN=postgresql://test:test@localhost:5432/qlkh_test`
trong `env` của job. `tests/schema/test_postgres_integration.py` (test-author sở hữu, không sửa)
đã sẵn cơ chế `pytestmark = pytest.mark.skipif(not PG_DSN, ...)` — trước đây biến này không được
đặt trong CI nên toàn bộ 17 test bị skip; từ vòng này biến LUÔN được đặt trong job `test` nên các
test chạy thật lên Postgres thật, không skip. Không sửa file test (ngoài phạm vi quyền của agent
`database` theo ADR-0028) — không cần sửa vì cơ chế skip có điều kiện đã đúng thiết kế, chỉ thiếu
hạ tầng cấp biến/service, đúng như mô tả nợ SD-25.

**Giới hạn xác minh của lượt này**: agent không có khả năng push lên remote / trigger GitHub
Actions thật (ngoài allowlist tool: chỉ có `lint`/`test` chạy cục bộ, không có `git push` hay
gọi API GitHub). `run test` cục bộ vẫn skip 17 test này vì sandbox không có service Postgres và
không đặt `QLKH_TEST_PG_DSN` — đây là hành vi ĐÚNG của cơ chế skip có điều kiện, không phải lỗi.
Bằng chứng "job CI pass thật, có link" theo yêu cầu DoD của ticket CHỈ có được sau khi PR này
được mở/merge và pipeline GitHub Actions thật chạy — việc đó thuộc phạm vi supervisor/release
(người có quyền push/merge), không phải việc agent `database` có thể tự làm trong worktree.

## Việc còn nợ
- **SD-25** (mã nguồn ĐÃ SỬA — chờ bằng chứng CI thật): CI đã có service Postgres thật + biến
  `QLKH_TEST_PG_DSN` đặt sẵn trong job `test` (xem `.github/workflows/ci.yml`, TCK-ADRDEBT-01).
  Trạng thái CHƯA chuyển hẳn sang `closed` trong tài liệu này vì chưa có link job CI thật chạy
  qua pipeline (agent không push/trigger được CI thật từ worktree). Đề nghị: sau khi PR
  TCK-ADRDEBT-01 merge và job `test` pass thật trên GitHub Actions, supervisor/release ghi link
  job đó vào đây và đổi dòng này thành `status: closed`, sau đó cập nhật
  `prd/QLKH/risk-register.json` `technical_debt_accepted.SD-25.status` → `closed`.
- **SD-14** (không còn chặn tuyệt đối cho mọi môi trường): chấp nhận rủi ro cho môi trường thử nghiệm
  theo RISK-6 (risk-register v21), bắt buộc trước khi phát hành thật. Chi tiết người chấp nhận, phạm vi
  và điều kiện mở lại: xem `docs/compliance/risk-acceptance.md` và `architecture/QLKH/c4.md` v2 mục
  "Điều kiện chặn Gate 3". DPIA vẫn là điều kiện chặn cứng cho phát hành production thật; không áp dụng
  cho môi trường thử nghiệm hiện tại (không có dữ liệu cá nhân thật của học viên/phụ huynh).
- **QLKH-014**: job retention/xóa P4 (REQ-011, NFR-007).
- **Migration 0004**: `ALTER COLUMN phone_key_version SET NOT NULL` sau khi backend xác nhận backfill hoàn tất.
- `erasure_requests`, `audit_log`, RLS (SD-19) thuộc ticket sau.

## Cập nhật tài liệu (TCK-CR-RISK-002-01, chỉ .md, không đổi migration/schema DB)

Theo CR-RISK-001: `prd/QLKH/risk-register.json` v21 (RISK-6 → `status=accepted` kèm
`risk_acceptance`) và `architecture/QLKH/c4.md` v2 (mục "Điều kiện chặn Gate 3") đã tách
điều kiện DPIA cho **môi trường THỬ NGHIỆM** khỏi điều kiện DPIA cho **phát hành thật**.
Mục "Việc còn nợ" bên trên được cập nhật cho khớp: DPIA không còn là điều
kiện chặn tuyệt đối cho *mọi* môi trường, mà chỉ chặn phát hành thật. Xem chi tiết điều
kiện chấp nhận rủi ro, phạm vi và điều kiện mở lại tại `docs/compliance/risk-acceptance.md`.
`db/pii_metadata.json` (`blocking_conditions.dpia`) không đổi trong ticket này — nội dung
đó đã nói "TRƯỚC khi migration ... áp lên môi trường **có dữ liệu thật**", tức đã tương
thích với cách hiểu mới, không cần sửa; đây không phải file `.md` và ngoài phạm vi ticket.

## Vòng 3 (đóng 4 block findings)

### [block-1 ĐÓNG] phone_key_version: expand phase an toàn
- **Xóa** `UPDATE parents SET phone_key_version = 'v1' WHERE phone_key_version IS NULL` khỏi 0003.up.sql.
- Cột `phone_key_version` giờ là **NULLABLE** (expand phase của expand–contract ADR-007).
- CHECK constraint: `phone_key_version IS NULL OR phone_key_version ~ '^v[0-9]+$'`.
- Lý do: gán 'v1' hardcode khi KMS chưa có DEK v1 → ứng dụng không giải mã được.
- SET NOT NULL sẽ ở **migration 0004** sau khi backend xác nhận backfill hoàn tất.
- Quy trình backfill: xem `docs/db/key-management.md`, mục "Quy trình backfill".

### [block-2 ĐÓNG] Rollback có quy trình cụ thể và tài liệu
- Tạo `docs/db/key-management.md`: quy trình backfill, xoay vòng khóa, rollback 5-bước, audit log bắt buộc, phân quyền KMS.
- Tạo `scripts/snapshot_consents_before_rollback.sql`: tự động snapshot + verify row count + ghi audit.
- Cập nhật `0003.down.sql`: cảnh báo pháp lý tường minh (NĐ13 Đ.11, phone_key_version).

### [block-3 — nợ SD-25, xem mục "Vòng 4" ở trên] Test Postgres thật
- Tạo `tests/schema/test_postgres_integration.py` với 17 test (Gherkin 1 full cycle, Gherkin 3 EXPLAIN, Block-1 NULL, Block-4 constraints thật).
- Auto-skip khi `QLKH_TEST_PG_DSN` không đặt — từ vòng 4, CI luôn đặt biến này nên chạy thật.

### [block-4 ĐÓNG] Đường lỗi CHECK constraints (kiểm tĩnh)
- 9 test tĩnh trong `test_pii_key_and_consent.py`: role_code enum, relation CHECK, classes UNIQUE, enrollments UNIQUE, status enums, consents withdrawn consistency.
- Test thật tương ứng trong `test_postgres_integration.py` (chạy thật từ vòng 4, xem trên).

## Bảng và chủ sở hữu context (không đổi từ v2)
| Context | Bảng |
|---|---|
| Identity & Access | `branches`, `roles`, `users`, `user_branch_scope` |
| People | `students`, `parents`, `parent_student`, `teachers` |
| Teaching | `classes`, `enrollments` |
| Compliance | `consents` |

## Schema migrations

### 0002_core_schema (không đổi)
- Tất cả 10 bảng lõi, 5 index, ràng buộc toàn vẹn.
- Rollback: xóa theo thứ tự ngược FK.

### 0003_pii_key_and_consent (không đổi từ v3)
- `parents.phone_key_version text NULL CHECK (IS NULL OR ~ '^v[0-9]+$')` — expand phase.
- `parents_phone_enc_ciphertext_chk`: `octet_length >= 32 AND encode != phone pattern`.
- `parent_student.created_at timestamptz NOT NULL DEFAULT now()` — mốc retention M-4.
- Bảng `consents` với tất cả ràng buộc.
- Index `consents_student_purpose_idx` và `consents_active_purpose_uniq`.
- Rollback: xóa theo thứ tự ngược; cảnh báo pháp lý tường minh trong file.

## Index (không đổi từ v2)
| Index | Truy vấn phục vụ |
|---|---|
| `students_branch_created_idx (branch_id, created_at DESC, id DESC) WHERE deleted_at IS NULL` | `GET /students` |
| `classes_branch_created_idx (branch_id, created_at DESC, id DESC)` | `GET /classes` |
| `enrollments_class_student_idx (class_id, student_id) WHERE status='active'` | điểm danh hàng loạt |
| `enrollments_student_idx (student_id)` | màn hình phụ huynh |
| `user_branch_scope_branch_idx (branch_id)` | tài khoản theo cơ sở |
| `consents_student_purpose_idx (student_id, purpose, granted_at DESC)` | GET /students/{id}/consents |
| `consents_active_purpose_uniq (student_id, purpose) WHERE status='granted'` | một đồng ý/mục đích |

EXPLAIN thật trên Postgres: xem `tests/schema/test_postgres_integration.py::test_gherkin3_*` — chạy thật trong CI từ vòng 4 (service Postgres, xem trên).

## PII Metadata (không đổi từ v2)
Mọi cột PII có `legal_basis`, `purpose`, `retention_days` ≤ 730, `retention_anchor`, `enforced_by`, `access_roles`. Cột `phone_enc` có thêm `key_version_column` và `key_management_ref`.

## Migration kiểm tự động
`python -m tools.schema_meta db` — kiểm idempotent, rollback pair, PII metadata, anchor tồn tại, encrypted_at_rest fields.
Test: `tests/schema/test_core_schema.py` (29 test), `tests/schema/test_pii_key_and_consent.py` (38 test), `tests/schema/test_postgres_integration.py` (17 test, chạy thật trong CI từ vòng 4; skip cục bộ nếu không đặt `QLKH_TEST_PG_DSN`/không có Postgres local).
