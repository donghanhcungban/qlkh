import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TeacherDashboard } from './TeacherDashboard';
import { apiClient } from '../api/client';
import type { Student } from '../api/types';

vi.mock('../api/client', () => ({
  apiClient: { bulkAttendance: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number) {
      super('err');
      this.status = status;
    }
  },
}));

describe('TeacherDashboard', () => {
  beforeEach(() => vi.resetAllMocks());

  it('Given giáo viên mở màn điểm danh lớp, When đánh dấu 30 học viên, Then gửi một request bulk', async () => {
    const students: Student[] = Array.from({ length: 30 }, (_, i) => ({
      id: `s${i}`,
      full_name: `HV ${i}`,
    }));
    (apiClient.bulkAttendance as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true });

    render(<TeacherDashboard classId="c1" students={students} />);

    students.forEach((s) => {
      const radios = screen.getAllByRole('radio', { name: 'Có mặt' });
      const idx = students.indexOf(s);
      fireEvent.click(radios[idx]);
    });

    fireEvent.click(screen.getByRole('button', { name: 'Gửi điểm danh' }));

    await waitFor(() => expect(apiClient.bulkAttendance).toHaveBeenCalledTimes(1));
    const [classId, payload] = (apiClient.bulkAttendance as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(classId).toBe('c1');
    expect(payload.entries).toHaveLength(30);
  });
});
