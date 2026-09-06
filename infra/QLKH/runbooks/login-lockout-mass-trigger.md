# RB-QLKH-OPS-001-03 — Rate limit / khóa tạm đăng nhập bị kích hoạt hàng loạt

- Ticket: TCK-CR-OPS-001-03 (CR-OPS-001)
- Dịch vụ: `qlkh-api` — endpoint `POST /auth/login`
- Alert liên kết (đặt trong `infra/QLKH/alerts.yaml` khi backend giám sát thật
  (DEF-03) sẵn sàng — xem `infra/QLKH/observability-logging.md` mục 3 và
  `infra/QLKH/observability/dashboards/pii-endpoints.md` mục 1):
  `auth-login-401-spike-brute-force`, kèm bổ trợ `auth-login-429-rate` (429
  do khóa tài khoản hoặc throttle IP tăng bất thường).
- Nguồn cơ chế: ADR-002 (khóa tài khoản + throttle IP), api-contract v1.4.0
  `POST /auth/login` (openapi.yaml dòng ~8, ~243-271), triển khai thật tại
  `qlkh/domain/auth.py` (`ACCOUNT_POLICY`, `IP_POLICY`) và
  `qlkh/application/auth_service.py`, `qlkh/application/rate_limit.py` /
  `rate_limiter.py`.

## 0. Ba cơ chế khác nhau — đừng nhầm khi đọc log/alert

| Cơ chế | Khóa theo | Ngưỡng | Cửa sổ | Hành vi khi vượt | Nơi cài |
|---|---|---|---|---|---|
| Khóa tài khoản (brute-force theo account) | `user_id`/email | 5 lần sai | 15 phút | Khóa cứng 15 phút (401→429 khi đang khóa) | `ACCOUNT_POLICY`, `auth.py:26-28` |
| Throttle IP theo lần sai đăng nhập | IP nguồn của request login | 50 lần sai | 15 phút | Backoff cấp số nhân, KHÔNG khóa cứng (429 + Retry-After tăng dần) | `IP_POLICY`, `auth.py:32-33` |
| Rate limit chung theo IP (mọi endpoint, kể cả login) | IP nguồn | 600 req/phút | 1 phút (cửa sổ cố định) | 429 + Retry-After = phần cửa sổ còn lại | `rate_limiter.py` (`DEFAULT_IP_LIMIT=600`), api-contract dòng 8/445 |

Ba cơ chế độc lập, có thể fire cùng lúc hoặc riêng lẻ. Khi điều tra, xác định
**alert nào fire** trước khi chọn bước giảm nhẹ — mở khóa tài khoản không giúp
gì nếu vấn đề thật là throttle IP hoặc rate limit chung, và ngược lại.

## 1. Phân biệt brute-force thật vs sự cố client (bug retry loop)

Không hành động (mở khóa, chặn IP, thông báo an ninh) trước khi đối chiếu đủ
các tín hiệu sau. Log audit `login_failed`/`login_locked` (không PII thô —
chỉ `user_id`/email đã băm hoặc id nội bộ, IP, timestamp, `error_type`) là
nguồn chính; đối chiếu thêm `release_version` trong metric để loại trừ do
triển khai mới.

| Tín hiệu | Brute-force / credential stuffing thật | Bug client (retry loop) |
|---|---|---|
| Số tài khoản bị ảnh hưởng | Nhiều tài khoản, tăng dần theo thời gian, thường không liên quan nghiệp vụ (không cùng lớp/cơ sở) | Thường 1 tài khoản, hoặc một nhóm hẹp dùng chung một phiên bản app/thiết bị lỗi (vd một trường học vừa cập nhật app) |
| Mật khẩu thử | Nhiều mật khẩu khác nhau cho cùng 1 tài khoản (brute-force cổ điển), HOẶC cùng 1 mật khẩu cho nhiều tài khoản khác nhau (credential stuffing) | Y HỆT một mật khẩu lặp lại liên tục trên cùng tài khoản (mật khẩu cached đã đổi, hoặc bug không xóa access token/mật khẩu sai vẫn lưu) |
| Nhịp độ request | Đều đặn hoặc dồn dập ở biên ngưỡng (né threshold), nhiều IP nguồn khác nhau xoay vòng | Rất đều, cùng một khoảng nghỉ cố định (đúng chu kỳ retry hard-code trong code client), 1 IP hoặc dải IP hẹp |
| User-Agent | Đa dạng hoặc giả mạo trình duyệt phổ biến; hoặc thiếu User-Agent | Đồng nhất — đúng 1 phiên bản app cụ thể (vd `QLKH-mobile/2.3.1`) |
| Tương quan thời điểm | Không khớp sự kiện vận hành nào | Trùng khớp thời điểm phát hành bản mới, đổi API, hoặc hết hạn refresh token hàng loạt (kiểm `release_version` trên metric) |
| Endpoint khác có bị dò song song không | Có thể kèm dò `/students/{id}` (IDOR scan) hoặc nhiều `GET /auth/me` 401 | Chỉ có `/auth/login`, không kèm dò endpoint khác |

Quy tắc quyết định nhanh:
1. Nếu **cùng một tài khoản, cùng một mật khẩu, nhịp đều, 1 nguồn IP hẹp**
   → nghi bug client trước, KHÔNG báo an ninh ngay; xác nhận bằng cách liên
   hệ đội phát triển client/mobile hoặc trường/cơ sở liên quan, kiểm bản phát
   hành gần nhất.
2. Nếu **nhiều tài khoản không liên quan, nhiều mật khẩu hoặc cùng mật khẩu
   lan nhiều tài khoản, nhiều IP** → coi là tấn công thật, đi thẳng bước 3
   (mass lockout) và mở sự cố theo `incident-management` (SEV theo số tài
   khoản phụ huynh/học viên bị khóa, vì đây là dữ liệu trẻ em — ưu tiên SEV2
   trở lên nếu > 50 tài khoản bị khóa cùng lúc).
3. Trường hợp không rõ ràng → vẫn ưu tiên giảm nhẹ (xem bước 3) trước, xác
   định nguyên nhân sau — không chặn người dùng hợp lệ lâu hơn mức cần thiết
   để "chắc chắn 100%".

## 2. Lockout hàng loạt trên nhiều tài khoản cùng lúc

### 2.1 Xác nhận không phải false-lockout do lỗi hệ thống

Trước khi coi đó là tấn công, loại trừ khả năng chính hệ thống gây khóa nhầm:

- Kiểm `release_version` trên metric `auth-login` tại thời điểm bắt đầu spike
  — có bản triển khai mới ngay trước đó không (vd đổi tham số argon2id, đổi
  encoding mật khẩu, lỗi `PasswordHasher.verify` trả `False` sai)?
- Kiểm tỉ lệ lỗi theo `error_type`: nếu tăng đột biến `InvalidCredentials`
  đồng loạt trên các tài khoản đang hoạt động bình thường (không phải các
  tài khoản bị dò) → nghi verify mật khẩu hỏng (lỗi hệ thống), KHÔNG phải
  brute-force. Brute-force thật vẫn có tỉ lệ 401 nền bình thường ở các tài
  khoản không bị nhắm tới.
- Thử đăng nhập bằng 1 tài khoản test nội bộ có mật khẩu biết chắc đúng, ở
  môi trường staging trước, prod sau nếu cần — nếu tài khoản test cũng bị từ
  chối sai → xác nhận lỗi hệ thống, chuyển hướng xử lý sang rollback bản phát
  hành lỗi (theo bảng "xử lý khi phụ thuộc hỏng" trong `architecture` và
  runbook `RB-QLKH-013-http-5xx.md` nếu kèm 5xx), KHÔNG mở khóa từng tài
  khoản (khóa sẽ tự tái diễn vì nguyên nhân gốc vẫn còn).
- Kiểm session store (Redis/P2) có đang lỗi/mất kết nối không — bộ đếm dùng
  chung nằm ở đây; sự cố hạ tầng ở P2 có thể khiến `AttemptStore` fallback về
  in-memory (SD-29) và khóa lệch giữa các worker, tạo cảm giác "khóa hàng
  loạt vô lý". Kiểm log khởi động ứng dụng có cảnh báo fail-fast của
  `auth_wiring.py` không.

### 2.2 Thông báo

- **Xác định là tấn công thật (2.1 đã loại trừ lỗi hệ thống)**: báo
  security-engineer ngay (chủ sở hữu RISK-3/RISK-9), mở kênh sự cố theo
  `incident-management`; báo delivery-lead nếu ảnh hưởng > 50 tài khoản hoặc
  kéo dài > 30 phút; nếu phụ huynh/giáo viên bị ảnh hưởng liên hệ hỗ trợ
  (kênh CSKH/Zalo/SMS nội bộ dự án) để chuẩn bị trả lời khi có khiếu nại.
- **Xác định là false-lockout do lỗi hệ thống (2.1 xác nhận)**: báo ngay đội
  phát hành/backend chịu trách nhiệm bản triển khai gần nhất (release-engineer
  + tác giả PR) để rollback hoặc hotfix; báo delivery-lead vì đây là sự cố
  ảnh hưởng người dùng diện rộng, không phải vấn đề an ninh; KHÔNG cần báo
  security-engineer trừ khi nghi ngờ vẫn còn tồn tại rủi ro uỷ quyền.
- Trong mọi trường hợp: ghi thời điểm phát hiện, số tài khoản ảnh hưởng, và
  kết luận (tấn công/lỗi hệ thống) vào dòng thời gian sự cố theo thời gian
  thực (không dựng lại sau).

### 2.3 Mở khóa thủ công có kiểm soát (chỉ khi xác định false-lockout, hoặc
sau khi tấn công đã bị chặn ở lớp mạng/IP)

Không mở khóa hàng loạt trong khi vector tấn công (nếu có) vẫn đang hoạt
động — mở khóa lúc đó chỉ khiến kẻ tấn công thử lại ngay.

1. Điều kiện tiên quyết: (a) đã xác nhận false-lockout theo 2.1, HOẶC (b) đã
   xác nhận là tấn công và đã chặn được nguồn (chặn IP/dải IP ở biên, hoặc
   xác nhận throttle IP đã tự hạ nhiệt) trước khi mở khóa tài khoản nạn nhân.
2. Yêu cầu ai đó **không phải người phát hiện** phê duyệt thao tác mở khóa
   hàng loạt (nguyên tắc hai người, vì đây là thao tác trên dữ liệu xác thực
   của trẻ em/phụ huynh — tương đương RISK-3/RISK-9).
3. Mở khóa bằng cách gọi `AttemptStore.reset(key)` theo đúng danh sách
   `user_id` đã xác nhận bị ảnh hưởng (không reset toàn bộ store một cách mù
   quáng — sẽ xóa luôn bộ đếm của các tài khoản đang thật sự bị dò và chưa
   hết nghi vấn). Thao tác này phải chạy qua job/script vận hành có ghi log,
   không sửa tay trực tiếp trên session store (Redis) qua console/CLI kết
   nối thủ công — vi phạm quy tắc "không sửa tay trên console/server".
4. Ghi audit: ai duyệt, ai thực hiện, danh sách tài khoản, thời điểm, lý do
   (đối chiếu NFR-007 — audit log đầy đủ, không chứa PII thô, chỉ id/thời
   điểm giống mẫu `erasure_requested`/`retention_erasure_run` đã áp dụng cho
   luồng xóa dữ liệu).
5. Theo dõi 30 phút sau khi mở khóa: nếu lockout tái diễn ngay trên cùng tập
   tài khoản → quay lại bước 1, tấn công vẫn đang tiếp diễn hoặc chặn IP chưa
   đủ, không mở khóa thêm.

## 3. Rate limit IP 600 req/phút — phân biệt tấn công vs NAT chung

Ngưỡng 600 req/phút/IP trong api-contract là ngưỡng chặn cứng cho **toàn bộ
API** (không riêng login), nên một địa chỉ IP văn phòng/trường học dùng NAT
(nhiều giáo viên/phụ huynh chung IP, đặc biệt cao điểm 17h30–18h00 theo
`architecture`, tối đa 60 giáo viên đồng thời) có thể chạm ngưỡng này một
cách hợp lệ. Không dùng riêng con số 600 req/phút để kết luận tấn công.

Tiêu chí phân biệt (đối chiếu cùng lúc, không chỉ 1 tín hiệu):

| Tín hiệu | NAT chung (hợp lệ) | Tấn công (chặn) |
|---|---|---|
| Tỉ lệ lỗi 401/429 trên tổng request của IP đó | Thấp — phần lớn 2xx/3xx, vì đa số người dùng đăng nhập thành công và thao tác bình thường | Cao — phần lớn request là 401 (login sai) hoặc tập trung gần như 100% vào `/auth/login` |
| Số tài khoản distinct dùng IP đó | Tương ứng số người thật tại địa điểm đó (dùng dữ liệu tham chiếu: trường/cơ sở có bao nhiêu giáo viên/phụ huynh) — ổn định qua nhiều ngày | Tăng đột biến so với baseline của chính IP đó, hoặc IP mới xuất hiện lần đầu với số tài khoản distinct rất lớn ngay lập tức |
| Phân bố endpoint | Trải trên nhiều endpoint nghiệp vụ (`/attendance`, `/students/{id}`, `/auth/me`...), đúng luồng dùng thật | Gần như chỉ có `/auth/login` (và có thể `/students/{id}` nếu kèm dò IDOR) |
| So với baseline 7 ngày của chính IP | Biến động cùng nhịp giờ cao điểm hằng ngày (17h30–18h00), lặp lại theo lịch học | Đột biến bất thường, không theo lịch cố định, hoặc IP hoàn toàn mới |
| Thời điểm | Trùng khung giờ điểm danh/giờ học đã biết trước | Bất kỳ giờ nào, kể cả ngoài giờ hành chính/giờ học |

Ngưỡng hành động cụ thể:
- IP đã có trong danh sách tham chiếu "IP cơ sở/trường đã biết" (nếu vận
  hành duy trì được danh sách IP tĩnh của 3 cơ sở) → nới ngưỡng cảnh báo,
  không tự động chặn, chỉ tăng theo dõi.
- IP lạ, chưa từng thấy, tỉ lệ lỗi 401/429 > 80% trong cửa sổ 5 phút, và số
  tài khoản distinct bị thử > 20 → chặn ở biên (WAF/rate-limit tầng mạng),
  báo security-engineer.
- IP lạ nhưng tỉ lệ lỗi thấp (< 20%) và endpoint đa dạng dù tổng request vượt
  600/phút → khả năng cao là NAT hợp lệ tải cao; KHÔNG chặn, chỉ theo dõi
  thêm; cân nhắc báo architect/platform để đánh giá có cần nâng ngưỡng riêng
  cho các IP cơ sở đã xác định (đổi cấu hình qua IaC, không sửa tay).

## 4. Leo thang và đóng sự cố

- SEV theo `incident-management`: SEV2 nếu > 50 tài khoản phụ huynh/học viên
  bị khóa hoặc > 30 phút chưa xác định nguyên nhân; SEV1 nếu có dấu hiệu dữ
  liệu bị truy cập trái phép (kết hợp alert `students-id-403-404-idor-scan`).
- Sau khi ổn định: postmortem blameless trong 48h nếu SEV1/2; action item có
  owner + hạn + ticket thật (vd bổ sung danh sách IP cơ sở tham chiếu, hoặc
  sửa bug retry loop ở client).
- Cập nhật lại bảng ngưỡng ở runbook này nếu diễn tập/sự cố thật cho thấy
  ngưỡng 20 tài khoản/80% lỗi ở mục 3 không còn phù hợp.

## 5. Nợ mở

- Chưa có backend giám sát thật (DEF-03 mở) nên các con số alert (401 spike,
  429 spike) hiện là khai báo, chưa diễn tập được bằng dữ liệu thật; runbook
  này cần được thử lại (game day) khi có backend giám sát thật, theo
  `resilience-testing`.
- File `infra/QLKH/alerts.yaml` chưa tồn tại trong worktree tại thời điểm
  viết runbook này (chỉ có khai báo YAML rời rạc trong
  `infra/QLKH/observability-logging.md` mục 3 và bảng "Alert liên kết" trong
  `infra/QLKH/observability/dashboards/pii-endpoints.md`). Khi
  TCK-CR-OPS-001-01 tạo/khớp `alerts.yaml` thật, cần xác nhận trường
  `runbook:` của các rule `auth-login-401-spike-brute-force` và
  `auth-login-429-*` trỏ đúng
  `infra/QLKH/runbooks/login-lockout-mass-trigger.md` — hiện KHÔNG thể tự
  đối chiếu vì file nguồn chưa tồn tại để đọc/sửa.
