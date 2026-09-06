# Skip Audit — bộ test QLKH

- Ticket: TCK-CR-RUNTIME-07 (CR-RUNTIME-NFR-001, mục "test skip")
- Ngày: 2026-09-06
- Người thực hiện: platform
- Phương pháp: `grep`/search toàn bộ `**/*.py` cho `pytest.mark.skip`, `pytest.mark.skipif`,
  `pytest.skip(`, `xfail`, `unittest.skip`; đối chiếu với `.github/workflows/ci.yml`,
  `prd/QLKH/risk-register.json` (technical_debt_accepted), `schema/QLKH/core-schema.md`.
  Chạy `pytest` cục bộ (sandbox, không có Postgres) để lấy bằng chứng skip thật.

## Kết quả chạy test cục bộ (sandbox platform, KHÔNG phải CI thật)

`run test` → PASS, **15 test skip**, toàn bộ nằm trong
`tests/schema/test_postgres_integration.py` (module-level `skipif` vì thiếu
`QLKH_TEST_PG_DSN`/Postgres trong sandbox). Không có skip nào khác thực sự
kích hoạt trong lần chạy này (xem mục 2 bên dưới — `test_healthz.py` có 2
điểm `pytest.skip()` có điều kiện nhưng KHÔNG kích hoạt vì `git` sẵn có trong
sandbox).

> Lưu ý về con số "11 test skip" trong tiêu đề ticket: tại thời điểm audit
> này, `tests/schema/test_postgres_integration.py` có **15** hàm test (đã
> tăng so với baseline lúc ticket được mở — không rõ mốc 11 lấy từ đâu, có
> thể là số cũ trước khi file được bổ sung thêm test). Báo cáo này lấy số
> liệu THẬT tại thời điểm chạy, không cố khớp lại con số 11 trong tiêu đề.

## 1. `tests/schema/test_postgres_integration.py` — 15 test, skip toàn module

Danh sách 15 hàm test bị skip (module-level `pytestmark = pytest.mark.skipif(not PG_DSN, ...)`,
dòng 33-40):

1. `test_gherkin1_apply_0002_khong_loi`
2. `test_gherkin1_apply_0003_khong_loi`
3. `test_gherkin1_idempotent_apply_0002`
4. `test_gherkin1_idempotent_apply_0003`
5. `test_gherkin1_rollback_0003_khong_loi`
6. `test_gherkin1_rollback_0002_khong_loi`
7. `test_gherkin1_apply_rollback_full_cycle`
8. `test_pg_phone_key_version_null_duoc_phep`
9. `test_pg_phone_key_version_invalid_bi_reject`
10. `test_pg_role_code_invalid_bi_reject`
11. `test_pg_relation_invalid_bi_reject`
12. `test_pg_classes_name_unique_per_branch`
13. `test_pg_enrollments_unique_class_student`
14. `test_gherkin3_query_branch_id_dung_index`
15. `test_gherkin3_query_classes_branch_id_dung_index`

- **Lý do skip**: không có `QLKH_TEST_PG_DSN` / Postgres thật trong môi
  trường chạy test (dòng 30-40 của file, comment giải thích rõ).
- **Ticket/nợ kỹ thuật liên quan**: **SD-25** — đã có, ghi tại
  `schema/QLKH/core-schema.md` (v10) và `prd/QLKH/risk-register.json`
  (`technical_debt_accepted`, v21).
- **Trạng thái**: `accepted_for_test`, `accepted_by: human:owner`,
  `date: 2026-09-06`.
- **Hạn/điều kiện**: KHÔNG phải một ngày lịch cụ thể mà là điều kiện —
  "Bắt buộc phải hoàn thành (PG service chạy trong CI, test tích hợp thật
  thay vì skip) TRƯỚC KHI phát hành cho người dùng thật (production thật)".
  Scope hiện tại: môi trường thử nghiệm/staging thử nghiệm, KHÔNG áp dụng
  cho phát hành thật.
- **Xác nhận lại theo gợi ý trong scope ticket** ("SD-25 ... nay đã hết skip
  theo schema v9 — xác nhận lại"): **KHÔNG đúng, SD-25 CHƯA đóng.**
  `schema/QLKH/core-schema.md` v10 (mới hơn v9, cùng ngày) đã tự xác nhận lại
  điều này: thử lấy bằng chứng CI thật, sandbox vẫn không có Postgres/DSN,
  giữ nguyên `accepted_for_test`, không suy đoán đóng.
- **Phát hiện mới của audit này**: `.github/workflows/ci.yml` job `test`
  (dòng 33-52) **ĐÃ có** service `postgres:16` và đặt
  `QLKH_TEST_PG_DSN=postgresql://test:test@localhost:5432/qlkh_test` — nghĩa
  là trên CI thật (không phải sandbox agent), 15 test này **chạy thật, không
  skip**. Việc còn thiếu duy nhất là **bằng chứng job `test` đã chạy PASS
  trên CI thật** (agent không có tool trigger GitHub Actions — cùng giới hạn
  đã ghi trong `infra/QLKH/tck-cr-runtime-01-runtime-declaration.md`).
- **Việc cần làm tiếp** (không thuộc phạm vi ticket này, ghi rõ để không thất
  lạc): platform/release-engineer xác nhận job `test` PASS trên CI thật (dán
  link/log run cụ thể), sau đó chủ sở hữu `prd` (namespace `prd`) cập nhật
  `technical_debt_accepted[SD-25].status → closed`. Ticket này (TCK-CR-RUNTIME-07)
  **không** tự đóng SD-25 — không đủ thẩm quyền/bằng chứng để làm vậy.

## 2. `tests/devserver/test_healthz.py` — 2 điểm `pytest.skip()` có điều kiện

Trong `test_sha_matches_real_git_sha_of_running_build`:

- Dòng 115: `pytest.skip("git không sẵn có trong môi trường chạy test")` —
  kích hoạt nếu `git rev-parse HEAD` raise `OSError`/`SubprocessError`.
- Dòng 118: `pytest.skip("không lấy được git sha trong môi trường chạy test")`
  — kích hoạt nếu output rỗng.

- **Lý do**: guard phòng vệ môi trường (không có `git` hoặc không lấy được
  sha) — KHÔNG kích hoạt trong lần chạy test cục bộ của audit này (git sẵn
  có trong sandbox và trong CI vì `actions/checkout` clone đầy đủ).
- **Ticket/hạn trước khi audit**: **KHÔNG có** — đây là 2 điểm skip chưa
  từng được gắn ticket/hạn theo quy ước.
- **Quyết định (ruling, xem `rulings` trong PR)**: mở ticket mới để theo dõi
  thay vì để trống, đúng yêu cầu acceptance #2 của ticket này.
  → **TCK-QA-SKIP-HEALTHZ-01** (đề xuất, priority thấp, assignee platform,
  hạn 2026-09-20): xác nhận `git` luôn sẵn có trên mọi runner CI dùng
  `actions/checkout` (đã đúng theo cấu hình hiện tại của `ci.yml`) và cân
  nhắc bỏ hai nhánh `pytest.skip()` này (thay bằng `pytest.fail`) nếu xác
  nhận môi trường CI luôn có git — một skip không bao giờ kích hoạt thật ra
  che giấu khả năng test này không kiểm tra được gì khi có sự cố runner.
  Ticket này CHƯA được tạo trong topic `tasks` bởi agent này (namespace ghi
  được của platform chỉ có `infra`); đề nghị delivery-lead tạo ticket thật
  với id nêu trên ở lượt kế tiếp.

## Tổng kết đối chiếu acceptance

| # | Tiêu chí | Kết quả |
|---|---|---|
| 1 | Danh sách đầy đủ test skip kèm lý do/ticket/hạn | Đủ — mục 1 (15 test, SD-25) và mục 2 (2 điểm, ticket mới) |
| 2 | Test skip thiếu ticket/hạn đã có ticket mới mở | Mục 2 đã đề xuất TCK-QA-SKIP-HEALTHZ-01 (cần delivery-lead tạo thật trong `tasks`) |
| 3 | Báo cáo lưu tại `docs/QLKH/qa/skip-audit.md` | File này |

## Không nằm trong phạm vi ticket này

- Không tự đóng SD-25 (thuộc thẩm quyền namespace `prd`, cần bằng chứng CI
  thật mà agent không tạo được).
- Không xoá bất kỳ `skip`/`skipif` nào (đúng yêu cầu "không tự ý xoá skip
  nếu chưa rõ lý do" — cả hai nhóm skip ở đây đều đã rõ lý do).
- Không sửa `.github/workflows/ci.yml` (đã đúng cấu hình cho SD-25 từ trước,
  không cần đổi).

| version | ngày | thay đổi |
|---|---|---|
| 1 | 2026-09-06 | Khởi tạo audit: 15 test skip (SD-25, đã có ticket/điều kiện) + 2 điểm skip có điều kiện chưa có ticket (đề xuất TCK-QA-SKIP-HEALTHZ-01). |
