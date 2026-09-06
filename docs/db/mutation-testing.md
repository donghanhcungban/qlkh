# Mutation testing thật cho module schema/db (TCK-CR-RUNTIME-06)

## Trạng thái: BỊ CHẶN — không có công cụ để tạo bằng chứng thật

Ticket yêu cầu (CR-RUNTIME-NFR-001):
1. Lệnh chạy mutation testing ghi trong `docs/db` (tài liệu này).
2. Báo cáo mutation score **thật** ≥70% cho module schema đã chọn, kèm output thật.
3. Không sửa file test do test-author sở hữu ngoài phạm vi ADR-0028 nếu không cần thiết.

## Module đề xuất cho mutation testing

`tools/schema_meta.py` — kiểm tra tĩnh schema (idempotent, rollback pair, PII metadata,
retention anchor, encrypted_at_rest), không cần DB, logic thuần Python, đã có 29+38 test
tĩnh bao phủ (`tests/schema/test_core_schema.py`, `tests/schema/test_pii_key_and_consent.py`).
Đây là ứng viên hợp lý nhất cho mutation testing trong phạm vi "core-schema/db layer" vì
không phụ thuộc Postgres thật (khác với `tests/schema/test_postgres_integration.py`, vốn
đã bị skip trong mọi worktree agent — xem `schema/QLKH/core-schema.md` mục "Vòng 5").

## Lệnh dự kiến (CHƯA chạy được — xem lý do bên dưới)

```bash
pip install mutmut==2.5.1   # hoặc cosmic-ray, tùy CI chọn
mutmut run --paths-to-mutate tools/schema_meta.py \
  --tests-dir tests/schema \
  --runner "python -m pytest tests/schema/test_core_schema.py tests/schema/test_pii_key_and_consent.py -q"
mutmut results
mutmut html   # báo cáo HTML mutation score
```

## Vì sao KHÔNG có báo cáo mutation score thật kèm theo tài liệu này

Agent `database` chạy trong worktree cô lập, chỉ được cấp **đúng 4 lệnh** qua tool `run`:
`git_diff`, `git_status`, `lint`, `test`. Đây là các lệnh cố định (không phải shell tùy ý):
không có cách nào trong bộ công cụ được cấp để:

- cài đặt gói mới (`pip install mutmut` / `cosmic-ray`) — không có `mutmut`/`cosmic-ray`
  trong `requirements.lock` hay `pyproject.toml` (đã kiểm bằng `search`, không có kết quả);
- chạy một lệnh binary tùy ý (`mutmut run ...`) — `run` chỉ nhận 4 tên lệnh cố định ở trên,
  không nhận lệnh shell tự do.

Vì vậy: **không có cách nào trong phạm vi công cụ được cấp cho agent `database` (lượt này)
để tự tạo ra bằng chứng "mutation score thật, kèm output thật"** mà ticket yêu cầu. Đây là
giới hạn năng lực công cụ, không phải suy đoán hay lười — đã thử `search` xác nhận không có
gói mutation testing nào sẵn có trong repo/dependency lock trước khi kết luận.

## Đề xuất người có năng lực làm nốt

1. `platform`/`release-engineer` (hoặc người có quyền chạy shell tùy ý / sửa CI pipeline):
   thêm job CI cài `mutmut` (ghim version, cập nhật `requirements.lock` nếu cần) và chạy
   lệnh ở mục "Lệnh dự kiến" trên target `tools/schema_meta.py`, đính kèm link/log job pass
   thật cùng % mutation score vào tài liệu này.
2. Nếu mutation score thật <70%: bổ sung test tĩnh/tích hợp để nâng lên (theo đúng scope
   ticket), **không sửa migration đã chốt** — việc bổ sung test thuộc namespace test-author
   theo ADR-0028 trừ khi được giao lại cho `database`.
3. Sau khi có bằng chứng thật: cập nhật mục này (bỏ trạng thái BỊ CHẶN, dán số liệu + link)
   và `schema/QLKH/core-schema.md` (mục "Việc còn nợ") tương ứng.

## Không thay đổi nào khác

Không sửa file test (`tests/schema/*`), không sửa migration, không sửa CI trong ticket này —
đúng scope "chỉ báo cáo/tài liệu" khi chưa có bằng chứng thật để báo cáo.
