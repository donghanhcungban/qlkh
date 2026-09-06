# RB-STUDENTS-ID-5XX — Tỉ lệ 5xx cao trên GET /students/{id}

**Triệu chứng**: alert `students-id-5xx-rate-high` fire (>2% lỗi 5xx trong 5 phút).

## Xác nhận
1. Dashboard `pii-endpoints.md#3-get-studentsid`, panel `errors`.
2. Kiểm P3 (lớp truy vấn bắt buộc ngữ cảnh) có lỗi khi áp bộ lọc branch_id/quan hệ không —
   lỗi ở đây có thể là bug trong kiểm uỷ quyền, ưu tiên cao (ADR-004).

## Giảm nhẹ
- Nếu nghi lỗi P3 làm sai uỷ quyền (không chỉ 5xx mà có khả năng trả sai dữ liệu): coi như sự cố bảo mật,
  cân nhắc tắt tính năng qua feature flag và escalate ngay, không chỉ xử lý như lỗi hiệu năng.
- Nếu do DB timeout thông thường: theo quy trình 5xx chuẩn (xem RB-AUTH-LOGIN-5XX bước DB).

## Leo thang
- Bất kỳ nghi ngờ rò rỉ PII chéo học viên/cơ sở → incident-management ngay, không chờ 15 phút.

## Chủ sở hữu
platform-oncall (leo thang security-engineer nếu nghi uỷ quyền sai)
