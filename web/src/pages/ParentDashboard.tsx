import { useEffect, useState } from 'react';
import { apiClient } from '../api/client';
import { ErrorBanner } from '../components/ErrorBanner';
import { t } from '../i18n/vi';
import type { Student } from '../api/types';

type State =
  | { kind: 'loading' }
  | { kind: 'error'; error: unknown }
  | { kind: 'empty' }
  | { kind: 'success'; students: Student[] };

/**
 * Danh sách học viên liên kết với phụ huynh. KHÔNG lọc ở client: dữ liệu trả về
 * từ /students đã được server áp SubjectContext (branch_id + quan hệ phụ huynh-học
 * viên) theo ADR-004 / P3. Client chỉ hiển thị nguyên trạng.
 */
export function ParentDashboard() {
  const [state, setState] = useState<State>({ kind: 'loading' });

  function load() {
    setState({ kind: 'loading' });
    apiClient
      .listStudents()
      .then((res) => {
        setState(res.items.length === 0 ? { kind: 'empty' } : { kind: 'success', students: res.items });
      })
      .catch((error) => setState({ kind: 'error', error }));
  }

  useEffect(load, []);

  return (
    <main>
      <h1>{t('parent_dashboard.title')}</h1>
      {state.kind === 'loading' && <p>{t('common.loading')}</p>}
      {state.kind === 'error' && <ErrorBanner error={state.error} onRetry={load} />}
      {state.kind === 'empty' && <p>{t('common.empty')}</p>}
      {state.kind === 'success' && (
        <ul>
          {state.students.map((s) => (
            <li key={s.id}>{s.full_name}</li>
          ))}
        </ul>
      )}
    </main>
  );
}
