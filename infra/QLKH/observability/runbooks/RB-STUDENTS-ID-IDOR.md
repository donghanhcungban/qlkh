# RB-STUDENTS-ID-IDOR — Dò quét IDOR nghi ngờ trên GET /students/{id}

**Triệu chứng**: alert `students-id-403-404-idor-scan` fire — một tài khoản tạo >20 request/5 phút
bị 403/404 trên /students/{id}.
**Liên quan**: RISK-3 (Critical, threat-model), ADR-004 uỷ quyền tầng dữ liệu.

## Xác nhận
1. Dashboard `pii-endpoints.md#3-get-studentsid`, panel `403+404 theo account_id`.
2. Xác định account_id cụ thể đứng sau spike (từ log/audit, không log PII thô).
3. Kiểm chuỗi id được thử có tuần tự/tăng dần không (dấu hiệu duyệt vét ID).
4. Xác nhận P3 đang chặn đúng (403/404 là hành vi ĐÚNG — vấn đề là TẦN SUẤT bất thường, không phải
   việc chặn có lỗi).

## Giảm nhẹ
- Khóa tạm tài khoản nghi vấn hoặc siết rate-limit riêng cho tài khoản đó.
- Không tự ý mở rộng quyền hay tắt kiểm uỷ quyền để "hết alert".

## Leo thang
- Xác nhận là dò quét chủ đích → mở incident theo `incident-management`, SEV theo phạm vi dữ liệu có thể đã bị thử;
  báo cho security-engineer để đánh giá threat-model có cần cập nhật RISK-3 không.

## Chủ sở hữu
security-engineer
