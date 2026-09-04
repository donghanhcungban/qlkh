# Quản lý khóa mã hóa cột — `parents.phone_enc`

Tài liệu: ADR-007 | Ticket: QLKH-002 / REQ-002 | Chủ sở hữu: security-engineer

## Tổng quan

`parents.phone_enc` (bytea) được mã hóa ở tầng ứng dụng bằng AES-256-GCM.  
Khóa dữ liệu (DEK) được bọc bởi Khóa mã hóa khóa (KEK) trong KMS managed đặt tại Việt Nam (ADR-006).  
Phiên bản DEK được ghi vào `parents.phone_key_version` (định dạng `v[0-9]+`, ví dụ `v1`, `v2`).

---

## Quy trình backfill sau migration 0003

Migration 0003 thêm cột `phone_key_version` ở trạng thái **NULLABLE** (expand phase của expand–contract).  
Tầng ứng dụng **phải** thực hiện backfill trước khi migration 0004 (SET NOT NULL) được chạy.

### Bước backfill (thực hiện bởi backend service, không phải migration SQL)

```
1. Tạo DEK v1 trong KMS VN; ghi key_id vào vault.
2. Với mỗi lô 5.000 dòng có phone_key_version IS NULL:
   a. Đọc phone_enc hiện tại.
   b. Giải mã (nếu cần) — dữ liệu legacy chưa mã hóa: mã hóa lại bằng DEK v1.
      Dữ liệu đã mã hóa: giữ nguyên ciphertext, chỉ ghi phone_key_version.
   c. UPDATE parents SET phone_key_version = 'v1'
      WHERE id IN (<lô hiện tại>) AND phone_key_version IS NULL;
   d. Nghỉ 200 ms giữa các lô để tránh lock contention.
3. Xác nhận: SELECT COUNT(*) FROM parents WHERE phone_key_version IS NULL; → phải = 0.
4. Báo cho database-agent chạy migration 0004 (ALTER COLUMN phone_key_version SET NOT NULL).
```

**Không được** chạy `UPDATE parents SET phone_key_version = 'v1'` trong SQL migration
vì lệnh này chạy mà không có DEK v1 thật trong KMS sẽ gán nhãn sai, gây lỗi giải mã hàng loạt.

---

## Quy trình xoay vòng khóa (định kỳ 12 tháng hoặc khi nghi lộ)

```
1. Tạo DEK v(n+1) trong KMS; ghi key_id.
2. Ứng dụng ghi mới bằng v(n+1), đọc được cả v(n) và v(n+1).
3. Backfill theo lô 5.000 dòng (tương tự bước trên):
   - Giải mã bằng DEK v(n), mã hóa lại bằng DEK v(n+1).
   - UPDATE phone_enc, phone_key_version = 'v(n+1)'.
4. Xác nhận: SELECT COUNT(*) FROM parents WHERE phone_key_version = 'v{n}'; → phải = 0.
5. Thu hồi DEK v(n) trong KMS; ghi audit log.
```

---

## Quy trình rollback migration 0003 (chỉ cho DB có dữ liệu thật)

> ⚠️ **Chỉ thực hiện khi có sự cố nghiêm trọng và được phê duyệt bởi security-engineer + tech lead.**

### Bước bắt buộc trước khi chạy 0003.down.sql

```sql
-- Bước A: Tạo bản sao consents ra bảng lưu trữ
CREATE TABLE consents_snapshot_20260904_120000 AS
    SELECT *, now() AS snapshot_at FROM consents;

-- Bước B: Xác nhận số dòng khớp
-- Phải = 0 thì mới tiếp tục
SELECT (SELECT COUNT(*) FROM consents)
     - (SELECT COUNT(*) FROM consents_snapshot_20260904_120000) AS diff;

-- Bước C (ngoài DB): Xuất dump
-- pg_dump -h $HOST -U $USER -d $DB -t consents -Fc > consents_$(date +%Y%m%d%H%M%S).dump
```

### Script tham chiếu

Xem `scripts/snapshot_consents_before_rollback.sql` để chạy tự động.

### Bước xử lý phone_key_version trước khi rollback

```
1. Backend: đọc toàn bộ (phone_enc, phone_key_version), giải mã, lưu plaintext ra hệ thống ngoài.
2. Hoặc: xuất ciphertext + key_version ra backup mã hóa, ghi kèm audit.
3. CHỈ SAU KHI xác nhận xong: chạy 0003.down.sql.
```

### Audit log bắt buộc

Ghi vào `audit_log` (hoặc hệ thống log tập trung):
- `actor`: ai phê duyệt và ai thực thi
- `action`: `rollback_migration_0003`
- `timestamp`: ISO 8601 UTC
- `consents_row_count`: số dòng trước khi xóa
- `parents_with_phone_key_version`: số dòng trước khi xóa cột
- `evidence`: tên file dump, tên bảng snapshot

---

## Phân quyền KMS

| Vai          | Quyền KMS           | Ghi chú                                  |
|---|---|---|
| `system` (P1) | Encrypt / Decrypt    | Vai duy nhất được đọc plaintext phone    |
| `admin`       | Không có             | Admin DB không giải mã được              |
| `security-engineer` | Key policy admin | Tạo / thu hồi DEK, không đọc plaintext |

---

## Tham chiếu

- ADR-007: `docs/adr/ADR-007-quan-ly-khoa-ma-hoa-cot.md`
- Script snapshot: `scripts/snapshot_consents_before_rollback.sql`
- Migration up: `db/migrations/0003_pii_key_and_consent.up.sql`
- Migration down: `db/migrations/0003_pii_key_and_consent.down.sql`
- Ticket QLKH-014: job retention/xóa P4 (xóa phone_enc khi hết retention)
