# RB-STUDENTS-CONSENTS-5XX — Tỉ lệ 5xx cao trên GET /students/{id}/consents

**Triệu chứng**: alert `students-consents-5xx-rate-high` fire (>2% lỗi 5xx trong 5 phút).

## Xác nhận
Tương tự RB-STUDENTS-ID-5XX — endpoint cùng nhóm uỷ quyền theo quan hệ chủ thể (ADR-004), dữ liệu
consent liên quan tuân thủ ND13 (RISK-9).

## Giảm nhẹ
Như RB-STUDENTS-ID-5XX. Ưu tiên xác nhận không có rò rỉ consent chéo học viên trước khi đóng alert.

## Leo thang
Nghi ngờ rò rỉ PII/consent chéo → incident-management ngay.

## Chủ sở hữu
platform-oncall (leo thang security-engineer nếu nghi uỷ quyền sai)
