# Kiểm thử hiệu năng QLKH — NFR-004

Ticket: TCK-CR-RUNTIME-03 (CR-RUNTIME-NFR-001). Yêu cầu: điểm danh hàng loạt
(`bulkAttendance`, `POST /v1/classes/{id}/attendance`) có p95 < 1s khi 30 giáo
viên gọi đồng thời trong cửa sổ ngắn (xem PRD RISK-4, NFR-004).

## Kịch bản

`perf/nfr-004-attendance.js` — [k6](https://k6.io/) (chọn k6 vì không cần cài
runtime nặng, chỉ cần một binary tĩnh; xem ghi chú trong ticket).

Mỗi VU (virtual user) mô phỏng một giáo viên: login một lần rồi lặp lại
`bulkAttendance` liên tục trong `DURATION`, có nghỉ ngẫu nhiên 1-3s giữa các
lần gọi.

## Yêu cầu trước khi chạy

1. Staging đã smoke-test OK (TCK-CR-RUNTIME-01/`infra/staging/wsl/smoke.sh`,
   `runtime.yaml`) — health `/healthz` trả 200.
2. Có sẵn trên staging: ≥ 30 tài khoản giáo viên hợp lệ (hoặc dùng chung 1 tài
   khoản qua `TEACHER_EMAIL` nếu staging cho phép nhiều phiên song song — xem
   cảnh báo bên dưới), một `class_id` thật giáo viên có quyền, và danh sách
   `subject_student_id` đã ghi danh vào lớp đó.
3. Cài k6: `https://k6.io/docs/get-started/installation/` (không có trong
   `requirements.lock` — đây là công cụ đo hiệu năng chạy ngoài, không phải
   dependency runtime của ứng dụng, cùng quy ước với mutmut/ruff/mypy đã dùng
   cho dev-tooling khác trong repo).

## Chạy

```bash
k6 run \
  -e BASE_URL=http://<staging-host>:8080 \
  -e TEACHER_EMAIL_PREFIX=teacher -e TEACHER_EMAIL_DOMAIN=example.test \
  -e TEACHER_PASSWORD='<mật khẩu thật lấy từ vault staging>' \
  -e CLASS_ID=<class-id-thật> \
  -e STUDENT_IDS=stu-001,stu-002,stu-003 \
  -e VUS=30 -e DURATION=30m \
  perf/nfr-004-attendance.js
```

Với `TEACHER_EMAIL_PREFIX`/`TEACHER_EMAIL_DOMAIN`, mỗi VU dùng một email khác
nhau (`teacher1@...`, `teacher2@...`, ...) — cần 30 tài khoản giáo viên có
thật tương ứng trên staging. Nếu chỉ có một tài khoản dùng thử, đặt
`TEACHER_EMAIL` cố định (kém đại diện hơn: không đo được overhead của 30
phiên đăng nhập độc lập, chỉ đo tải endpoint).

Chạy nhanh (khói, không phải chỉ số chính thức cho báo cáo NFR-004):

```bash
k6 run -e BASE_URL=http://127.0.0.1:8080 -e VUS=5 -e DURATION=1m perf/nfr-004-attendance.js
```

## Đọc kết quả

k6 in ra `bulk_attendance_duration` (p95) và threshold pass/fail ở cuối chạy.
Ngưỡng chặn khai trong script: `p(95)<1000` cho `bulk_attendance_duration`,
`rate<0.01` cho `bulk_attendance_fail_rate`.

Số liệu THẬT đo trên staging phải được dán nguyên văn (không làm tròn/chọn
lọc) vào `docs/QLKH/perf/nfr-004-report.md`. Nếu không đạt ngưỡng, ghi rõ
finding — không sửa số, không xoá lần chạy xấu.

## Giới hạn đã biết

Kịch bản này CHƯA được chạy thật trên staging trong lượt thực hiện
TCK-CR-RUNTIME-03 — xem `docs/QLKH/perf/nfr-004-report.md` để biết lý do và
việc còn lại cần ai làm.
