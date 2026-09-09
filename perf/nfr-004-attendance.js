// perf/nfr-004-attendance.js — Kịch bản k6 cho NFR-004
// (điểm danh hàng loạt p95 < 1s @ 30 phiên đồng thời).
//
// Nguồn: PRD RISK-4 ("60 giáo viên cùng điểm danh trong 30 phút" → nghẽn đúng
// khung giờ quan trọng nhất), NFR-004, TCK-CR-RUNTIME-03 (CR-RUNTIME-NFR-001).
//
// Cách chạy (xem thêm README ở cuối file):
//
//   k6 run \
//     -e BASE_URL=http://<staging-host>:8080 \
//     -e TEACHER_EMAIL=teacher1@example.test \
//     -e TEACHER_PASSWORD=... \
//     -e CLASS_ID=<class-id-thật-trên-staging> \
//     -e STUDENT_IDS=stu-001,stu-002,stu-003 \
//     -e VUS=30 \
//     -e DURATION=30m \
//     perf/nfr-004-attendance.js
//
// Mỗi VU mô phỏng MỘT giáo viên: login một lần (dùng session cookie, đúng
// luồng thật theo qlkh/application/auth_http.py — POST /v1/auth/login trả
// 204 + Set-Cookie qlkh_session), sau đó lặp lại bulkAttendance
// (POST /v1/classes/{id}/attendance, body {entries:[...]}) trong suốt cửa sổ
// DURATION, có sleep ngẫu nhiên giữa các lần gọi để không đồng bộ hoá tải
// (tránh thundering herd giả tạo do chính script gây ra).
//
// Ngưỡng chặn (threshold) ánh xạ trực tiếp NFR-004: p95 < 1000ms cho riêng
// nhóm request bulkAttendance (tag `endpoint:bulk_attendance`), và tỉ lệ lỗi
// http < 1%.

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8080";
const TEACHER_EMAIL_PREFIX = __ENV.TEACHER_EMAIL_PREFIX || "teacher";
const TEACHER_EMAIL_DOMAIN = __ENV.TEACHER_EMAIL_DOMAIN || "example.test";
const TEACHER_EMAIL = __ENV.TEACHER_EMAIL || null; // nếu set: dùng chung 1 tài khoản cho mọi VU
const TEACHER_PASSWORD = __ENV.TEACHER_PASSWORD || "ChangeMe123!";
const CLASS_ID = __ENV.CLASS_ID || "class-nfr004-demo";
const STUDENT_IDS = (__ENV.STUDENT_IDS || "stu-001,stu-002,stu-003,stu-004,stu-005")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const VUS = parseInt(__ENV.VUS || "30", 10);
const DURATION = __ENV.DURATION || "30m";
const RAMP_UP = __ENV.RAMP_UP || "30s";
const RAMP_DOWN = __ENV.RAMP_DOWN || "30s";

export const bulkAttendanceDuration = new Trend("bulk_attendance_duration", true);
export const bulkAttendanceFailRate = new Rate("bulk_attendance_fail_rate");

export const options = {
  scenarios: {
    teachers_bulk_attendance: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: RAMP_UP, target: VUS },
        { duration: DURATION, target: VUS },
        { duration: RAMP_DOWN, target: 0 },
      ],
      gracefulRampDown: "10s",
    },
  },
  thresholds: {
    // NFR-004: p95 < 1s cho endpoint bulkAttendance — cổng chặn chính.
    "bulk_attendance_duration": ["p(95)<1000"],
    "bulk_attendance_fail_rate": ["rate<0.01"],
    // Ngưỡng bổ trợ trên toàn bộ HTTP để bắt các lỗi ngoài dự kiến (login...).
    "http_req_failed": ["rate<0.02"],
  },
};

function teacherEmailFor(vuId) {
  if (TEACHER_EMAIL) return TEACHER_EMAIL;
  return `${TEACHER_EMAIL_PREFIX}${vuId}@${TEACHER_EMAIL_DOMAIN}`;
}

function login(vuId) {
  const email = teacherEmailFor(vuId);
  const res = http.post(
    `${BASE_URL}/v1/auth/login`,
    JSON.stringify({ email, password: TEACHER_PASSWORD }),
    { headers: { "Content-Type": "application/json" }, tags: { endpoint: "login" } },
  );
  check(res, {
    "login trả 204": (r) => r.status === 204,
  });
  const setCookie = res.headers["Set-Cookie"];
  if (!setCookie) {
    return null;
  }
  // k6 tự quản cookie jar theo VU/iteration khi dùng http.cookieJar(); ở đây
  // chỉ cần đảm bảo request tiếp theo cùng VU sẽ mang cookie vừa nhận.
  return true;
}

function randomEntries() {
  const statuses = ["present", "absent", "late", "excused"];
  return STUDENT_IDS.map((subject_student_id) => ({
    subject_student_id,
    status: statuses[Math.floor(Math.random() * statuses.length)],
  }));
}

export default function () {
  const ok = login(__VU);
  if (!ok) {
    // Không login được thì không mô phỏng bulkAttendance vô nghĩa; ghi nhận
    // như một lần fail rồi thử lại ở iteration sau.
    bulkAttendanceFailRate.add(1);
    sleep(1);
    return;
  }

  const body = JSON.stringify({ entries: randomEntries() });
  const res = http.post(
    `${BASE_URL}/v1/classes/${CLASS_ID}/attendance`,
    body,
    { headers: { "Content-Type": "application/json" }, tags: { endpoint: "bulk_attendance" } },
  );

  bulkAttendanceDuration.add(res.timings.duration);
  const passed = check(res, {
    "bulkAttendance trả 201": (r) => r.status === 201,
  });
  bulkAttendanceFailRate.add(passed ? 0 : 1);

  // Giãn cách ngẫu nhiên 1-3s giữa các lần điểm danh của cùng một giáo viên,
  // mô phỏng nhịp thao tác thật thay vì spam liên tục.
  sleep(1 + Math.random() * 2);
}
