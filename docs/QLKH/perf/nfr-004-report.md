# Báo cáo hiệu năng NFR-004 — điểm danh hàng loạt p95 < 1s @ 30 phiên đồng thời

- Ticket: TCK-CR-RUNTIME-03 (CR-RUNTIME-NFR-001), phụ thuộc TCK-CR-RUNTIME-01.
- Ngày: 2026-09-10 (retry 1; lần đầu 2026-09-06 — xem bảng version cuối file)
- Người thực hiện: platform (agent)
- Liên quan: PRD RISK-4 (High/Medium, owner=architect, req_id=[REQ-005, NFR-004]).

## Việc đã làm (lần đầu, 2026-09-06)

1. Viết kịch bản k6 `perf/nfr-004-attendance.js`: mô phỏng N giáo viên
   (mặc định 30, cấu hình qua `VUS`) gọi `POST /v1/classes/{id}/attendance`
   (bulkAttendance) đồng thời, liên tục trong cửa sổ `DURATION` (mặc định
   30 phút), sau khi mỗi VU login thật qua `POST /v1/auth/login` — khớp
   handler thật `qlkh/application/attendance_http.py` và
   `qlkh/application/auth_http.py` (status code, cookie).
2. Viết `perf/README.md`: lệnh chạy đầy đủ, yêu cầu tiền đề (staging đã
   smoke OK theo `runtime.yaml`/TCK-CR-RUNTIME-01, tài khoản giáo viên +
   class_id + học viên thật trên staging, cài k6), và cách đọc ngưỡng.
3. Ngưỡng chặn khai trong script: `bulk_attendance_duration` p(95) < 1000ms,
   `bulk_attendance_fail_rate` < 1% — ánh xạ trực tiếp NFR-004.

## Sửa lỗi phát hiện ở lượt này (retry 1, 2026-09-10)

**Phát hiện, không che giấu**: khi đối chiếu lại kịch bản với code thật để
chuẩn bị chạy, phát hiện bản `perf/nfr-004-attendance.js` cũ gửi field
`subject_student_id` trong mỗi entry của `bulkAttendance`, trong khi API
thật (`qlkh/application/attendance_service.py` dòng 112:
`raw.get("student_id")`) và contract (`AttendanceBulk.entries[].student_id`
trong `api/QLKH/openapi.yaml` v1.4.0) đều yêu cầu field tên `student_id`.

Hệ quả nếu chạy bản cũ trên staging thật: **100% request `bulkAttendance`
sẽ nhận `422 InvalidAttendanceInput` ("student_id không được rỗng")** —
`bulk_attendance_fail_rate` sẽ luôn = 1.0 và `bulk_attendance_duration` sẽ
chỉ đo độ trễ của một validation lỗi sớm, không đo được đường ghi dữ liệu
thật. Số p95 thu được (nếu có ai chạy bản cũ) sẽ KHÔNG phản ánh NFR-004
thật dù có thể trông "nhanh" (lỗi 422 trả sớm, ít việc).

Đã sửa: đổi field thành `student_id` trong hàm `randomEntries()`. Không sửa
gì khác trong script (threshold, luồng login, cấu trúc scenario giữ nguyên).

## KHÔNG làm được (vẫn còn ở retry này): chưa có số p95 thật đo trên staging

**Finding, không che giấu**: agent này vẫn chưa chạy được kịch bản trên
staging thật ở lượt retry này, vì cùng giới hạn năng lực công cụ đã ghi ở
lần đầu — đã kiểm tra lại, KHÔNG có gì thay đổi:

1. Tool `run` của agent platform trong lượt này chỉ có 4 lệnh cố định
   (`git_diff`, `git_status`, `lint`, `test`) — không có lệnh thực thi tuỳ ý
   hay truy cập mạng để gọi `k6 run` tới một host staging thật, và cũng
   không có cách gọi `infra/staging/wsl/deploy.sh`/`smoke.sh` (shell script
   tuỳ ý) qua bộ công cụ này. Không có cách nào trong bộ công cụ hiện có để
   tự thực thi bước 2 của acceptance ("Chạy kịch bản trên staging").
2. Khác với lần đầu: worktree lần này **đã có** `infra/staging/wsl/`
   (deploy.sh, smoke.sh, rollback.sh, README.md) và `runtime.yaml` ở gốc
   repo (TCK-CR-RUNTIME-01 đã hiện thực) — nghĩa là khai báo runtime đã sẵn
   sàng để orchestrator/release-engineer tự chạy. Nhưng bản thân agent
   `builder` (stack platform) trong worktree cô lập này vẫn không có quyền
   thực thi mạng/tiến trình ngoài 4 lệnh cố định nói trên, nên vẫn không thể
   tự xác nhận "staging đã smoke OK" bằng một lệnh thật, và càng không thể
   tự gọi `k6 run` tới một host staging (dù là localhost hay WSL) từ trong
   sandbox này.

Vì vậy: **vẫn không có số p95 nào được đo, và báo cáo này không bịa số**.
Đây là finding cần ghi rõ theo đúng acceptance #3 của ticket ("nếu không đạt
ngưỡng, ticket ghi rõ finding, không che giấu") — áp dụng tương tự cho
trường hợp "chưa đo được": im lặng coi như đạt là sai, nên ghi rõ ở đây.

Cải thiện thật của lượt này: kịch bản k6 giờ **đúng với API thật** (trước đó
dù có ai chạy được cũng sẽ ra số vô nghĩa vì lỗi field). Đây là điều kiện
cần để bước "chạy thật" (do người/agent có quyền exec+network làm) tạo ra
bằng chứng có giá trị.

## Việc còn lại — ai cần làm gì

- **release-engineer hoặc platform có quyền exec/network thật tới staging**:
  1. Xác nhận staging đã smoke OK (`infra/staging/wsl/smoke.sh` hoặc
     `tools/run_smoke.sh` theo `runtime.yaml`).
  2. Chạy đúng lệnh trong `perf/README.md`
     (`k6 run ... perf/nfr-004-attendance.js`, VUS=30), dán nguyên văn kết
     quả p95 thật (`bulk_attendance_duration` p95, tỉ lệ lỗi) vào bảng dưới
     đây, KHÔNG chỉnh sửa lệnh hay chọn lọc lần chạy đẹp.
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
| 2 | 2026-09-10 | Retry 1: phát hiện và sửa bug field `subject_student_id`→`student_id` trong `perf/nfr-004-attendance.js` (bản cũ sẽ luôn 422 trên staging thật, số liệu vô nghĩa nếu ai đó chạy). Xác nhận `infra/staging/wsl/` và `runtime.yaml` nay đã có trong worktree (TCK-CR-RUNTIME-01 xong) nhưng agent vẫn không có exec/network để tự chạy k6 thật — finding "chưa có số p95 thật" vẫn còn, ghi rõ không che giấu. |
| 1 | 2026-09-06 | Khởi tạo: kịch bản k6 + README sẵn sàng chạy; CHƯA có số p95 thật do agent không có exec/network tới staging và thiếu `infra/staging/wsl/` trong worktree — ghi finding rõ ràng, không bịa số. |
