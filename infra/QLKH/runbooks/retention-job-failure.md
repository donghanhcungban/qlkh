# Runbook: Job retention/xóa (P4) chạy sai hoặc quá hạn `due_at` (SLA 30 ngày)

- Dịch vụ: `qlkh/application/retention_job.py` (`RetentionJob.run_erasure`, `RetentionJob.run_archive`)
- Tham chiếu: threat-model v1.34 mục 25 (QLKH-012, deep-review lần 3, PASS + warn W1/W2), REQ-011, NFR-006/007, RISK-8 (prd risk-register)
- Owner: platform (vận hành job) + backend (logic domain) + security-engineer (tuân thủ ND13)
- Ticket liên quan: TCK-CR-OPS-001-01 (alert `alerts.yaml`), TCK-CR-OPS-001-02 (runbook này)

> Trạng thái phụ thuộc: tại thời điểm viết runbook này, `alerts.yaml` của
> TCK-CR-OPS-001-01 **chưa có trong workspace** (không tìm thấy file khi
> `list_files` toàn repo). Runbook này khai báo TÊN alert và ngưỡng kỳ vọng
> ở mục 1 để TCK-CR-OPS-001-01 trỏ `runbook_url` đúng vào file này
> (`infra/QLKH/runbooks/retention-job-failure.md`) và đặt tên alert khớp.
> Nếu `alerts.yaml` đã tồn tại với tên khác, đối chiếu lại và sửa một trong
> hai phía cho khớp trước khi đóng cả hai ticket — đây là việc phối hợp,
> không tự suy ra được nếu chưa đọc được file kia.

## 1. Phát hiện

Hai lớp cảnh báo độc lập, dựa trên audit event mà `RetentionJob` phát ra
(threat-model mục 25, điểm 3):

| Alert (tên kỳ vọng trong `alerts.yaml`) | Điều kiện / ngưỡng | Mức | Vì sao |
|---|---|---|---|
| `erasure_sla_breach_detected` | audit event `erasure_sla_breach` xuất hiện ≥ 1 lần trong cửa sổ 15 phút (event phát khi `run_at > due_at` ngay trong `run_erasure`, xem dòng phát audit trong code) | **Critical / page ngay** | Đây là bằng chứng ND13 đã bị vi phạm (xóa trễ hạn 30 ngày) đã xảy ra thật, không phải nguy cơ |
| `retention_job_run_failed` | job `run_erasure` hoặc `run_archive` không hoàn tất (exception thoát ra ngoài, hoặc job scheduler báo lỗi/timeout) trong lần chạy theo lịch | **High / page trong giờ hành chính, page ngay nếu > 1 lần chạy lỗi liên tiếp** | Job không chạy được đồng nghĩa các yêu cầu `pending` không được xử lý, nguy cơ tích lũy thành SLA breach |
| `erasure_pending_backlog_high` | số bản ghi `erasure_requests` ở trạng thái `pending` với `due_at` trong vòng ≤ 3 ngày tới vượt ngưỡng (đề xuất ban đầu: > 5, điều chỉnh theo baseline thật khi có dữ liệu) | **Medium / cảnh báo sớm, không cần page** | Cảnh báo sớm trước khi breach xảy ra — mục tiêu là không bao giờ cần dùng đến alert Critical ở trên |

Không alert nào dựa trên nguyên nhân nội bộ (CPU, kết nối DB...) làm alert
chính — đó là chỉ báo bổ trợ dùng ở bước chẩn đoán, không phải điều kiện
page (theo `observability`: alert theo triệu chứng, không theo nguyên nhân).

## 2. Chẩn đoán nhanh (≤ 10 phút)

1. Xác nhận alert thật, không phải nhiễu: xem log job gần nhất
   (`retention_erasure_run` / `retention_archived` audit event) — có chạy
   không, `run_at` gần nhất là khi nào.
2. Đếm số request đang `pending` và số đã overdue (`due_at < now`):
   truy vấn `erasure_requests` theo `status='pending'`.
3. Nếu `retention_job_run_failed`: lấy stack trace/log lỗi lần chạy gần
   nhất. Phân loại nhanh:
   - Lỗi hạ tầng (DB timeout, cold storage không phản hồi, log sink lỗi)
     → khả năng transient, ưu tiên retry job theo mục 3.
   - Lỗi logic/dữ liệu (KeyError, dữ liệu `due_at` sai định dạng...) → KHÔNG
     retry ngay, cần fix code trước (mục 4), vì retry lặp lại sẽ lỗi y hệt.
4. Nếu `erasure_sla_breach_detected`: xác định request nào breach, breach
   bao lâu rồi (`run_at - due_at`), và đã hoàn tất xóa hay chưa — đọc kỹ:
   theo code, request overdue **vẫn được xóa trong cùng lần chạy** (không bị
   bỏ sót, xem threat-model điểm 4/RISK-8), audit `erasure_sla_breach` chỉ
   là cảnh báo vi phạm mốc, không phải dấu hiệu job bỏ qua request đó. Việc
   cần làm là xử lý hậu quả tuân thủ (mục 3.2), không phải "chạy lại cho nó
   xóa".

## 3. Giảm nhẹ trước (khôi phục trước, hiểu sau — theo `incident-management`)

### 3.1 Nếu job không chạy được (`retention_job_run_failed`)

1. **Không** để job đứng yên tới lần lịch kế tiếp nếu đã có request pending
   gần hạn — kích hoạt chạy lại thủ công (manual trigger) ngay khi đã phân
   loại lỗi là transient (bước 2.3).
2. **Cảnh báo rủi ro double-run / idempotency (W1, threat-model mục 25):**
   `erase_subject` trên cả ba Protocol port (`RetentionSource`,
   `LogEraser`, `ColdArchiveEraser`) **chưa được yêu cầu idempotent tường
   minh** ở tầng domain. Nếu lần chạy trước đã xóa thành công một số nhánh
   (ví dụ DB đã xóa) rồi lỗi ở nhánh khác (ví dụ cold storage timeout) thì
   `mark_completed` KHÔNG được gọi (theo code, chỉ gọi sau khi cả ba nhánh
   xong) — request vẫn ở trạng thái `pending` và sẽ được xử lý lại ở lần
   chạy tiếp theo, gọi lại `erase_subject` trên CẢ BA nhánh kể cả nhánh đã
   xóa xong rồi.
   - **Trước khi retry thủ công, kiểm tra bằng tay**: với từng request nghi
     ngờ đã xóa một phần, xác nhận trạng thái thật ở từng sink (DB, log,
     cold archive) — hỏi adapter thật đã hiện thực `erase_subject` là
     idempotent hay chưa (trả 0 nếu bản ghi đã không còn, không lỗi/không
     xóa nhầm dữ liệu khác).
   - Nếu adapter **chưa xác nhận idempotent**: không tự động retry hàng
     loạt. Retry từng request, theo dõi audit `erasure_completed` xuất hiện
     đúng 1 lần cho mỗi request, và kiểm tra không có lỗi mới phát sinh do
     xóa lại cái đã xóa (ví dụ lỗi "not found" bị coi là fail thay vì no-op).
   - Đây là rủi ro double-run thật, không phải giả định — ghi vào ticket
     theo dõi nếu gặp trong thực tế, gắn nhãn liên quan tới W1.
3. Nếu lỗi lặp lại sau 1 lần retry thủ công → dừng retry tự động, chuyển
   sang điều tra sâu (mục 4), đồng thời áp dụng mục 3.2 vì SLA đang chạy.

### 3.2 Xử lý `erasure_sla_breach_detected` để không vi phạm ND13 kéo dài

- **Thông báo**: platform on-call thông báo ngay (≤ 15 phút kể từ alert)
  cho security-engineer (owner tuân thủ ND13, xem prd risk-register RISK-8)
  và delivery-lead của dự án QLKH, qua kênh incident chính thức.
- **Trong ≤ 1 giờ kể từ alert**: security-engineer xác nhận số request
  breach, thời gian trễ mỗi request, và liệu request đó đã được xóa xong
  trong lần chạy vừa rồi hay vẫn còn kẹt.
- **Nếu vẫn còn pending sau breach**: đây là ưu tiên cao nhất của job —
  đảm bảo request được xử lý trong lần chạy gần nhất có thể (retry thủ
  công theo mục 3.1 nếu job đang lỗi), KHÔNG chờ tới lịch chạy định kỳ
  tiếp theo.
- **Trong vòng 24 giờ**: security-engineer chuẩn bị hồ sơ ghi nhận sự cố
  (thời điểm request, `due_at`, thời điểm xóa thực tế, lý do trễ) — đây là
  bằng chứng cần có sẵn nếu bị thanh tra hỏi, không che giấu vi phạm mà
  chứng minh đã phát hiện và khắc phục nhanh.
- Không dùng breach của một request làm lý do trì hoãn các request khác
  đang trong hạn — mỗi request xử lý theo `due_at` riêng của nó.

## 4. Điều tra sâu (chỉ sau khi đã giảm nhẹ)

1. Xác định nguyên nhân gốc lỗi job (hạ tầng: DB/cold storage/log sink
   không khả dụng, hay logic: dữ liệu `due_at`/`subject_student_id` sai
   dạng — xem W2, subject_student_id mới chỉ kiểm rỗng, chưa kiểm định
   dạng UUID ở tầng service).
2. Nếu nguyên nhân là W1 (double-run/không idempotent) đã thực sự xảy ra:
   mở ticket cho backend để làm `erase_subject` idempotent tường minh ở
   adapter thật (Postgres/cold storage/log sink) — đây là nợ đã ghi nhận
   trong threat-model, không phải phát hiện mới, nhưng lần xảy ra thật cần
   ticket riêng để ưu tiên hoá.
3. Nếu nguyên nhân là backlog tăng dần (nhiều `erasure_pending_backlog_high`
   liên tiếp trước khi breach): xem lại tần suất chạy job / tài nguyên job
   có đủ không, không chỉ coi là sự cố đơn lẻ.
4. Đối chiếu tổng số bản ghi đã xóa (`erasure_completed.counts`) khớp với
   kỳ vọng nghiệp vụ (không xóa thiếu, không xóa nhầm chủ thể khác).

## 5. Đóng sự cố

- Xác nhận: không còn request nào `pending` quá hạn `due_at`.
- Xác nhận: mọi audit event liên quan (`erasure_sla_breach`,
  `erasure_completed`, `retention_erasure_run`) đã ghi đầy đủ cho các
  request bị ảnh hưởng.
- Nếu có breach xảy ra: đóng kèm hồ sơ tuân thủ (mục 3.2) đã hoàn tất,
  security-engineer xác nhận.
- Postmortem (SEV theo mức độ breach — có breach thật luôn coi như tối
  thiểu SEV2 vì liên quan ND13) trong 48h theo `incident-management`; mọi
  action item (ví dụ: làm idempotent adapter, validate UUID, điều chỉnh
  ngưỡng backlog) có owner và hạn, mở ticket thật.
- Cập nhật ngưỡng `erasure_pending_backlog_high` nếu ngưỡng ban đầu gây
  nhiễu hoặc phát hiện muộn — ngưỡng trong mục 1 là đề xuất khởi điểm, cần
  hiệu chỉnh theo dữ liệu thật của TCK-CR-OPS-001-01.

## Rủi ro đã biết, chưa đóng (tham chiếu, không phải việc của runbook này)

| id | nội dung | owner |
|---|---|---|
| W1 (threat-model mục 25) | `erase_subject` chưa idempotent tường minh ở domain/adapter — xem mục 3.1 | backend |
| W2 (threat-model mục 25) | `subject_student_id` chưa validate định dạng UUID ở service | backend |
| — | `alerts.yaml` (TCK-CR-OPS-001-01) cần đối chiếu tên alert và `runbook_url` khớp file này | platform (điều phối với người làm TCK-CR-OPS-001-01) |
