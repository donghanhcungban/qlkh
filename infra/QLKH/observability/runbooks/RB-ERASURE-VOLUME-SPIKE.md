# RB-ERASURE-VOLUME-SPIKE — Spike bất thường số yêu cầu xóa (202) được chấp nhận

**Triệu chứng**: alert `erasure-requests-volume-spike-anomalous` fire — volume 202 vượt 5x baseline 7 ngày.

## Xác nhận
1. Dashboard panel `202 volume (baseline 7d)`.
2. Kiểm nguồn request: một vài tài khoản gửi hàng loạt hay phân bố tự nhiên (ví dụ cuối năm học,
   nhiều phụ huynh cùng rút hồ sơ — có thể là hợp lệ theo mùa vụ).
3. Đối chiếu audit `erasure_requested` để xác nhận không phải lỗi client gửi trùng lặp (idempotency, W1 threat-model).

## Giảm nhẹ
- Nếu là lỗi client gửi trùng: phối hợp release-engineer/frontend sửa retry.
- Nếu là tấn công/lạm dụng: rate-limit theo tài khoản.
- Nếu hợp lệ theo mùa vụ: đóng alert, cân nhắc điều chỉnh baseline theo mùa (đổi qua PR riêng, không sửa tay).

## Leo thang
- Nghi lạm dụng có chủ đích ảnh hưởng SLA xóa 30 ngày (RISK-8) → báo security-engineer + compliance.

## Chủ sở hữu
security-engineer
