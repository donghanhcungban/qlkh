# QLKH-013 — Logging cắt PII, quan sát được, chặn dữ liệu rời VN

Nguồn: NFR-006/007, threat-model T-13/RISK-9, architecture (TB-7: giám sát chỉ
nhận log đã cắt PII), infra v7 (SD-06: quy tắc phát hiện PII thô trong log).

## 1. Cắt PII khỏi log (scope 1+2)

Module `qlkh/infrastructure/observability/log_scrubber.py`:

- **Allowlist trường** (`ALLOWED_FIELDS`) — trường không được liệt kê bị loại
  bỏ khỏi bản ghi (fail-closed), không phải blocklist chạy theo sau.
- **`FORBIDDEN_FIELDS`**: `password*`, `otp*`, `mfa_code`, `token*`,
  `session_cookie`, `authorization`... — xuất hiện thì `scrub_log_record` raise
  `ForbiddenFieldError` ngay, không âm thầm lọc rồi cho log đi tiếp. Ứng dụng
  gọi hàm này ở lớp logging trung tâm; lỗi này phải lộ ra khi test/CI, không
  phải khi log thật đã rời hệ thống.
- **`MASKABLE_FIELDS`** (`phone`, `email`...) và trường tự do `message`: quét
  bằng regex SĐT VN (`0|+84` + 9–10 chữ số) và email, che phần giữa.
- **`scrub_for_external_sink`**: áp thêm quy tắc riêng cho luồng ra E5 (TB-7)
  — bỏ cả `user_id` (định danh nội bộ), chỉ giữ tối thiểu cần để vận hành.

Đóng SD-06 (infra v7: "quy tắc phát hiện PII thô trong log") ở mức code +
test; **còn thiếu để đóng hẳn**: bật middleware này trong tầng logging thật
của ứng dụng khi endpoint đầu tiên ghi log request/response (chưa có endpoint
nào tồn tại tính tới ticket này — QLKH-004 mới có auth service nội bộ, chưa có
HTTP layer). Ghi rõ trong nợ mở bên dưới để agent viết endpoint kế tiếp phải
gọi `scrub_log_record`/`scrub_for_external_sink`, không tự log dict thô.

## 2. Metric/trace gắn nhãn phiên bản phát hành (scope 3)

`qlkh/infrastructure/observability/metrics.py`: `with_release_label(labels)`
thêm `release_version` đọc từ env `QLKH_RELEASE_VERSION` (Twelve-Factor, config
qua env) vào mọi bộ nhãn metric/span trước khi export — cho phép so
trước/sau bản phát hành trong dashboard.

## 3. Alert 5xx và p95 (scope 3) — khai báo, chưa có backend giám sát thật

Chưa có dịch vụ giám sát tại VN được chọn (DEF-03 vẫn mở, xem prd RISK-7) nên
chưa thể tạo alert/dashboard thật trong một hệ thống cụ thể. Khai báo trước ở
đây làm hợp đồng cho khi DEF-03 chốt:

```yaml
# alerts/qlkh-http.yaml (khai báo — áp dụng khi có backend giám sát tại VN)
service: qlkh-api
labels_required: [release_version, route, environment]
alerts:
  - name: http-5xx-burn-rate-fast
    expr: "rate(http_requests_total{status=~'5..'}[5m]) / rate(http_requests_total[5m]) > 0.05"
    for: 5m
    severity: page
    runbook: runbooks/RB-QLKH-013-http-5xx.md
  - name: http-5xx-burn-rate-slow
    expr: "rate(http_requests_total{status=~'5..'}[1h]) / rate(http_requests_total[1h]) > 0.02"
    for: 30m
    severity: ticket
    runbook: runbooks/RB-QLKH-013-http-5xx.md
  - name: attendance-p95-latency
    expr: "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{route='/attendance'}[5m])) > 1.0"
    for: 10m
    severity: page
    runbook: runbooks/RB-QLKH-013-p95-attendance.md
```

Runbook tối thiểu (RB-QLKH-013-http-5xx.md — nội dung tóm tắt, viết đầy đủ khi
có backend thật):
1. Triệu chứng: tỉ lệ 5xx vượt ngưỡng ở route nào, từ khi nào (nhãn `release_version`
   giúp xác định có phải do bản phát hành gần nhất).
2. Xác nhận: so `release_version` hiện tại vs bản trước trong dashboard RED.
3. Giảm nhẹ: rollback bằng IaC/feature flag nếu mới deploy; nếu do phụ thuộc
   (DB/bucket) theo bảng "xử lý khi phụ thuộc hỏng" ở `architecture`.
4. Leo thang: theo `incident-management` nếu SEV1/2.

## 4. Residency VN cho DB/bucket/log (scope acceptance 3)

`policy/storage.rego` mở rộng:
- Thêm `log_types` (`log_sink`, `logging_sink`, `log_group`, `observability_sink`)
  và deny-rule bắt buộc `region ∈ vn_regions` cho mọi tài nguyên loại này.
- Thêm deny-rule residency áp dụng cho **mọi** `storage_types` (DB/bucket) bất
  kể có gắn `data-class: pii` hay không — trước đây quy tắc vùng chỉ áp cho
  tài nguyên PII; acceptance của ticket này yêu cầu "mọi DB/bucket/log", rộng
  hơn phạm vi PII thuần túy.
- Test mới trong `policy/storage_test.rego`: bucket không-PII ngoài VN vẫn bị
  chặn; DB trong VN không bị chặn; log_sink ngoài VN bị chặn, trong VN thì qua.

`conftest verify` (job `iac` trong CI) là release-check chạy các test này.
Vẫn không có `terraform plan` thật (DEF-01 chưa chốt nhà cung cấp) nên chưa có
tài nguyên hạ tầng nào để áp policy lên — quy tắc đã sẵn sàng, sẽ tự động chặn
PR hạ tầng đầu tiên nếu vi phạm.

## 5. Chi phí

Không tạo tài nguyên cloud nào ở ticket này (thuần code + policy). Delta hạ
tầng: **0 USD/tháng**. Chi phí CI: không đổi so với infra v7 (~5 USD/tháng),
vì job `test`/`iac` đã chạy sẵn, chỉ thêm test/policy chạy trong cùng job.

## 6. Nợ mở / việc còn lại

| id | nội dung | owner | hạn |
|---|---|---|---|
| QLKH-013-a | Gắn `scrub_log_record`/`scrub_for_external_sink` vào tầng logging thực khi HTTP layer đầu tiên ra đời | backend (ticket tạo endpoint đầu tiên) | trước endpoint PII đầu tiên |
| QLKH-013-b | Alert rule ở mục 3 mới là khai báo YAML; cần backend giám sát tại VN thật (DEF-03) để triển khai và diễn tập | platform | sau khi DEF-03 chốt |
| QLKH-013-c | Runbook RB-QLKH-013-* mới là bản tóm tắt; viết đầy đủ + diễn tập khi có dịch vụ giám sát thật | platform | cùng QLKH-013-b |
