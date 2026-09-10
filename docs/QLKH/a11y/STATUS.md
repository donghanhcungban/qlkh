## Trạng thái kịch bản a11y (TCK-CR-RUNTIME-04 / CR-RUNTIME-NFR-001)

Ngày: 2026-09-10

### Đã có sẵn trong repo (từ lượt hiện thực trước, đã commit, `git_status` sạch)

1. **Script tồn tại, chạy được bằng lệnh ghi trong README** — thỏa acceptance #1:
   - `web/package.json`: script `"a11y": "vitest run src/a11y"`.
   - `web/README.md` mục "Kiểm tra khả năng tiếp cận (a11y)": lệnh rõ ràng
     `cd web && npm install && npm run a11y`.
   - Bộ test thật: `web/src/a11y/screens.a11y.test.tsx` — chạy `axe-core` trên
     DOM `jsdom` cho 3 màn hình chính đã cam kết trong scope: đăng nhập
     (`Login`, trạng thái default), danh sách học viên (`ParentDashboard`,
     trạng thái loading + error), điểm danh (`TeacherDashboard`, trạng thái
     success).
   - Test **fail** (không tự ý bỏ qua) nếu có vi phạm `critical`/`serious` —
     thỏa acceptance #3 ("vi phạm mức nghiêm trọng cao được ghi finding,
     không tự ý bỏ qua"): xem `expectNoHighSeverity()` trong file test.
   - Mỗi lần chạy `npm run a11y` tự sinh/ghi đè `docs/QLKH/a11y/report.md`
     với số liệu THẬT (đếm violations theo severity, per màn hình/trạng thái)
     — không phải số liệu ước lượng (xem hook `afterAll` trong file test).

### Còn thiếu — chưa có bằng chứng: `docs/QLKH/a11y/report.md` chưa từng được
sinh/commit trong worktree này

Đã xác nhận `docs/QLKH/a11y` **không tồn tại** trong worktree (kiểm bằng
`list_files`) và `git_status`/`git_diff` sạch — nghĩa là chưa có lượt nào
thực sự CHẠY `npm run a11y` và commit report thật, dù script đã sẵn sàng.

**Lý do: giới hạn năng lực công cụ của agent `builder` (lượt này), không phải
bỏ sót hay lười.** Tool `run` chỉ nhận đúng 4 lệnh cố định: `git_diff`,
`git_status`, `lint`, `test`. Đã kiểm chứng thật trong lượt này:

- `run lint --paths web` → `"warning: No Python files found under the given
  path(s)"` (lint ở đây là **ruff**, chỉ quét Python, không phải `eslint`
  của `web/`).
- `run test --paths web` → **exit=5** (pytest "không thu thập được test nào"
  ở đường dẫn đó) — không phải `vitest`, không chạy được
  `web/src/a11y/screens.a11y.test.tsx`.
- `run test` (không path) → chạy bộ pytest của phần Python, không đụng tới
  `web/`.

Không có cách nào trong 4 lệnh cố định này để gọi `npm run a11y` (cần Node
runtime + `vitest` + `jsdom`, hoàn toàn ngoài `lint`/`test` đã cấu hình sẵn
cho Python). Đây là giới hạn công cụ được cấp cho `builder`, tương tự tình
huống đã ghi nhận ở `docs/db/mutation-testing.md` (TCK-CR-RUNTIME-06) với
`mutmut`.

### Việc bàn giao

Người/agent có shell Node thật (ví dụ `platform`/`release-engineer`, hoặc
người vận hành chạy tay) cần:

```bash
cd web
npm install   # lần đầu
npm run a11y
```

rồi commit `docs/QLKH/a11y/report.md` sinh ra (số liệu thật) vào repo làm
bằng chứng cho acceptance #2. Nếu report cho thấy vi phạm `critical`/`serious`
thật, `npm run a11y` sẽ tự fail — đúng theo acceptance #3, không cần thêm
bước thủ công nào để "chặn".

### Không có thay đổi code nào trong ticket này

Không sửa `web/src/a11y/screens.a11y.test.tsx` (thuộc phạm vi test, và đã
đúng theo mô tả ticket), không sửa `web/package.json`/`web/README.md` (đã
đúng, đã mô tả đủ lệnh). Chỉ thêm tài liệu trạng thái này để không im lặng
về phần chưa xong.
