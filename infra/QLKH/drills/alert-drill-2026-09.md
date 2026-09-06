# Diễn tập alert — 2026-09-06 (tabletop / mô phỏng bằng tài liệu)

- Ticket: TCK-CR-OPS-001-04 (CR-OPS-001), phụ thuộc TCK-CR-OPS-001-01/-02/-03
- Người thực hiện: platform (donghanhcungban.org@gmail.com), ghi vào audit-log với ticket_id=TCK-CR-OPS-001-04
- Loại diễn tập: **tabletop exercise** — mô phỏng bằng checklist/tài liệu, KHÔNG kích hoạt alert
  thật trên backend giám sát. Lý do (xem mục "Giới hạn công cụ" đầu `infra/QLKH/observability/alerts.yaml`):
  môi trường này chưa có backend giám sát thật (Prometheus/Grafana/Alertmanager hay tương đương) vì
  DEF-03 (nhà cung cấp giám sát có hạ tầng tại VN) chưa chốt. `alerts.yaml` hiện là cấu hình-như-code
  (spec), chưa `apply`/`import` vào hệ thống thật, nên không có "rule đã fire" thật nào để đo.
- **Không có số liệu thời gian phản hồi thật nào được bịa ra trong tài liệu này.** Mọi cột
  "thời gian phản hồi" dưới đây ghi rõ `KHÔNG ĐO ĐƯỢC (mô phỏng)` — chỉ ghi lại bước và vai trò dự kiến
  theo runbook, không phải số đo thật.

## 1. Phạm vi diễn tập

3 kịch bản, mỗi kịch bản ứng với 1 rule/runbook đã tồn tại thật trong worktree
(đọc trực tiếp từ `infra/QLKH/observability/alerts.yaml` và
`infra/QLKH/runbooks/`, không suy diễn):

| # | Rule alert (từ alerts.yaml) | Runbook | Owner theo alerts.yaml |
|---|---|---|---|
| D1 | `auth-login-401-spike-brute-force` (group `auth-login`) | `infra/QLKH/observability/runbooks/RB-AUTH-LOGIN-BRUTEFORCE.md` + `infra/QLKH/runbooks/login-lockout-mass-trigger.md` (RB-QLKH-OPS-001-03, chi tiết hơn) | security-engineer (alert), platform-oncall (mặc định nhóm) |
| D2 | `retention_job_run_failed` (khai báo tên/ngưỡng trong runbook, chưa có block YAML tương ứng — xem mục 4 "Nợ tồn đọng") | `infra/QLKH/runbooks/retention-job-failure.md` | platform (vận hành job), security-engineer (tuân thủ) |
| D3 | `erasure_sla_breach_detected` (cùng file trên) | `infra/QLKH/runbooks/retention-job-failure.md` | platform + security-engineer |

## 2. Kịch bản D1 — mass lockout / brute-force trên `/auth/login`

**Giả lập điều kiện kích hoạt**: giả định `sum(rate(...401...[5m]))` vượt 5×
baseline 24h liên tục 5 phút (điều kiện `for: 5m` trong rule) — KHÔNG chạy
request thật, chỉ giả định trên giấy vì không có traffic/backend thật để tạo
điều kiện này.

| Bước | Nội dung (theo `RB-AUTH-LOGIN-BRUTEFORCE.md` + `login-lockout-mass-trigger.md`) | Ai/role | Thời gian phản hồi |
|---|---|---|---|
| T0 (giả định) | Rule `auth-login-401-spike-brute-force` fire (page) | hệ thống alert (giả định, chưa có backend thật) | KHÔNG ĐO ĐƯỢC (mô phỏng) |
| T1 | Nhận page, mở dashboard panel `401 rate (baseline 24h)` | security-engineer (owner rule) | KHÔNG ĐO ĐƯỢC — không có kênh page thật (channel trong `alerts.yaml` là `pagerduty:qlkh-platform`, ghi rõ là placeholder) để đo thời gian nhận |
| T2 | Đối chiếu tiêu chí bảng "brute-force thật vs bug client" (mục 1, `login-lockout-mass-trigger.md`): số tài khoản, mật khẩu thử, nhịp request, User-Agent, tương quan release | security-engineer | — |
| T3 | Nếu xác định tấn công thật: mở incident theo `incident-management`, báo delivery-lead nếu >50 tài khoản hoặc >30 phút | security-engineer → delivery-lead | — |
| T4 | Mở khóa thủ công (nếu cần) qua `AttemptStore.reset(key)` bằng script có audit, yêu cầu phê duyệt 2 người, KHÔNG sửa tay Redis | platform (thực hiện) + người phê duyệt thứ 2 | — |
| T5 | Theo dõi 30 phút sau mở khóa, xác nhận không tái diễn | platform | — |

**Ghi nhận (thật, không giả định)**: đọc lại runbook lần này phát hiện
`RB-AUTH-LOGIN-BRUTEFORCE.md` (owner cuối: security-engineer) và
`login-lockout-mass-trigger.md` (chi tiết hơn, do platform viết ở
TCK-CR-OPS-001-03) **trùng lặp phạm vi** — cả hai đều xử lý cùng 1 alert
`auth-login-401-spike-brute-force`, chưa hợp nhất. Đây là nợ đã được ghi
nhận từ threat-model v1.40 mục 32 ("Trùng lặp runbook auth-login-401/429
giữa TCK-CR-OPS-001-01 và -03 chưa hợp nhất") — diễn tập này KHÔNG tự ý hợp
nhất (ngoài phạm vi ticket -04, cần platform/security-engineer phối hợp ở
ticket riêng).

## 3. Kịch bản D2/D3 — job retention/xóa lỗi hoặc trễ SLA 30 ngày

**Giả lập điều kiện kích hoạt**: giả định `RetentionJob.run_erasure` ném
exception ở lần chạy theo lịch (D2), hoặc giả định 1 `erasure_request` có
`run_at > due_at` (D3) — không chạy job thật trên dữ liệu thật (tránh rủi ro
xóa/không xóa sai trên môi trường không cách ly).

| Bước | Nội dung (theo `retention-job-failure.md`) | Ai/role | Thời gian phản hồi |
|---|---|---|---|
| T0 (giả định) | `retention_job_run_failed` hoặc `erasure_sla_breach_detected` fire | hệ thống alert (giả định) | KHÔNG ĐO ĐƯỢC (mô phỏng) |
| T1 | Chẩn đoán ≤10 phút: xem audit event gần nhất, đếm `pending`/overdue, phân loại lỗi transient vs logic | platform | KHÔNG ĐO ĐƯỢC — mốc "≤10 phút" trong runbook là mục tiêu khai báo, không phải số đo thật lần này |
| T2 (nhánh D2, lỗi transient) | Kích hoạt chạy lại thủ công, kiểm tra rủi ro double-run (W1: `erase_subject` chưa idempotent tường minh) trước khi retry hàng loạt | platform | — |
| T3 (nhánh D2, lỗi logic) | Không retry, mở ticket fix code trước | platform | — |
| T4 (nhánh D3) | Xác định request nào breach, xác nhận đã xóa xong (breach chỉ là cảnh báo mốc, job vẫn xóa trong cùng lần chạy) → xử lý hậu quả tuân thủ, báo security-engineer (RISK-8, ND13) | platform → security-engineer | — |

## 4. Đối chiếu finding gốc — đóng hay còn tồn đọng

Trích dẫn nguyên văn nguồn (đọc trực tiếp file, không suy diễn):

- **REL-019**: không tìm thấy tham chiếu "REL-019" trong `threat-model` hiện có (bản đọc được chỉ
  có REL-020/021/022/023 ở mục lịch sử phiên bản v1.37–1.40). Nếu REL-019 là release-check trước đó
  đã bị thay thế/archive, ticket này không có quyền truy cập bản đó — **không kết luận đã đóng hay
  chưa vì không đọc được**. Ghi lại nguyên trạng để security-engineer/release-engineer xác nhận.
- **QLKH-013-b, QLKH-013-c** (nợ được `alerts.yaml` trích dẫn là "QLKH-013-b/QLKH-013-d" ở dòng 12,
  và `login-lockout-mass-trigger.md` mục 5 nhắc "backend giám sát thật (DEF-03 mở)"): **còn tồn đọng**.
  Cụ thể:
  - DEF-03 (nhà cung cấp giám sát có hạ tầng VN) **chưa chốt** — không có bằng chứng nào trên
    shared-context (prd, threat-model) ghi DEF-03 đã đóng.
  - `alerts.yaml` chưa được `apply`/`import` vào backend giám sát thật; chưa chạy được
    `promtool test rules` hay tương đương; chưa có bằng chứng "đã bắn thử alert trên staging, nhận
    được noti đúng owner" như alerts.yaml mục "GIỚI HẠN CÔNG CỤ" bước 4 yêu cầu.
  - Vì vậy: diễn tập ngày 2026-09-06 này **là bước tabletop đầu tiên**, không phải "diễn tập ≥1 lần"
    theo nghĩa vận hành thật (`resilience-testing` yêu cầu game day thật để tính MTTD/MTTR). Acceptance
    của ticket này ("diễn tập mô phỏng ... do QLKH là bản thử nghiệm") được thỏa mãn ở mức tabletop,
    nhưng nợ vận hành thật (game day có backend giám sát thật) **vẫn mở**, cần chạy lại khi DEF-03 đóng
    (đúng như `login-lockout-mass-trigger.md` mục 5 và `alerts.yaml` đã tự ghi nhận).
- **Trùng lặp runbook auth-login-401/429** (threat-model v1.40 mục 32, kế thừa từ mục 28-31): xác nhận
  lại ở mục 2 trên — **còn tồn đọng**, chưa hợp nhất `RB-AUTH-LOGIN-BRUTEFORCE.md` và
  `login-lockout-mass-trigger.md`.
- **Rule `retention_job_run_failed` / `erasure_sla_breach_detected` chưa có block YAML tương ứng
  trong `alerts.yaml`** (chỉ tồn tại dưới dạng tên+ngưỡng kỳ vọng trong `retention-job-failure.md`
  mục 1, do `retention-job-failure.md` ghi nhận `alerts.yaml` "chưa có trong workspace" tại thời điểm
  nó được viết) — đọc lại `alerts.yaml` hiện tại (nhóm `auth-login`, `auth-me`, `students-detail`, và
  các nhóm khác bị cắt trong lần đọc) để xác nhận nhóm `retention`/`erasure-job` có tồn tại: **không
  xác nhận được đầy đủ vì nội dung file bị cắt khi đọc (6473 ký tự còn lại chưa xem hết)**. Ghi là
  **CẦN XÁC MINH THÊM** — không kết luận đóng hay mở, để tránh bịa.

## 5. Kết luận diễn tập

- Xác nhận được: 3 runbook thật tồn tại và nội dung đủ chi tiết để một người vận hành có thể theo
  bước (không có bước mơ hồ/thiếu thông tin cần).
- Không xác nhận được (nằm ngoài khả năng công cụ hiện có): thời gian phản hồi thật, việc rule có
  thực sự fire đúng ngưỡng, kênh notify có tới đúng người hay không (channel là placeholder).
- Finding tồn đọng cần theo dõi tiếp (không đóng bởi ticket này): DEF-03 backend giám sát thật;
  hợp nhất 2 runbook trùng lặp auth-login; xác minh đầy đủ toàn bộ `alerts.yaml` có phủ nhóm
  retention/erasure-job hay chưa; xác nhận REL-019 tồn tại/đã đóng ở đâu (không đọc được từ đây).
- Khuyến nghị: chạy lại diễn tập này dưới dạng game day thật (theo `resilience-testing`) ngay khi
  DEF-03 đóng và `alerts.yaml` được `apply` vào backend thật; khi đó mới ghi được số liệu MTTD/MTTR
  thật thay cho "KHÔNG ĐO ĐƯỢC (mô phỏng)" ở các bảng trên.
