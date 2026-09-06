# RB-AUTH-LOGIN-LATENCY — p95 cao trên POST /auth/login

**Triệu chứng**: alert `auth-login-p95-latency-high` fire (p95 > 1.0s trong 10 phút).

## Xác nhận
1. Dashboard `pii-endpoints.md#1-post-authlogin`, panel `duration p50/p95/p99`.
2. Kiểm CPU/latency DB (argon2id hashing có chi phí CPU đáng kể theo thiết kế — ADR-002; phân biệt
   chậm do hash cố ý và chậm do tài nguyên bị nghẽn).
3. Kiểm rate-limit/khóa tạm có đang áp sai gây retry dồn dập không.

## Giảm nhẹ
- Scale ứng dụng theo IaC nếu do CPU; không giảm chi phí argon2id (bảo mật > tốc độ ở đây).
- Nếu do DB: kiểm slow query log, timeout 5s theo architecture.md.

## Leo thang
- Không cải thiện sau 30 phút → escalate platform lead; đánh giá ảnh hưởng SLO đăng nhập.

## Chủ sở hữu
platform-oncall
