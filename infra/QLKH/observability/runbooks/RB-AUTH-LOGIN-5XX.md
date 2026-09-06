# RB-AUTH-LOGIN-5XX — Tỉ lệ 5xx cao trên POST /auth/login

**Triệu chứng**: alert `auth-login-5xx-rate-high` fire (>2% lỗi 5xx trong 5 phút).
**Ảnh hưởng người dùng**: phụ huynh/giáo viên/giáo vụ không đăng nhập được.

## Xác nhận
1. Xem dashboard `pii-endpoints.md#1-post-authlogin`, panel `errors` — xác nhận status cụ thể (500/502/503).
2. Kiểm log ứng dụng lọc `route="/auth/login"` và `status>=500` trong cùng cửa sổ.
3. Kiểm DB/session store (Redis) có timeout/lỗi kết nối không (architecture.md — bảng "Xử lý khi phụ thuộc hỏng").

## Giảm nhẹ
- Nếu do session store (Redis) hỏng: theo bảng phụ thuộc, hệ thống nên tự chuyển sang "từ chối đăng nhập mới,
  phiên hiện có suy giảm" — xác nhận hành vi này đang đúng, không phải 500 tràn lan.
- Nếu do DB quá tải: kiểm connection pool, cân nhắc scale tạm read replica (qua IaC, không sửa tay).
- Nếu do lỗi triển khai gần đây: rollback theo pipeline release-engineer.

## Leo thang
- Không tự giảm sau 15 phút giảm nhẹ → escalate incident-management, chỉ huy sự cố theo SEV dựa trên số người dùng ảnh hưởng.

## Chủ sở hữu
platform-oncall
