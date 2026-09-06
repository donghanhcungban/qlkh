import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ParentDashboard } from './ParentDashboard';
import { apiClient } from '../api/client';

vi.mock('../api/client', () => ({
  apiClient: { listStudents: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number) {
      super('err');
      this.status = status;
    }
  },
}));

describe('ParentDashboard', () => {
  beforeEach(() => vi.resetAllMocks());

  it('Given phụ huynh đăng nhập, When mở dashboard, Then chỉ thấy học viên liên kết với mình (dữ liệu server trả về, không lọc client)', async () => {
    (apiClient.listStudents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ id: 's1', full_name: 'Nguyễn Văn A' }],
    });
    render(<ParentDashboard />);
    await waitFor(() => expect(screen.getByText('Nguyễn Văn A')).toBeInTheDocument());
    // Không có logic lọc phía client: chỉ hiển thị đúng những gì API trả về.
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });
});
