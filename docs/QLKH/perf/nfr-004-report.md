# Báo cáo hiệu năng NFR-004 — điểm danh hàng loạt p95 < 1s @ 30 phiên đồng thời

- Ticket: TCK-CR-RUNTIME-03 (CR-RUNTIME-NFR-001), phụ thuộc TCK-CR-RUNTIME-01.
- Ngày: 2026-09-06
- Người thực hiện: platform (agent)
- Liên quan: PRD RISK-4 (High/Medium, owner=architect, req_id=[REQ-005, NFR-004]).

## Việc đã làm

1. Viết kịch bản k6 `perf/nfr-004-attendance.js`: mô phỏng N giáo viên
   (mặc định 30, cấu hình qua `VUS`) gọi `POST /v1/classes/{id}/attendance`
   (bulkAttendance) đồng thời, liên tục trong cửa sổ `DURATION` (mặc định
   30 phút), sau khi mỗi VU login thật qua `POST /v1/auth/login` — khớp
   handler thật `qlkh/application/attendance_http.py` và
   `qlkh/application/auth_http.py` (status code, cookie, body request đã đọc
   trực tiếp từ code, không đoán).
2. Viết `perf/README.md`: lệnh chạy đầy đủ, yêu cầu tiền đề (staging đã
   smoke OK theo `runtime.yaml`/TCK-CR-RUNTIME-01, tài khoản giáo viên +
   class_id + học viên thật trên staging, cài k6), và cách đọc ngưỡng.
3. Ngưỡng chặn khai trong script: `bulk_attendance_duration` p(95) < 1000ms,
   `bulk_attendance_fail_rate` < 1% — ánh xạ trực tiếp NFR-004.

## KHÔNG làm được: chưa có số p95 thật đo trên staging

**Finding, không che giấu**: agent này chưa chạy được kịch bản trên staging
thật, vì hai giới hạn năng lực cụ thể, không phải vì bỏ sót:

1. Tool `run` của agent platform trong lượt này chỉ có 4 lệnh cố định
   (`git_diff`, `git_status`, `lint`, `test`) — không có lệnh thực thi tuỳ ý
   hay truy cập mạng để gọi `k6 run` tới một host staging. Không có cách nào
   trong bộ công cụ hiện có để tự thực thi bước 2 của acceptance
   ("Chạy kịch bản trên staging").
2. Worktree hiện tại của agent KHÔNG chứa `infra/staging/wsl/` (đã kiểm bằng
   `list_files` — thư mục rỗng), dù `runtime.yaml` (TCK-CR-RUNTIME-01) và
   nhiều tài liệu trên shared-context (`architecture` ADR-0015, `contract`
   REL-034, `glossary` CR-REL034-COND-01) đều tham chiếu
   `infra/staging/wsl/deploy.sh`/`smoke.sh`. Không có bằng chứng cục bộ để
   xác nhận "staging đã smoke ok" (điều kiện tiên quyết của scope ticket)
   từ trong worktree này.

Vì vậy: **không có số p95 nào được đo, và báo cáo này không bịa số**. Đây là
finding cần ghi rõ theo đúng acceptance #3 của ticket ("nếu không đạt ngưỡng,
ticket ghi rõ finding, không che giấu") — áp dụng tương tự cho trường hợp
"chưa đo được": im lặng coi như đạt là sai, nên ghi rõ ở đây.

## Việc còn lại — ai cần làm gì

- **release-engineer hoặc platform có quyền exec/network thật tới staging**:
  chạy đúng lệnh trong `perf/README.md` (`k6 run ... perf/nfr-004-attendance.js`)
  sau khi xác nhận staging đã smoke OK, dán nguyên văn kết quả p95 thật
  (`bulk_attendance_duration` p95, tỉ lệ lỗi) vào bảng dưới đây, KHÔNG chỉnh
  sửa lệnh hay chọn lọc lần chạy đẹp.
- Nếu p95 ≥ 1s: giữ nguyên finding ở đây, không đóng ticket, đối chiếu với
  mitigation đã ghi ở RISK-4 (phân trang bắt buộc, giới hạn 200 mục/lần gửi)
  để xác định có cần thêm biện pháp hay không.
- Cập nhật `prd/QLKH/risk-register.json` RISK-4 (owner=architect) sau khi có
  số thật — ngoài thẩm quyền namespace của platform, chỉ ghi chú yêu cầu ở
  đây.

## Bảng kết quả (điền bởi người/agent chạy thật trên staging)

| lần chạy | ngày | VUS | duration | p95 bulk_attendance (ms) | fail rate | đạt <1s? | ghi chú |
|---|---|---|---|---|---|---|---|
| _(chưa có)_ | | | | | | | Chưa chạy được — xem mục "KHÔNG làm được" ở trên. |

| version | ngày | thay đổi |
|---|---|---|
| 1 | 2026-09-06 | Khởi tạo: kịch bản k6 + README sẵn sàng chạy; CHƯA có số p95 thật do agent không có exec/network tới staging và thiếu `infra/staging/wsl/` trong worktree — ghi finding rõ ràng, không bịa số. |
