
# SLO tối thiểu — /auth/login và /classes/{id}/attendance (QLKH, CR-OPS-001)

- Ticket: TCK-CR-OPS-001-05, requirement: CR-OPS-001
- Nguồn: RISK-4 (prd/risk-register.json), NFR-004 (architecture c4.md, fitness function #4),
  ADR-002/NFR-002 (auth, `qlkh/domain/auth.py`), infra/QLKH/observability-logging.md (alert
  `attendance-p95-latency` đã khai báo trước đó), threat-model v1.34.
- **Trạng thái công cụ**: đây là ĐỊNH NGHĨA dạng tài liệu/cấu hình (YAML khai báo bên dưới).
  Chưa có dashboard/backend giám sát thật đang chạy trong môi trường này (DEF-03 chưa chốt,
  xem RISK-7 và `infra/QLKH/observability-logging.md` mục 3). Số liệu p95/5xx dưới đây là
  **ngưỡng để đối chiếu** khi release-engineer/platform triển khai backend giám sát thật —
  không phải phép đo đang chạy. `test_attendance_load.py` (`_P95_BUDGET_SECONDS = 0.2s`) là
  ngân sách nội bộ tầng domain-only trong RAM, KHÔNG phải số NFR-004 dưới đây — hai tầng khác
  nhau, không nhầm lẫn (xem docstring test đó).

## 1. GET/POST /classes/{id}/attendance

Bối cảnh: RISK-4 — nghẽn khung giờ 17h30–18h00, 60 giáo viên điểm danh đồng thời (NFR-004).

| Chỉ số | Ngưỡng | Cửa sổ | Nguồn |
|---|---|---|---|
| p95 latency | **< 1.0 s** ở kịch bản ≤ 60 phiên đồng thời | tức thời (rolling 5m để alert), báo cáo theo 30 ngày rolling | Tái dùng đúng số đã khai báo ở `infra/QLKH/observability-logging.md` alert `attendance-p95-latency` (`... > 1.0`) và ngưỡng "vượt 1,0 s" trong `early_warning` của RISK-4 (prd/risk-register.json). Không phải số mới. |
| Tỉ lệ lỗi 5xx | **≤ 0.5%** request trong cửa sổ 30 ngày rolling (error budget = 0.5%) | 30 ngày rolling | Endpoint ghi dữ liệu điểm danh (ghi, không phải đọc thuần) đúng lúc cao điểm nhất trong ngày — ngưỡng chặt hơn baseline chung của hệ thống vì RISK-4 xếp severity High/likelihood Medium và mất dữ liệu điểm danh không phục hồi được dễ dàng. |
| Burn-rate alert (tái dùng alert đã có, lọc theo route) | nhanh: 5xx > 5% trong 5m, 10m liên tục → page; chậm: 5xx > 2% trong 1h, 30m liên tục → ticket | — | Cùng biểu thức đã khai báo ở `observability-logging.md` mục 3 (`http-5xx-burn-rate-fast/slow`), chỉ thêm filter `route="/classes/{id}/attendance"`. |

Ghi chú phạm vi lỗi: request bị từ chối bởi rate-limit (429, NFR-004/005: 120/phút/tài khoản,
600/phút/IP — `qlkh/application/rate_limit.py`) hoặc 422 (dữ liệu điểm danh sai định dạng)
**không** tính vào error budget 5xx — đó là hành vi đúng theo contract, không phải lỗi hệ thống.

## 2. POST /auth/login

Bối cảnh: ADR-002 (argon2id, khóa tạm theo tài khoản), NFR-002 (`qlkh/domain/auth.py`).

| Chỉ số | Ngưỡng | Cửa sổ | Nguồn |
|---|---|---|---|
| p95 latency | **< 800 ms** | tức thời (rolling 5m để alert), báo cáo theo 30 ngày rolling | **Không có số NFR-002 tường minh nào cho latency trong architecture/threat-model** — đã tìm kiếm (`search NFR-002`, `argon2id`, domain/auth.py) và không thấy con số milliseconds nào được chốt trước đó, khác với attendance. Số 800ms là **đề xuất của platform**, suy ra từ: (a) argon2id ghim `time_cost=3, memory_cost=64MiB, parallelism=4` (`qlkh/application/auth_service.py` DEFAULT_PARAMS) — chi phí KDF cố ý chậm nhưng thường dưới ~150ms trên phần cứng server thông thường; (b) trần timeout hạ lưu đã khai báo trong architecture (DB 5s, session store/Redis 1s); (c) cùng nhóm NFR-004/005 "hiệu năng, sẵn sàng" áp cho toàn hệ thống. **Cần architect hoặc delivery-lead xác nhận/điều chỉnh con số này trước khi dùng làm cam kết SLA chính thức** — khác với ngưỡng attendance (tái dùng số đã có), số này là số mới, ghi rõ để không bị hiểu nhầm là đã chốt từ trước. |
| Tỉ lệ lỗi 5xx | **≤ 0.3%** request trong cửa sổ 30 ngày rolling (error budget = 0.3%) | 30 ngày rolling | Đăng nhập là điểm vào duy nhất của mọi vai trò (kể cả admin MFA) — ngưỡng chặt tương đương mức bảo thủ chung cho endpoint xác thực; chưa có số NFR-002 riêng nên áp cùng mức 99.7% availability như baseline SRE phổ biến, cần xác nhận cùng lúc với p95 ở trên. |
| Burn-rate alert (tái dùng, lọc route) | nhanh: 5xx > 5% / 5m, 10m → page; chậm: 5xx > 2% / 1h, 30m → ticket | — | Cùng biểu thức `http-5xx-burn-rate-*` đã có, filter `route="/auth/login"`. |
| **Loại trừ khỏi error budget** | **401 do sai thông tin đăng nhập (mật khẩu sai, tài khoản không tồn tại, MFA sai) KHÔNG tính vào error budget 5xx.** Đây là hành vi đúng theo contract (`qlkh/domain/auth.py`: thông điệp lỗi đồng nhất cho mọi nguyên nhân, chống liệt kê tài khoản — threat T-04). Chỉ 5xx thật (lỗi DB, lỗi session store, lỗi không xử lý được) tính vào error budget. | — | — |
| Tín hiệu bảo mật riêng (không phải SLO) | `401 rate (baseline 24h)` — spike bất thường là tín hiệu brute-force, thuộc alert `auth-login-401-spike-brute-force` đã khai báo ở dashboard PII (`infra/QLKH/observability/dashboards/pii-endpoints.md`), KHÔNG cộng vào error budget 5xx ở trên. | — | Tránh nhầm 401 cao là "vi phạm SLO" — nó là tín hiệu an ninh khác, xử lý theo runbook riêng. |

## 3. Cấu hình khai báo (để release-engineer import khi có backend giám sát thật)

```yaml
# infra/QLKH/slo/slo-definitions.yaml (khai báo — đối chiếu, chưa apply)
service: qlkh-api
window_rolling_days: 30
slos:
  - route: "/classes/{id}/attendance"
    latency:
      metric: p95
      threshold_seconds: 1.0
      load_scenario: "<=60 phien dong thoi, khung 17h30-18h00 (RISK-4/NFR-004)"
      source: "reuse: observability-logging.md#attendance-p95-latency, prd/risk-register.json#RISK-4.early_warning"
    error_rate:
      counts_as_error: ["5xx"]
      excludes: ["429 rate-limit", "422 validation"]
      budget_pct_30d: 0.5
    burn_rate_alerts:
      - name: attendance-5xx-burn-fast
        window: 5m
        for: 10m
        threshold_pct: 5
        severity: page
      - name: attendance-5xx-burn-slow
        window: 1h
        for: 30m
        threshold_pct: 2
        severity: ticket
  - route: "/auth/login"
    latency:
      metric: p95
      threshold_seconds: 0.8
      status: "PROPOSED - can architect/delivery-lead xac nhan, khong phai so da chot truoc do"
    error_rate:
      counts_as_error: ["5xx"]
      excludes: ["401 invalid-credentials (contract dung, chong enumeration - T-04)", "429 lockout/throttle (ADR-002)"]
      budget_pct_30d: 0.3
    burn_rate_alerts:
      - name: auth-login-5xx-burn-fast
        window: 5m
        for: 10m
        threshold_pct: 5
        severity: page
      - name: auth-login-5xx-burn-slow
        window: 1h
        for: 30m
        threshold_pct: 2
        severity: ticket
```

## 4. Hành động khi error budget bị tiêu hết (trong cửa sổ 30 ngày rolling)

Áp dụng cho cả hai endpoint, theo chính sách error-budget chuẩn (Google SRE, xem skill
`observability`):

1. **Phát hiện**: burn-rate alert "chậm" (2%/1h) fire liên tục hoặc tổng tỉ lệ lỗi 30 ngày
   vượt ngưỡng ở bảng trên → dashboard hiển thị error budget còn lại < 0.
2. **Hành động bắt buộc ngay khi budget về 0 hoặc âm**:
   - Đóng băng thay đổi rủi ro cao trên endpoint đó (không merge thay đổi logic nghiệp vụ
     mới cho `/auth/login` hoặc `/classes/{id}/attendance`; feature flag đang bật giữ nguyên,
     không bật thêm cái mới liên quan).
   - Ưu tiên số 1 của sprint kế tiếp là vá lỗi/ổn định hóa endpoint đó (đưa vào backlog với
     priority cao nhất), không nhận thêm việc tính năng mới trên cùng module cho tới khi budget
     phục hồi dương.
   - Nếu nguyên nhân là do bản phát hành gần nhất (đối chiếu `release_version` trong metric,
     theo `observability-logging.md`) → rollback bằng IaC/feature flag trước, điều tra sau
     (thứ tự theo `incident-management`).
3. **Ai ra quyết định**:
   - **delivery-lead** ra quyết định đóng băng tính năng mới trên project QLKH (có quyền
     điều phối backlog/sprint) — dựa trên dữ liệu do **platform** cung cấp (dashboard/alert).
   - **architect** xác nhận khía cạnh kỹ thuật (có phải do thiết kế/NFR chưa đủ, hay do lỗi
     triển khai cụ thể) và đề xuất hướng vá.
   - **security-engineer** được tham vấn bắt buộc nếu nguyên nhân liên quan `/auth/login`
     (xác thực) vì chạm ADR-002/NFR-002 và có thể là dấu hiệu tấn công, không chỉ lỗi hiệu năng.
   - Quyết định và ngày tháng ghi vào ticket vận hành tương ứng (không quyết định miệng).
4. Budget phục hồi dương khi tỉ lệ lỗi trung bình 30 ngày rolling quay lại dưới ngưỡng — đóng
   băng được gỡ bởi cùng người đã ra quyết định đóng băng (delivery-lead).

## 5. Nợ mở

| id | nội dung | owner | điều kiện đóng |
|---|---|---|---|
| QLKH-013-e | Xác nhận/điều chỉnh ngưỡng p95 800ms và error budget 0.3% cho `/auth/login` (đề xuất, chưa có NFR số tường minh) | architect + delivery-lead | có quyết định ghi lại, cập nhật file này |
| QLKH-013-f | Triển khai backend giám sát thật (DEF-03) và import cấu hình YAML mục 3 | platform (sau khi DEF-03 chốt, cùng QLKH-013-b/c) | dashboard thật hiển thị đúng 2 route, alert fire thử được |
| QLKH-013-g | Diễn tập: tạo tải/lỗi thật để xác nhận burn-rate alert fire đúng ngưỡng cho 2 route này | platform/release-engineer | có bằng chứng (log alert fired) đính kèm ticket vận hành |
