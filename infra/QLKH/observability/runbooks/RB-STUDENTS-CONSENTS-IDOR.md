# RB-STUDENTS-CONSENTS-IDOR — Dò quét IDOR nghi ngờ trên GET /students/{id}/consents

**Triệu chứng**: alert `students-consents-403-404-idor-scan` fire.
**Liên quan**: RISK-3 + RISK-9 (consent là dữ liệu tuân thủ ND13), ADR-004.

## Xác nhận
Như RB-STUDENTS-ID-IDOR, áp dụng cho bảng consents. Đặc biệt chú ý: lộ trạng thái consent qua dò
quét cũng là vi phạm riêng tư ngay cả khi P3 chặn đúng (chính hành vi dò quét đã là dấu hiệu tấn công).

## Giảm nhẹ
Như RB-STUDENTS-ID-IDOR.

## Leo thang
Như RB-STUDENTS-ID-IDOR; báo thêm cho chủ sở hữu compliance (DPIA) nếu có dấu hiệu consent bị lộ.

## Chủ sở hữu
security-engineer
