-- QLKH-002 / REQ-002 (vòng 2) — đóng M-1, M-3, M-4 của deep-review.
--
-- M-1 Quản lý khóa: `parents.phone_enc` được mã hóa ở tầng ứng dụng (ADR-007,
--     docs/adr/ADR-007-quan-ly-khoa-ma-hoa-cot.md). Schema ràng buộc để không
--     ghi được plaintext: ciphertext tối thiểu 32 byte và không giải được thành
--     chuỗi chỉ gồm chữ số/dấu + (dạng số điện thoại thường).
--
--     EXPAND PHASE (expand–contract ADR-007):
--     Cột `phone_key_version` được thêm với giá trị NULL cho phép.
--     Tầng ứng dụng có trách nhiệm backfill với phiên bản DEK thật từ KMS
--     (xem docs/db/key-management.md, mục "Quy trình backfill").
--     SET NOT NULL sẽ được thực hiện ở migration 0004 sau khi backfill hoàn tất.
--     LÝ DO AN TOÀN: UPDATE hardcode 'v1' mà không có DEK v1 tồn tại trong KMS
--     sẽ khiến tầng ứng dụng không giải mã được sau khi migration (ADR-007 §3).
--
-- M-3 Bảng `consents` chứng minh cơ sở pháp lý `dong_y_cua_cha_me` (NĐ13 Đ.11;
--     khớp /consents và DELETE /consents/{id} của api-contract v1.0.0).
-- M-4 Mốc thời gian cho job retention P4 (ticket QLKH-014) trên mọi bảng PII;
--     `db/pii_metadata.json` khai báo `retention_anchor` + `enforced_by`.
--
-- CHẶN TRIỂN KHAI: migration này KHÔNG được áp lên môi trường có dữ liệu thật
-- trước khi DPIA (SD-14, NĐ 13/2023/NĐ-CP, dữ liệu trẻ em) được ký. Chủ sở hữu:
-- security-engineer. Đây là điều kiện chặn B-1 của REL-001.
--
-- Expand-only, idempotent, rollback: 0003_pii_key_and_consent.down.sql

-- M-1: Thêm cột phiên bản khóa (NULLABLE — expand phase; backfill thực hiện bởi app)
ALTER TABLE parents ADD COLUMN IF NOT EXISTS phone_key_version text;
-- KHÔNG có UPDATE hardcode ở đây: phone_key_version = NULL cho đến khi app backfill
-- với phiên bản DEK thật. SET NOT NULL ở migration 0004 sau backfill.

ALTER TABLE parents DROP CONSTRAINT IF EXISTS parents_phone_key_version_chk;
ALTER TABLE parents ADD CONSTRAINT parents_phone_key_version_chk
    CHECK (phone_key_version IS NULL OR phone_key_version ~ '^v[0-9]+$');

-- Chống ghi plaintext vào cột bytea: ciphertext AES-GCM (nonce 12 + tag 16 + payload)
-- luôn > 32 byte và không bao giờ giải escape ra chuỗi số điện thoại thuần.
ALTER TABLE parents DROP CONSTRAINT IF EXISTS parents_phone_enc_ciphertext_chk;
ALTER TABLE parents ADD CONSTRAINT parents_phone_enc_ciphertext_chk
    CHECK (octet_length(phone_enc) >= 32
           AND encode(phone_enc, 'escape') !~ '^[0-9+() .-]+$');

-- Mốc thời gian cho job retention (M-4).
ALTER TABLE parent_student ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS consents (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id       uuid NOT NULL REFERENCES students (id) ON DELETE RESTRICT,
    purpose          text NOT NULL CHECK (purpose IN ('service_delivery', 'notification', 'photo_publication')),
    document_version text NOT NULL,
    granted_by       uuid NULL REFERENCES parents (id) ON DELETE SET NULL,
    granted_at       timestamptz NOT NULL DEFAULT now(),
    withdrawn_at     timestamptz NULL,
    status           text NOT NULL DEFAULT 'granted' CHECK (status IN ('granted', 'withdrawn')),
    CONSTRAINT consents_status_withdrawn_chk
        CHECK ((status = 'withdrawn') = (withdrawn_at IS NOT NULL)),
    CONSTRAINT consents_withdrawn_after_granted_chk
        CHECK (withdrawn_at IS NULL OR withdrawn_at >= granted_at)
);

-- Truy vấn: GET /students/{id}/consents và kiểm cơ sở pháp lý trước khi ghi PII trẻ em.
CREATE INDEX IF NOT EXISTS consents_student_purpose_idx
    ON consents (student_id, purpose, granted_at DESC);

-- Một mục đích chỉ có tối đa một đồng ý còn hiệu lực (mỗi mục đích một bản ghi riêng).
CREATE UNIQUE INDEX IF NOT EXISTS consents_active_purpose_uniq
    ON consents (student_id, purpose) WHERE status = 'granted';
