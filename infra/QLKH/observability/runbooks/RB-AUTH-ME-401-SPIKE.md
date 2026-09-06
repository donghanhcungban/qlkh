# RB-AUTH-ME-401-SPIKE — Spike 401 bất thường trên GET /auth/me

**Triệu chứng**: alert `auth-me-401-spike-session-revocation-anomaly` fire.
**Liên quan**: T-03 (thu hồi toàn bộ phiên khi tài khoản bị vô hiệu hóa).

## Xác nhận
1. Dashboard panel `401 rate (baseline 24h)`.
2. Kiểm có đợt vô hiệu hóa tài khoản hàng loạt hợp lệ (giáo vụ xử lý) hay là lỗi thu hồi phiên sai/tấn công session.
3. Đối chiếu audit_log các thao tác vô hiệu hóa tài khoản trong cùng khung giờ.

## Giảm nhẹ
- Nếu là lỗi logic thu hồi phiên: rollback bản phát hành liên quan.
- Nếu là hành vi hợp lệ (đợt vô hiệu hóa lớn theo kế hoạch): đóng alert kèm ghi chú, không cần giảm nhẹ.

## Leo thang
- Nghi tấn công chiếm phiên hàng loạt → incident-management, mời security-engineer.

## Chủ sở hữu
security-engineer
