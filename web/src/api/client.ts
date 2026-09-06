import { ApiError, type AttendanceBulkCreate, type Problem } from './types';

// Base URL: ưu tiên override qua biến môi trường build-time (VITE_API_BASE_URL).
// Không đặt fallback tuyệt đối cho bản build production (staging/CR-STAGE-001,
// TCK-CR-STAGE-001-04, ADR-0013 mục 4): web/dist được devserver phục vụ cùng
// origin tại '/', nên fallback production là đường dẫn TƯƠNG ĐỐI '/v1' — không
// cần cấu hình CORS ở staging. Bản dev (vite dev server, cổng khác devserver)
// vẫn cần origin tuyệt đối và đã có `.env.development` đặt tường minh; fallback
// dev ở đây chỉ dự phòng khi ai đó chạy thiếu file env, dùng đúng origin mặc
// định của devserver theo README.
const _env = (import.meta as unknown as { env?: Record<string, string | boolean> }).env ?? {};
const BASE_URL =
  (_env.VITE_API_BASE_URL as string | undefined) ??
  (_env.PROD ? '/v1' : 'http://127.0.0.1:8080/v1');

/**
 * Xử lý lỗi RFC 9457 (application/problem+json). Không suy diễn ngoài contract:
 * - 401: gọi onUnauthorized (điều hướng login) — caller quyết định hành vi UI.
 * - 403/429/422/404: ném ApiError để UI hiển thị thông điệp tương ứng.
 */
async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: 'include', // phiên máy chủ qua cookie HttpOnly (ADR-002)
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  });

  if (res.status === 204) {
    return undefined as T;
  }

  if (!res.ok) {
    let problem: Problem | undefined;
    try {
      problem = await res.json();
    } catch {
      problem = undefined;
    }
    let retryAfterSeconds: number | undefined;
    if (res.status === 429) {
      const header = res.headers.get('Retry-After');
      retryAfterSeconds = header ? Number(header) : undefined;
    }
    throw new ApiError(res.status, problem, retryAfterSeconds);
  }

  return (await res.json()) as T;
}

export const apiClient = {
  login(email: string, password: string) {
    return request<{ ok: true }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },
  listStudents() {
    return request<{ items: import('./types').Student[] }>('/students');
  },
  listStudentGrades(studentId: string) {
    return request<{ items: import('./types').Grade[] }>(`/students/${studentId}/grades`);
  },
  listAttendance(classId: string) {
    return request<{ items: unknown[] }>(`/classes/${classId}/attendance`);
  },
  bulkAttendance(classId: string, payload: AttendanceBulkCreate) {
    // Đúng scope: điểm danh cả lớp gửi MỘT request bulk, không lặp gọi từng học viên.
    return request<{ ok: true }>(`/classes/${classId}/attendance`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
};

export { ApiError };
