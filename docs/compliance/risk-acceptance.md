# Chấp nhận rủi ro — RISK-6 (DPIA, môi trường thử nghiệm QLKH)

Trạng thái: **accepted** (có điều kiện), phạm vi giới hạn. Tài liệu này là bản ghi tuân
thủ đối chiếu cho quyết định chấp nhận rủi ro đã có trong
`prd/QLKH/risk-register.json` v21 (`RISK-6.risk_acceptance`) và điều kiện gate tương ứng
trong `architecture/QLKH/c4.md` v2 (mục "Điều kiện chặn Gate 3"). Tài liệu này **không**
tự tạo quyết định mới — nó tổng hợp lại quyết định đã do `human:owner` ký, để các vai trò
khác (security-engineer, release-engineer, QA) có một điểm tham chiếu duy nhất bằng .md.

## Rủi ro được chấp nhận

- **ID rủi ro**: RISK-6 (`prd/QLKH/risk-register.json` v21)
- **Mô tả rủi ro**: DPIA (Đánh giá tác động bảo vệ dữ liệu cá nhân) cho dữ liệu trẻ em
  chưa hoàn thành; dự án QLKH xử lý dữ liệu học viên là trẻ em, thuộc phạm vi Nghị định
  13/2023/NĐ-CP.
- **Yêu cầu/NFR liên quan**: NFR-006, REQ-010.

## Người chấp nhận rủi ro

- **Người ký**: `human:owner`
- **Ngày**: 2026-09-06
- **Vai trò**: chủ dự án — thẩm quyền chấp nhận rủi ro pháp lý còn lại của quyết định này.

## Phạm vi chấp nhận

Chấp nhận rủi ro này **chỉ áp dụng cho môi trường THỬ NGHIỆM** của QLKH, cụ thể:

- Không phát hành cho học viên/phụ huynh thật (không có người dùng cuối thật).
- Không có dữ liệu cá nhân thật của trẻ em trong môi trường thử nghiệm/staging thử nghiệm.
- **Không áp dụng** cho bất kỳ hình thức phát hành production thật nào — dù một phần hay
  toàn bộ, dù có hay không có thông báo trước.

## Điều kiện mở lại (bắt buộc trước khi phát hành thật)

1. DPIA phải **hoàn thành** và được **ký** trước khi phát hành cho người dùng thật
   (production thật).
2. Tại thời điểm chuyển sang phát hành thật, RISK-6 **phải được mở lại**
   (`status` quay về `open` trong `prd/QLKH/risk-register.json`) — không được coi RISK-6
   là đã đóng vĩnh viễn bởi lần `accepted` này.
3. Cho tới khi (1) và (2) hoàn tất, không có ticket/roadmap phát hành thật nào được phép
   tiến hành (xem RISK-F, cùng risk-register, ghi nhận rủi ro dư nếu bỏ qua bước rà soát
   này).

## Liên kết bắt buộc (nguồn sự thật)

- `prd/QLKH/risk-register.json` **v21**, mục `risks[].id == "RISK-6"`, trường
  `risk_acceptance` (accepted_by, date, scope, condition, rationale, cross_reference) —
  đây là bản ghi gốc của quyết định chấp nhận rủi ro.
- `architecture/QLKH/c4.md` **v2**, mục **"Điều kiện chặn Gate 3"** — điều kiện gate cho
  RC phạm vi thử nghiệm đã được điều chỉnh tương ứng với chấp nhận rủi ro này.
- `schema/QLKH/core-schema.md`, mục "Việc còn nợ", dòng **SD-14** — cập nhật để không còn
  ghi "DPIA security-engineer ký" như điều kiện chặn tuyệt đối cho mọi môi trường.
- `security/QLKH/threat-model.md` (chủ sở hữu: security-engineer) — cần ghi nhận mục mới
  xác nhận release-check cho RC phạm vi thử nghiệm không còn `BLOCK` vì thiếu
  DPIA/DAST/SBOM, với điều kiện: 3 phiếu review pass + QA hồi quy staging pass. Tài liệu
  này không thay được xác nhận đó — cho tới khi threat-model tự cập nhật, điều kiện gốc
  "DPIA hoàn thành" của threat-model vẫn có hiệu lực trong namespace của threat-model.

## Ghi chú thẩm quyền

`gate_release` do người ký là thẩm quyền cuối cùng cho production; threat-model là đầu
vào tư vấn, không phải quyền phủ quyết sau khi đã ký (xem
`prd/QLKH/risk-register.json` v21, mục `pending_out_of_namespace`). Tài liệu này không
thay đổi nguyên tắc đó — nó chỉ tổng hợp bằng chứng chấp nhận rủi ro để gate 3 tham chiếu.

## Nợ kỹ thuật liên quan (đối chiếu, không thuộc phạm vi tài liệu này)

`prd/QLKH/risk-register.json` v21, mục `technical_debt_accepted`, cùng điều kiện phạm vi
thử nghiệm / bắt buộc hoàn thành trước phát hành thật, cùng người ký `human:owner`,
2026-09-06:

- **SD-08**: DAST/license/SBOM không chạy được cho bundle release.
- **SD-25**: thiếu infra PostgreSQL service trong CI cho test tích hợp schema
  (xem `schema/QLKH/core-schema.md`, mục "Việc còn nợ").
