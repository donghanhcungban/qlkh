# ADR-007 — Quản lý khóa mã hóa cột PII (`parents.phone_enc`)

- Trạng thái: proposed (cần security-engineer duyệt trước khi áp production)
- Ngày: 2026-09-04
- Ticket: QLKH-002 — REQ-002; đóng M-1 của deep-review (ASVS 6.2/6.4), SD-16
- Liên quan: NFR-006/007, T-11, ADR-006 (residency VN)

## Bối cảnh
`parents.phone_enc bytea` được khai báo `encrypted_at_rest` trong `db/pii_metadata.json`
nhưng vòng 1 không nói mã hóa bằng cách nào, ai giữ khóa, xoay vòng ra sao, và
schema không ngăn tầng ứng dụng ghi plaintext vào cột bytea.

## Quyết định
1. **Mã hóa ở tầng ứng dụng, không dùng `pgcrypto` trong SQL.** Lý do: nếu mã hóa
   trong câu lệnh SQL thì khóa đi qua log truy vấn và nằm trong tầm nhìn của DBA;
   `pgcrypto` vẫn được bật chỉ để dùng `gen_random_uuid()`.
2. **KMS**: khóa gốc (KEK) do dịch vụ KMS managed đặt tại Việt Nam giữ (ADR-006);
   khóa dữ liệu (DEK) AES-256-GCM được bọc bởi KEK, ứng dụng lấy qua vai IAM của
   tiến trình P1. Không có khóa nào nằm trong repo, env file hay fixture test.
3. **Phiên bản khóa**: cột `parents.phone_key_version text NOT NULL` với ràng buộc
   `^v[0-9]+$`, ghi phiên bản DEK đã dùng. Không có phiên bản thì không giải mã
   được sau khi xoay vòng.
4. **Xoay vòng**: định kỳ 12 tháng hoặc ngay khi nghi lộ. Quy trình: tạo `v(n+1)`
   → ứng dụng ghi mới bằng `v(n+1)`, đọc được cả hai → backfill theo lô 5.000
   dòng, nghỉ 200 ms → khi không còn dòng `v(n)` thì hủy DEK cũ ở KMS.
5. **Ràng buộc chống plaintext ở DB** (`parents_phone_enc_ciphertext_chk`):
   `octet_length(phone_enc) >= 32` và `encode(phone_enc,'escape') !~ '^[0-9+() .-]+$'`.
   Ciphertext AES-GCM (nonce 12B + tag 16B + payload) luôn thỏa; số điện thoại ghi
   thô luôn vi phạm. Đây là lưới an toàn của schema, không thay cho review code.
6. **Ai giữ khóa**: security-engineer sở hữu chính sách KMS; database-agent không có
   quyền giải mã; vai `system` (tiến trình ứng dụng) là vai duy nhất được đọc cột.

## Hệ quả
- Truy vấn theo số điện thoại chính xác không làm được trực tiếp; hiển thị dùng
  `phone_last4`, tra cứu dùng chỉ mục băm ở ticket sau nếu có nhu cầu đo được.
- Rollback migration 0003 xóa `phone_key_version` → phải giải mã/di trú trước.

## Phương án đã loại
- `pgcrypto` `pgp_sym_encrypt` trong SQL: khóa lọt vào log/plan, khó xoay vòng.
- TDE toàn đĩa đơn thuần: không chống được đọc qua kết nối DB hợp lệ.

## Việc chưa đóng (không thuộc ticket này)
- SD-14 DPIA dữ liệu trẻ em — chặn triển khai, chủ: security-engineer.
- QLKH-014 job retention P4 — chặn thu thập PII ở production.
