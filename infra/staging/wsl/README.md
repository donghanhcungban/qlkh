# QLKH — Staging THẬT trên WSL (CR-STAGE-001 / ADR-0013)

Đây là môi trường staging **thật** (không phải lời khai) chạy trên máy WSL của
chủ dự án, dùng để có bằng chứng khách quan "staging deployed" trước khi
release-engineer công bố. Ngoài phạm vi: DB thật, Redis, TLS, domain, cloud
(xem ADR-0013).

## 1. Yêu cầu máy

- WSL2 (Ubuntu khuyến nghị) hoặc Linux tương đương.
- Tối thiểu: **4 CPU / 8 GB RAM / 20 GB đĩa trống**.
- Khi devserver đang chạy, mức dùng thực tế kỳ vọng **≤ 1 CPU, ≤ 512 MB RAM**
  (đo bằng `ps`/`top`, ghi trong PR nghiệm thu theo tiêu chí CR-STAGE-001) —
  yêu cầu máy ở trên là để chạy build (đặc biệt `npm run build`) và git clone,
  không phải mức dùng khi phục vụ traffic.
- Phần mềm cần cài **trước lần deploy đầu tiên**:
  - `git`, `curl`, `python3` (đã có sẵn trên hầu hết distro) — `python3 -m venv`
    phải dùng được (gói `python3-venv` trên Debian/Ubuntu).
  - Node.js **LTS** (khuyến nghị dùng `nvm` hoặc gói LTS chính thức) — cần cho
    `npm run build` (xem mục 4, web build phục vụ tại `/`).
  - **Không cần cài `uv`**: `deploy.sh` cài dependency Python bằng
    `pip install --require-hashes -r requirements.lock` trong một virtualenv
    riêng (`~/qlkh-staging/.venv`) — đúng cơ chế khoá phiên bản chính thức của
    dự án (ADR-0014, đóng SD-13). Không dùng `uv sync --frozen`/`uv.lock`.

Cài đặt lần đầu (ví dụ Ubuntu trên WSL2):

```bash
sudo apt-get update && sudo apt-get install -y git curl python3 python3-venv
# Node LTS — ví dụ qua nvm:
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install --lts
```

Không cần cài đặt gì thêm trước khi chạy `deploy.sh` lần đầu ngoài các mục
trên — bản thân `deploy.sh` sẽ tự clone repo vào `~/qlkh-staging` nếu thư mục
đó chưa tồn tại, và tự tạo virtualenv Python nếu chưa có.

## 2. Lệnh deploy / rollback / smoke

Ba script nằm tại `infra/staging/wsl/`. Chạy trực tiếp từ checkout repo nguồn
(không cần `cd` vào `~/qlkh-staging`):

### 2.1 Deploy một phiên bản (git tag hoặc sha)

```bash
infra/staging/wsl/deploy.sh v0.16.0
```

- Idempotent: chạy lại cùng ref không lỗi, không nhân đôi tiến trình.
- Việc script làm: fetch ref vào `~/qlkh-staging` → cài dependency vào
  `~/qlkh-staging/.venv` bằng `pip install --require-hashes -r
  requirements.lock` (ADR-0014 — nguồn khoá phiên bản chính thức duy nhất,
  không dùng `uv sync --frozen`/`uv.lock`) → dừng tiến trình devserver cũ
  (qua pidfile) → khởi động `python -m qlkh.devserver --host 0.0.0.0 --port
  8080` (nohup, dùng python của `.venv`) → chờ `GET /healthz` trả 200 đúng
  sha (mặc định tối đa 30 giây).
- `exit != 0` nếu bất kỳ bước nào thất bại, kể cả khi `/healthz` không xanh
  trong thời hạn chờ.
- Tiêu chí nghiệm thu CR-STAGE-001: hoàn tất trong **≤ 2 phút**.

### 2.2 Rollback về phiên bản trước

```bash
infra/staging/wsl/rollback.sh
```

- Tương đương gọi `deploy.sh <sha-trước>`, với sha đọc từ
  `~/qlkh-staging/var/previous` (do lần `deploy.sh` gần nhất ghi lại trước khi
  ghi đè `var/current`).
- Chỉ dùng được sau khi đã có **ít nhất hai** lần `deploy.sh` thành công (lần
  đầu chưa có "phiên bản trước" để về); nếu `var/previous` chưa tồn tại,
  script báo lỗi rõ ràng và `exit 1`.
- Tiêu chí nghiệm thu: hoàn tất trong **≤ 1 phút**.

Ví dụ một chu trình đầy đủ:

```bash
infra/staging/wsl/deploy.sh v0.16.0     # deploy bản mới
infra/staging/wsl/smoke.sh              # xác nhận hoạt động đúng
# ... phát hiện vấn đề ...
infra/staging/wsl/rollback.sh           # quay lại bản chạy trước v0.16.0
```

### 2.3 Smoke test

```bash
infra/staging/wsl/smoke.sh
```

- **Không tự deploy gì** — chỉ gọi HTTP vào staging đã chạy sẵn (chạy
  **sau** `deploy.sh`, không thay thế `deploy.sh`).
- Gọi tuần tự 4 bước và in method/path/mã HTTP mỗi bước ra stderr:
  1. `GET /healthz` → kỳ vọng 200 + `{version, sha, started_at}`.
  2. `POST /v1/auth/login` (tài khoản seed `teacher1@qlkh.test`) → kỳ vọng
     204 + cookie phiên `qlkh_session`.
  3. `GET /v1/auth/me` (dùng cookie ở trên) → kỳ vọng 200 +
     `{user_id, role, branch_ids}`.
  4. `GET /v1/students` (cùng cookie) → kỳ vọng 200 + `data` là mảng.
- `exit 0` chỉ khi cả 4 bước đúng mã HTTP **và** đúng hình dạng response;
  sai ở bất kỳ bước nào → `exit != 0` ngay tại bước đó.
- **Đây là bằng chứng "staging deployed" duy nhất** được chấp nhận theo
  ADR-0013 — tự khai báo không còn được chấp nhận sau ADR này.
- Không bao giờ in mật khẩu hay body đầy đủ ra log; không override tài khoản
  seed qua tham số dòng lệnh, chỉ qua biến môi trường `QLKH_SMOKE_EMAIL` /
  `QLKH_SMOKE_PASSWORD` nếu seed mặc định đổi sau này.

## 3. Xem log

Toàn bộ trạng thái vận hành (log + pidfile + sha đang chạy) nằm tại:

```
~/qlkh-staging/var/
```

Cụ thể:

- `~/qlkh-staging/var/devserver.log` — log hiện tại của devserver (nohup);
  xoay tự động khi vượt ~10 MiB (`devserver.log.1`, `.2`, ... tối đa 5 bản
  cũ theo mặc định).
- `~/qlkh-staging/var/devserver.pid` — pid tiến trình devserver đang chạy.
- `~/qlkh-staging/var/current` — sha đang chạy (ghi sau khi `/healthz` xanh).
- `~/qlkh-staging/var/previous` — sha chạy trước lần deploy thành công gần
  nhất (dùng cho `rollback.sh`).

Virtualenv Python nằm tại `~/qlkh-staging/.venv` — không phải log/trạng thái
deploy, chỉ là cache dependency được cài lại từ `requirements.lock` mỗi lần
`deploy.sh` chạy; có thể xoá thủ công an toàn (script tự tạo lại ở lần chạy
kế tiếp), khác với `var/` (không được xoá tay).

Xem log theo thời gian thực:

```bash
tail -f ~/qlkh-staging/var/devserver.log
```

Lưu ý: `~/qlkh-staging/var/` và `~/qlkh-staging/.venv/` nằm trong working tree
của checkout staging nhưng **không** được git track trong repo nguồn — không
xoá thư mục `var/` bằng tay và không chạy `git clean -fd` thủ công bên trong
`~/qlkh-staging` (các script đã tự loại trừ `var/` và `.venv/` khi dọn working
tree, nhưng thao tác tay ngoài script thì không được bảo vệ).

## 4. Giới hạn dữ liệu: in-memory, mất khi restart

Devserver của QLKH giữ dữ liệu **trong bộ nhớ tiến trình (in-memory)**, không
có Postgres/DB thật ở môi trường staging này. Hệ quả:

- Mỗi lần `deploy.sh` chạy (kể cả deploy lại cùng một ref), tiến trình cũ bị
  dừng và tiến trình mới khởi động **sạch** — toàn bộ dữ liệu đã tạo trong
  phiên trước (học viên, lớp, điểm danh, v.v., kể cả tài khoản seed đã đăng
  nhập) **mất hoàn toàn**. Chỉ dữ liệu seed mặc định (ví dụ tài khoản
  `teacher1@qlkh.test`) được tạo lại từ đầu mỗi lần khởi động.
- Tương tự, nếu tiến trình devserver bị crash hoặc máy WSL khởi động lại mà
  không ai chạy lại `deploy.sh`, dữ liệu cũng mất khi có ai chạy `deploy.sh`
  tiếp theo — không có cơ chế phục hồi dữ liệu.
- Đây là giới hạn **được chấp nhận** cho môi trường thử nghiệm/staging thử
  nghiệm (không phải production thật, không có dữ liệu cá nhân thật của
  người dùng — xem RISK-6 accepted có điều kiện,
  `prd/QLKH/risk-register.json`). **Không dùng môi trường này để lưu dữ liệu
  cần giữ lại qua các lần deploy**, và không coi smoke test hay thao tác thủ
  công trên staging là nguồn dữ liệu tin cậy lâu dài.

## 5. Việc còn lại / giới hạn đã biết

- README này mô tả hành vi đã đọc trực tiếp từ mã nguồn 3 script
  (`deploy.sh`, `rollback.sh`, `smoke.sh`) và code devserver liên quan
  (`qlkh/devserver/health.py`, `wiring.py`). Bản thân agent viết README này
  **không có khả năng chạy shell thật trên WSL** (sandbox chỉ có `lint` và
  `test` Python) — chưa tự xác nhận các bước trên chạy đúng trên máy WSL
  thật; đó là công việc nghiệp vụ còn lại cho platform/release-engineer, đã
  ghi trong `infra/QLKH/staging/TCK-CR-STAGE-001-03-notes.md`.
- risk_tags=`[auth]` áp dụng cho `smoke.sh` (gọi `/auth/login` thật với tài
  khoản seed) — đã qua deep-review bảo mật (threat-model v1.45 mục 37,
  verdict PASS, 2 warn không chặn).
