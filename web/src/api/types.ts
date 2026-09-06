// Kiểu dữ liệu tối thiểu khớp api/QLKH/openapi.yaml (v1.4.1). Không thêm field ngoài contract.

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  errors?: { field?: string; message?: string }[];
}

export interface Student {
  id: string;
  full_name: string;
  branch_id?: string;
}

export interface Grade {
  student_id: string;
  score: number;
  reason?: string;
}

export type AttendanceStatus = 'present' | 'absent' | 'late' | 'excused';

export interface AttendanceEntry {
  student_id: string;
  status: AttendanceStatus;
}

export interface AttendanceBulkCreate {
  entries: AttendanceEntry[];
}

export class ApiError extends Error {
  status: number;
  problem?: Problem;
  retryAfterSeconds?: number;

  constructor(status: number, problem?: Problem, retryAfterSeconds?: number) {
    super(problem?.title ?? `HTTP ${status}`);
    this.status = status;
    this.problem = problem;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}
