# RB-ERASURE-LATENCY — p95 cao trên POST /erasure-requests

**Triệu chứng**: alert `erasure-requests-p95-latency-high` fire (p95 > 1.0s trong 10 phút).

## Xác nhận
1. Dashboard panel `duration p95`.
2. Kiểm bước kiểm quan hệ chủ thể (repo.get_student_ref) có chậm bất thường không.

## Giảm nhẹ
Theo quy trình latency chuẩn (kiểm DB, index, tài nguyên).

## Leo thang
Không cải thiện sau 30 phút → platform lead.

## Chủ sở hữu
platform-oncall
