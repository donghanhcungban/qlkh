# RB-STUDENTS-ID-LATENCY — p95 cao trên GET /students/{id}

**Triệu chứng**: alert `students-id-p95-latency-high` fire (p95 > 1.0s trong 10 phút).

## Xác nhận
1. Dashboard panel `duration p95`.
2. Kiểm P3 có thêm điều kiện lọc gây query chậm (thiếu index theo branch_id/quan hệ) không.

## Giảm nhẹ
- Kiểm/EXPLAIN truy vấn liên quan bảng students qua P3; đề xuất index nếu thiếu (qua migration, không sửa tay DB).

## Leo thang
- Không cải thiện sau 30 phút → platform lead.

## Chủ sở hữu
platform-oncall
