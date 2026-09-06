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
