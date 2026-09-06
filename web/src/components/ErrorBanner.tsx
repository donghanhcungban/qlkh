import { ApiError } from '../api/client';
import { t } from '../i18n/vi';

/**
 * Hiển thị lỗi thân thiện theo mã HTTP (RFC 9457). Không lộ chi tiết kỹ thuật.
 * 401 nên được xử lý ở tầng điều hướng (redirect login) trước khi tới đây;
 * component này bao quát trường hợp còn hiển thị inline.
 */
export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;

  let message = t('common.error_unknown');
  if (error instanceof ApiError) {
    if (error.status === 401) message = t('common.error_401');
    else if (error.status === 403) message = t('common.error_403');
    else if (error.status === 429) {
      message = t('common.error_429', { seconds: error.retryAfterSeconds ?? 60 });
    } else if (error.problem?.detail) {
      message = error.problem.detail;
    }
  }

  return (
    <div role="alert" aria-live="assertive">
      <p>{message}</p>
      {onRetry && <button type="button" onClick={onRetry}>{t('common.retry')}</button>}
    </div>
  );
}
