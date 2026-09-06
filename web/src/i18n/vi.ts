// Bảng dịch tiếng Việt (locale mặc định). Mọi chuỗi hiển thị phải qua đây (ADR i18n).
export const vi = {
  login: {
    title: 'Đăng nhập',
    email_label: 'Email',
    password_label: 'Mật khẩu',
    submit: 'Đăng nhập',
    error_generic: 'Đăng nhập thất bại. Kiểm tra lại thông tin.',
  },
  common: {
    loading: 'Đang tải…',
    empty: 'Không có dữ liệu.',
    error_401: 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.',
    error_403: 'Bạn không có quyền thực hiện thao tác này.',
    error_429: 'Hệ thống đang bận, thử lại sau {seconds} giây.',
    error_unknown: 'Có lỗi xảy ra. Vui lòng thử lại.',
    retry: 'Thử lại',
  },
  parent_dashboard: {
    title: 'Học viên của bạn',
    grades_link: 'Xem điểm',
  },
  teacher_dashboard: {
    title: 'Lớp phụ trách — điểm danh',
    submit_attendance: 'Gửi điểm danh',
    status_present: 'Có mặt',
    status_absent: 'Vắng',
    status_late: 'Trễ',
    status_excused: 'Có phép',
    submit_success: 'Đã gửi điểm danh thành công.',
  },
} as const;

export type MessageKey = string;

/**
 * ICU tối giản: hỗ trợ thay thế {name}. Đủ dùng cho các thông điệp hiện có;
 * mở rộng sang ICU đầy đủ (số nhiều/giới tính) khi có nhu cầu thật.
 */
export function t(path: string, params?: Record<string, string | number>): string {
  const value = path.split('.').reduce<unknown>((acc, key) => {
    if (acc && typeof acc === 'object' && key in (acc as Record<string, unknown>)) {
      return (acc as Record<string, unknown>)[key];
    }
    return undefined;
  }, vi);
  let text = typeof value === 'string' ? value : path;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(`{${k}}`, String(v));
    }
  }
  return text;
}
