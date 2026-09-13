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

## Kiểm tra khả năng tiếp cận (a11y)

Lệnh:

```
cd web
npm install   # lần đầu, nếu chưa có node_modules
npm run a11y
```

Chạy `axe-core` trên DOM do `jsdom` dựng (trong tiến trình `vitest`, không cần
trình duyệt thật) cho 3 màn hình chính đã cam kết trong scope
(CR-RUNTIME-NFR-001 / TCK-CR-RUNTIME-04): đăng nhập, danh sách học viên
(`ParentDashboard`), điểm danh (`TeacherDashboard`). Xem chi tiết ở
`src/a11y/screens.a11y.test.tsx`.

Test **fail** nếu có bất kỳ vi phạm mức `critical` hoặc `serious` — đây là
finding chặn, không được bỏ qua. Mức `moderate`/`minor` không chặn test nhưng
vẫn được ghi vào báo cáo.

Mỗi lần chạy ghi đè `docs/QLKH/a11y/report.md` bằng số liệu THẬT của lần chạy
đó (số violation theo mức nghiêm trọng, cho từng màn hình/trạng thái).

**Giới hạn đã biết**: `jsdom` không dựng layout/CSS thật nên axe-core không
chạy được đáng tin cậy các rule phụ thuộc render trực quan (`color-contrast`,
kích thước target theo pixel màn hình thật) — axe-core liệt các rule đó vào
`incomplete` thay vì báo pass giả. Muốn phủ đủ WCAG 2.2 AA (bao gồm contrast)
cần thêm một vòng kiểm bằng trình duyệt thật (Lighthouse CI hoặc
Playwright + axe) chạy trong CI có mạng/trình duyệt — hiện CHƯA có bước đó
trong repo này; đây là việc còn thiếu, không phải đã làm và giấu đi.
