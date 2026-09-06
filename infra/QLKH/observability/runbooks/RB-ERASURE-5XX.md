# RB-ERASURE-5XX — Tỉ lệ 5xx cao trên POST /erasure-requests

**Triệu chứng**: alert `erasure-requests-5xx-rate-high` fire (>2% lỗi 5xx trong 5 phút).
**Ảnh hưởng**: có thể chặn tạo yêu cầu xóa, đe dọa nghĩa vụ xóa ≤ 30 ngày (RISK-8, NFR-007).

## Xác nhận
1. Dashboard `pii-endpoints.md#5-post-erasure-requests`, panel `errors`.
2. Kiểm audit log `erasure_requested` có ghi được không trước khi lỗi xảy ra (xem threat-model mục 25).
3. Phân biệt lỗi tạo request (endpoint) với lỗi job xóa nền (`retention_job.py`, ngoài scope alert này).

## Giảm nhẹ
- Nếu do DB: theo quy trình 5xx chuẩn.
- Nếu là lỗi có thể làm mất yêu cầu xóa (không phải chỉ trả lỗi cho client mà request bị mất): escalate
  ngay là vấn đề tuân thủ, không chỉ vận hành — do_at tính từ requested_at nên request bị mất có thể
  gây trễ hạn không thể chứng minh đã cố gắng.

## Leo thang
- Nghi mất yêu cầu xóa → mở incident, báo compliance/security-engineer (RISK-8).

## Chủ sở hữu
platform-oncall
