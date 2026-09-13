# QLKH — Trung tâm Anh ngữ Sao Mai

Hệ thống quản lý khoá học: học viên, lớp, điểm danh, học phí, cổng phụ huynh.

## Quản lý phụ thuộc Python (khoá phiên bản)

`requirements.lock` là **nguồn khoá phiên bản chính thức duy nhất** của dự án
(ADR-0014, đóng nợ kiến trúc SD-13 — xem
`architecture/QLKH/adr/ADR-0014-debt-closure-sd13-def01-def03.md`). Không dùng
`uv.lock`/`uv sync --frozen` trong CI hay deploy.

Quy trình khi đổi dependency:

1. Sửa `dependencies` trong `pyproject.toml`.
2. Sinh lại lockfile:

   ```bash
   uv pip compile pyproject.toml --generate-hashes --python-version 3.12 -o requirements.lock
   ```

3. Commit cả `pyproject.toml` và `requirements.lock` trong CÙNG một PR.

CI (`.github/workflows/ci.yml`):

- job `test` cài dependency bằng `pip install --require-hashes -r
  requirements.lock` — thiếu hash hoặc hash sai thì fail ngay (chuỗi cung ứng,
  T-12).
- job `lock-check` sinh lại `requirements.lock` từ `pyproject.toml` bằng đúng
  lệnh ở bước 2 rồi `diff` với bản đã commit — quên chạy lại lệnh trên sau khi
  đổi dependency thì PR fail rõ ràng, không lặng lẽ merge một lockfile lệch.

`infra/staging/wsl/deploy.sh` dùng lại đúng cơ chế này (`pip install
--require-hashes -r requirements.lock` vào một virtualenv riêng), không cài
qua `uv sync` — staging và CI không lệch cơ chế cài dependency.

## Mutation testing (mutmut)

TCK-CR-RUNTIME-05 (CR-RUNTIME-NFR-001, risk_tags=[pii]): mutation testing thật
cho luồng xoá dữ liệu chủ thể ND13 (`qlkh/application/erasure_http.py`,
`POST /erasure-requests`) và luồng ghi danh (`qlkh/application/class_service.py`
+ `qlkh/application/class_http.py`). Phạm vi khai ở `pyproject.toml`
(`[tool.mutmut]`).

Chạy cục bộ:

```bash
pip install mutmut==3.2.2 pyyaml==6.0.2 pytest==8.3.3
mutmut run
mutmut results   # bảng mutant: killed / survived / timeout / suspicious
mutmut html      # báo cáo HTML chi tiết từng mutant sống sót
```

Ngưỡng yêu cầu (CR-RUNTIME-NFR-001): mutation score **>= 70%** cho cả hai
phạm vi (`erasure_http.py` và enrollment). Mutant sống sót (`survived`) nghĩa
là có nhánh logic không được test nào phát hiện khi bị đột biến — bổ sung test
theo đúng ADR-0028 (test-author sở hữu vùng test; backend chỉ mở
`test_dispute` nếu cho rằng test sai đặc tả, không tự sửa test).

CI job `mutation` chạy đúng lệnh trên trong GitHub Actions (nơi có quyền
`pip install` tuỳ ý). Job này hiện đặt `continue-on-error: true` vì lần chạy
CI thật đầu tiên chưa được platform/release-engineer xác nhận đạt ngưỡng —
xem chú thích trong `.github/workflows/ci.yml` job `mutation` và mục 38
`security/QLKH/threat-model.md`. **Việc còn nợ**: sau khi CI chạy thật lần
đầu và xác nhận cả hai phạm vi >= 70%, gỡ `continue-on-error` để job trở
thành cổng chặn cứng; nếu <70%, mở ticket bổ sung test trước khi gỡ.

Dev-tool `mutmut`/`pyyaml`/`pytest` cài riêng trong job CI, không đưa vào
`requirements.lock`/`dependencies` của ứng dụng — cùng quy ước với
ruff/mypy/import-linter/pip-audit ở các job khác.
