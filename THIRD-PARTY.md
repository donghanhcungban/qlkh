# Phụ thuộc bên thứ ba (runtime)

Hồ sơ SPDX của mọi gói runtime trong `requirements.lock` (SD-04, SD-13). Nguồn định danh: trường
`license_expression` trong metadata PyPI của đúng phiên bản ghim, tra ngày 2026-09-05. Gói dev/CI
(ruff, mypy, pytest, semgrep, syft…) ghim trong `.github/workflows/ci.yml`, không nằm trong artifact
giao khách nên không liệt kê ở đây.

| Gói | Phiên bản | SPDX | Kéo vào bởi | Lý do |
|---|---|---|---|---|
| argon2-cffi | 25.1.0 | MIT | pyproject.toml | Băm mật khẩu argon2id (QLKH-004, REQ-001, NFR-001, ADR-002) |
| argon2-cffi-bindings | 26.1.0 | MIT | argon2-cffi | Binding C của thư viện tham chiếu argon2 |
| cffi | 2.1.1 | MIT-0 | argon2-cffi-bindings | Cầu C FFI (**MIT-0**, không phải MIT — không có nghĩa vụ ghi công) |
| pycparser | 3.0 | BSD-3-Clause | cffi | Bộ phân tích C dùng khi build binding |

Không gói nào thuộc họ bị cấm (GPL/AGPL/LGPL/SSPL/BUSL/CC-BY-NC — `tools/check_licenses.py`).

Cập nhật: thêm/đổi phụ thuộc → sửa `pyproject.toml`, sinh lại `requirements.lock`
(lệnh ở đầu file đó), rồi thêm dòng vào bảng này với SPDX tra từ PyPI. Cổng `license` trong CI
đọc SBOM CycloneDX do syft sinh; thiếu license hay license cấm là fail.
