import { useState, type FormEvent } from 'react';
import { apiClient, ApiError } from '../api/client';
import { ErrorBanner } from '../components/ErrorBanner';
import { t } from '../i18n/vi';

type Status = 'idle' | 'loading' | 'error' | 'success';

export function Login({ onSuccess }: { onSuccess?: () => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<unknown>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (status === 'loading') return; // chặn double-submit
    setStatus('loading');
    setError(null);
    try {
      await apiClient.login(email, password);
      setStatus('success');
      onSuccess?.();
    } catch (err) {
      setError(err);
      setStatus('error');
      // giữ nguyên email/password đã nhập để người dùng không phải gõ lại
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label={t('login.title')}>
      <h1>{t('login.title')}</h1>
      <label htmlFor="login-email">{t('login.email_label')}</label>
      <input
        id="login-email"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        aria-invalid={status === 'error'}
        disabled={status === 'loading'}
      />
      <label htmlFor="login-password">{t('login.password_label')}</label>
      <input
        id="login-password"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        aria-invalid={status === 'error'}
        disabled={status === 'loading'}
      />
      <button type="submit" disabled={status === 'loading'} aria-disabled={status === 'loading'}>
        {status === 'loading' ? t('common.loading') : t('login.submit')}
      </button>
      {status === 'error' && error instanceof ApiError && <ErrorBanner error={error} onRetry={() => setStatus('idle')} />}
    </form>
  );
}
