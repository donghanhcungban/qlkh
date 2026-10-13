# Gợi ý nâng cấp — rà soát 2026-10-13

> Lấy từ đợt rà soát chéo 19 repo của chủ sở hữu (ma trận vệ sinh ở [seeker19110/stored, mục 23 §8.1](https://github.com/seeker19110/stored/blob/main/23-own-repos-lessons/README.md); gợi ý tích hợp ở §7b của cùng file). Số liệu đo bằng lệnh trên HEAD (đếm `uses:` ghim SHA 40 ký tự, khối `permissions:`, `dependabot.yml`, `.claude/settings.json`), không suy ra từ văn xuôi. Đây là **đề xuất**, chưa sửa code. Mỗi mục kèm bằng chứng để kiểm lại trước khi làm; mục nào đã xử lý thì đánh dấu hoặc xoá.

## Hiện trạng đo được

| HEAD đọc | Action ghim SHA | Workflow thiếu `permissions:` cấp đầu | Dependabot | LICENSE · SECURITY | File test |
|---|---|---|---|---|---|
| `16501bd` (2026-09-13) | 29/29 | – | **không có** | không · không | 52 |

## Đề xuất (🔴 cao · 🟠 trung bình · 🟢 nhẹ)

| # | Mức | Đề xuất | Bằng chứng | Kiểm xong khi |
|---|---|---|---|---|
| 1 | 🟠 | Thêm `.github/dependabot.yml` (pip, npm, github-actions) | Không có Dependabot; 29/29 action ghim SHA và có `ci/tool-checksums.txt`, nhưng không có bot thì SHA và checksum sẽ cũ dần | Dependabot mở PR đầu tiên |
| 2 | 🟢 | Thêm `LICENSE` và `SECURITY.md` | Repo không có cả hai file | Có file |

## Giữ nguyên (điểm mạnh)

- CI 14 job (OPA / conftest, syft SBOM, pip-audit, mutmut, import-linter, hash-lock), fitness function AST, ghim SHA 29/29.

## Gợi ý tích hợp từ catalog `stored`

- agent-scan hoặc Semgrep khi thêm skill / MCP (stored mục 12 §3d); badge CodeFlow card (mục 16 §2c).

## Ghi chú chung

- Ghim action theo SHA bằng [pinact](https://github.com/suzuki-shunsuke/pinact) hoặc [ratchet](https://github.com/sethvargo/ratchet), giữ comment tag (`# v7.0.1`), rồi để Dependabot `github-actions` tự nâng SHA. Đây là cách projects-template, xboss và Sales-Hunter đang làm.
- Chuẩn tham chiếu là `seeker19110/projects-template`: 25/25 action ghim SHA, mọi workflow có `permissions:` cấp đầu, Dependabot cho npm, github-actions và pip.
