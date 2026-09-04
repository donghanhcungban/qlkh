-- Rollback QLKH-002 vòng 2. Idempotent, thứ tự ngược phụ thuộc.
-- Cảnh báo dữ liệu: xóa `consents` làm mất bằng chứng đồng ý; chỉ chạy sau khi
-- đã snapshot logic bảng consents (quy trình trong docs/db/key-management.md).

DROP INDEX IF EXISTS consents_active_purpose_uniq;
DROP INDEX IF EXISTS consents_student_purpose_idx;
DROP TABLE IF EXISTS consents;

ALTER TABLE parent_student DROP COLUMN IF EXISTS created_at;

ALTER TABLE parents DROP CONSTRAINT IF EXISTS parents_phone_enc_ciphertext_chk;
ALTER TABLE parents DROP CONSTRAINT IF EXISTS parents_phone_key_version_chk;
ALTER TABLE parents DROP COLUMN IF EXISTS phone_key_version;
