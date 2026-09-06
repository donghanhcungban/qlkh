# RB-AUTH-LOGIN-BRUTEFORCE — Spike 401 bất thường trên POST /auth/login

**Triệu chứng**: alert `auth-login-401-spike-brute-force` fire — tần suất 401 vượt 5x baseline 24h.
**Liên quan**: RISK-3 (threat-model), khóa 5 lần/15 phút theo tài khoản + throttle IP (openapi.yaml).

## Xác nhận
1. Dashboard panel `401 rate (baseline 24h)`.
2. Kiểm phân bố theo IP/tài khoản trong log (không lộ PII thô — theo QLKH-013 scrubber).
3. Xác nhận khóa 5 lần/15 phút và throttle IP đang hoạt động đúng (429 có tăng tương ứng không).

## Giảm nhẹ
- Nếu là tấn công dò mật khẩu thật: hạ ngưỡng rate-limit tạm thời qua config (không sửa tay hạ tầng),
  cân nhắc chặn IP nguồn qua WAF/hạ tầng biên nếu có.
- Nếu là lỗi client (retry sai): liên hệ đội frontend/release-engineer.

## Leo thang
- Nghi ngờ tấn công có chủ đích quy mô lớn → mở incident theo `incident-management`, SEV theo phạm vi tài khoản bị ảnh hưởng.

## Chủ sở hữu
security-engineer
