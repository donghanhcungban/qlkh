import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ErrorBanner } from './ErrorBanner';
import { ApiError } from '../api/client';

describe('ErrorBanner', () => {
  it('Given API trả 429, When người dùng thao tác, Then hiện thông báo chờ theo Retry-After', () => {
    const error = new ApiError(429, undefined, 42);
    render(<ErrorBanner error={error} />);
    expect(screen.getByRole('alert')).toHaveTextContent('42 giây');
  });
});
