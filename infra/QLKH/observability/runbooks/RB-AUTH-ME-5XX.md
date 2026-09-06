# RB-AUTH-ME-5XX — Tỉ lệ 5xx cao trên GET /auth/me

**Triệu chứng**: alert `auth-me-5xx-rate-high` fire (>2% lỗi 5xx trong 5 phút).
**Ảnh hưởng**: mọi trang cần biết chủ phiên sẽ lỗi (endpoint gọi ở hầu hết luồng UI).

## Xác nhận
1. Dashboard `pii-endpoints.md#2-get-authme`, panel `errors`.
2. Kiểm DB (bảng users/sessions) và Redis — /auth/me đọc trạng thái vô hiệu hóa tài khoản mỗi request.

## Giảm nhẹ
- Theo bảng phụ thuộc architecture.md: DB hỏng → 503 + alert là hành vi mong đợi; xác nhận không phải lỗi logic khác.
- Rollback nếu liên quan bản phát hành gần nhất.

## Leo thang
- Không cải thiện sau 15 phút → incident-management.

## Chủ sở hữu
platform-oncall
