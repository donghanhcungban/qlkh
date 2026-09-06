# RB-ERASURE-403-SPIKE — Spike 403 (không có quan hệ chủ thể) trên POST /erasure-requests

**Triệu chứng**: alert `erasure-requests-403-relationship-denied-spike` fire — một tài khoản tạo
>10 request/5 phút bị 403 ErasureNotAuthorized.
**Liên quan**: RISK-3, threat-model v1.34 mục 25 (create_erasure_request kiểm quan hệ chủ thể qua
`repo.get_student_ref` trước khi tạo yêu cầu; ngoài phạm vi trả 403, không lộ tồn tại qua 404).

## Xác nhận
1. Dashboard panel `403 relationship-denied theo account_id`.
2. Xác định account_id và các subject_student_id đã thử — dấu hiệu dò quét ID học viên để kiểm tra
   quan hệ tồn tại hay không (dùng phản hồi 403 làm oracle).
3. Đối chiếu với các alert IDOR khác (students-id, students-consents) từ cùng account_id để xác nhận
   pattern dò quét trên diện rộng hơn một endpoint.

## Giảm nhẹ
- Khóa tạm tài khoản nghi vấn; siết rate-limit riêng.
- Không thay đổi ngữ nghĩa 403 hiện tại (đã đúng thiết kế theo threat-model — không đổi sang 404 vì
  contract mô tả rõ ngữ nghĩa hành động ghi).

## Leo thang
- Xác nhận dò quét chủ đích → incident-management; báo security-engineer để đánh giá mở rộng RISK-3.

## Chủ sở hữu
security-engineer
