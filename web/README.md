# QLKH — web

Giao diện web (React + Vite + TypeScript) cho QLKH, theo `api/QLKH/openapi.yaml`.

## Chạy dev

Yêu cầu: đã cài `uv` (Python) và Node LTS.

1. Chạy devserver (ở thư mục gốc repo, cửa sổ terminal riêng):

   ```
   uv run python -m qlkh.devserver
   ```

   Mặc định devserver lắng nghe `http://127.0.0.1:8080` và cho phép CORS từ
   `http://localhost:5173` (đúng cổng Vite dev bên dưới).

2. Chạy web dev server (ở thư mục `web/`):

   ```
   npm run dev
   ```

   Mở `http://localhost:5173`. `web/.env.development` đã trỏ sẵn
   `VITE_API_BASE_URL=http://127.0.0.1:8080/v1` nên không cần cấu hình thêm.

Chỉ cần đúng 2 lệnh trên (mỗi lệnh một terminal) là dùng được.

## Tài khoản seed (devserver, KHÔNG PHẢI dữ liệu thật)

Devserver seed sẵn 3 tài khoản trong RAM (mất khi restart), dùng để đăng nhập thử:

| Vai trò  | Email                  | Mật khẩu          |
|----------|------------------------|--------------------|
| teacher  | `teacher1@qlkh.test`   | `Seed-Pass-123!`   |
| teacher  | `teacher2@qlkh.test`   | `Seed-Pass-123!`   |
| parent   | `parent1@qlkh.test`    | `Seed-Pass-123!`   |

Không có tài khoản `admin` trong seed (MFA chưa được nối dây cho devserver).
