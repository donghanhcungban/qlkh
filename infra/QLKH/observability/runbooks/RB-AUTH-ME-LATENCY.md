# RB-AUTH-ME-LATENCY — p95 cao trên GET /auth/me

**Triệu chứng**: alert `auth-me-p95-latency-high` fire (p95 > 0.5s trong 10 phút).

## Xác nhận
1. Dashboard panel `duration p95`.
2. Endpoint gọi rất thường xuyên (mỗi trang) — kiểm N+1 query hoặc thiếu cache trạng thái phiên.

## Giảm nhẹ
- Kiểm session store (Redis) latency; nếu Redis chậm, cân nhắc scale theo IaC.
- Không cache kết quả /auth/me quá lâu ở phía server vì cần kiểm tài khoản bị vô hiệu hóa realtime (T-03).

## Leo thang
- Không cải thiện sau 30 phút → platform lead.

## Chủ sở hữu
platform-oncall
