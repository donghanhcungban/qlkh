-- Rollback QLKH-002 vòng 2. Idempotent, thứ tự ngược phụ thuộc.
--
-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  CẢNH BÁO PHÁP LÝ — KHÔNG CHẠY KHI CÓ DỮ LIỆU THẬT                ║
-- ║                                                                      ║
-- ║  1. `consents` là bằng chứng đồng ý hợp pháp (NĐ13 Đ.11).         ║
-- ║     Xóa bảng này = phá vỡ nghĩa vụ pháp lý không phục hồi được.   ║
-- ║                                                                      ║
-- ║  2. `phone_key_version` cho biết DEK nào mã hóa phone_enc.         ║
-- ║     Xóa cột này = không thể giải mã số điện thoại đã lưu.          ║
-- ║                                                                      ║
-- ║  QUY TRÌNH BẮT BUỘC TRƯỚC KHI CHẠY ROLLBACK TRÊN DB CÓ DỮ LIỆU:  ║
-- ║  a. Chạy scripts/snapshot_consents_before_rollback.sql để sao lưu  ║
-- ║     bảng consents ra bảng consents_snapshot_YYYYMMDDHHMMSS.         ║
-- ║  b. Xác nhận count(*) khớp giữa consents và bảng snapshot.         ║
-- ║  c. Xuất dump pg_dump -t consents -Fc > consents_TIMESTAMP.dump.   ║
-- ║  d. Ghi audit log: ai chạy, lý do, timestamp, row count.           ║
-- ║  e. Giải mã và di trú toàn bộ phone_enc về plaintext (hoặc       ║
-- ║     lưu ciphertext + key_version ra hệ thống ngoài) trước khi     ║
-- ║     xóa phone_key_version.                                          ║
-- ║                                                                      ║
-- ║  Chi tiết: docs/db/key-management.md, mục "Quy trình rollback"     ║
-- ╚══════════════════════════════════════════════════════════════════════╝

DROP INDEX IF EXISTS consents_active_purpose_uniq;
DROP INDEX IF EXISTS consents_student_purpose_idx;
DROP TABLE IF EXISTS consents;

ALTER TABLE parent_student DROP COLUMN IF EXISTS created_at;

ALTER TABLE parents DROP CONSTRAINT IF EXISTS parents_phone_enc_ciphertext_chk;
ALTER TABLE parents DROP CONSTRAINT IF EXISTS parents_phone_key_version_chk;
ALTER TABLE parents DROP COLUMN IF EXISTS phone_key_version;
