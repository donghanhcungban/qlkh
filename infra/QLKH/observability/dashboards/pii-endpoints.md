# Dashboard (cấu hình-như-code) — 5 endpoint PII QLKH

Nguồn: api/QLKH/openapi.yaml v1.4.0 (CR-OPS-001). Panel/query dưới đây là đặc tả để
release-engineer/backend import vào Grafana (hoặc tương đương) khi backend giám sát thật
(DEF-03) được chốt. **Chưa apply/import vào hệ thống thật nào** — xem giới hạn công cụ trong
`../alerts.yaml`.

Mỗi endpoint có 1 hàng panel RED (Rate, Errors, Duration); 3 endpoint liên quan uỷ quyền tầng
dữ liệu (ADR-004) có thêm panel 403/404 theo account_id để phát hiện dò quét IDOR.

## 1. POST /auth/login
- Panel `rate`: `sum(rate(http_requests_total{route="/auth/login"}[5m]))`
- Panel `errors (4xx/5xx)`: `sum(rate(http_requests_total{route="/auth/login",status=~"4..|5.."}[5m])) by (status)`
- Panel `duration p50/p95/p99`: `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{route="/auth/login"}[5m])) by (le))`
- Panel `401 rate (baseline 24h)`: cho brute-force alert
- Alert liên kết: auth-login-5xx-rate-high, auth-login-p95-latency-high, auth-login-401-spike-brute-force

## 2. GET /auth/me
- Panel `rate`, `errors`, `duration p95` tương tự (route="/auth/me")
- Panel `401 rate (baseline 24h)`: phát hiện thu hồi phiên bất thường (T-03)
- Alert liên kết: auth-me-5xx-rate-high, auth-me-p95-latency-high, auth-me-401-spike-session-revocation-anomaly

## 3. GET /students/{id}
- Panel `rate`, `errors`, `duration p95` (route="/students/{id}")
- Panel `403+404 theo account_id (top 10)`: `topk(10, sum(rate(http_requests_total{route="/students/{id}",status=~"403|404"}[5m])) by (account_id))`
  — dùng `account_id`, KHÔNG dùng `id`/`student_id` làm nhãn (tránh cardinality/PII, xem observability skill).
- Alert liên kết: students-id-5xx-rate-high, students-id-p95-latency-high, students-id-403-404-idor-scan

## 4. GET /students/{id}/consents
- Panel `rate`, `errors`, `duration p95` (route="/students/{id}/consents")
- Panel `403+404 theo account_id (top 10)`: tương tự mục 3
- Alert liên kết: students-consents-5xx-rate-high, students-consents-p95-latency-high, students-consents-403-404-idor-scan

## 5. POST /erasure-requests
- Panel `rate`, `errors`, `duration p95` (route="/erasure-requests")
- Panel `202 volume (baseline 7d)`: theo dõi spike bất thường yêu cầu xóa
- Panel `403 relationship-denied theo account_id (top 10)`: dò quét subject_student_id (RISK-3)
- Panel bổ trợ vận hành (không phải alert HTTP): tỉ lệ `erasure_sla_breach` từ audit log
  (threat-model v1.34 mục 25) — cảnh báo riêng thuộc phạm vi QLKH-013-b (chưa có backend giám sát).
- Alert liên kết: erasure-requests-5xx-rate-high, erasure-requests-p95-latency-high,
  erasure-requests-volume-spike-anomalous, erasure-requests-403-relationship-denied-spike

## Đối chiếu 5/5

| Endpoint | Có trong api-contract v1.4.0 | Panel RED | Panel IDOR | Alert file |
|---|---|---|---|---|
| POST /auth/login | có (openapi.yaml:243) | có | 401-spike thay thế | alerts.yaml#auth-login |
| GET /auth/me | có (openapi.yaml:287) | có | 401-spike thay thế | alerts.yaml#auth-me |
| GET /students/{id} | có (openapi.yaml:327) | có | có | alerts.yaml#students-detail |
| GET /students/{id}/consents | có (openapi.yaml:353) | có | có | alerts.yaml#students-consents |
| POST /erasure-requests | có (openapi.yaml:534) | có | có (403 relationship) | alerts.yaml#erasure-requests |

Không endpoint PII nào trong CR-OPS-001 bị thiếu dashboard/alert.

## Cách release-engineer đối chiếu thủ công (không có công cụ giám sát thật trong môi trường này)
1. So `## Đối chiếu 5/5` ở trên với danh sách path trong `api/QLKH/openapi.yaml` — chạy
   `grep -nE "^  /(auth/login|auth/me|students/\{id\}(/consents)?|erasure-requests):" api/QLKH/openapi.yaml`
   xác nhận đúng 5 dòng khớp.
2. Với mỗi dòng trong bảng "alert liên kết" ở alerts.yaml, tạo panel/alert thật trên backend
   (Grafana/Prometheus hay dịch vụ VN đã chọn theo DEF-03) giữ nguyên tên rule để so sánh được.
3. Chạy thử một request 403/404 liên tục >20 lần/5 phút trên môi trường staging cho
   /students/{id} và xác nhận `students-id-403-404-idor-scan` fire, noti tới security-engineer,
   link runbook mở được.
4. Ghi lại bằng chứng (ảnh chụp dashboard, log alert fired) vào ticket vận hành khi đóng
   QLKH-013-b/QLKH-013-d.
