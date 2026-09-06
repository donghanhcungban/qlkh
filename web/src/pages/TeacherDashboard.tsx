import { useState } from 'react';
import { apiClient } from '../api/client';
import { ErrorBanner } from '../components/ErrorBanner';
import { t } from '../i18n/vi';
import type { AttendanceEntry, AttendanceStatus, Student } from '../api/types';

type SubmitState = 'idle' | 'loading' | 'error' | 'success';

/**
 * Điểm danh lớp: đánh dấu N học viên tại chỗ (state cục bộ), rồi gửi MỘT
 * request bulk duy nhất khi bấm submit (khớp NFR-004 và acceptance ticket).
 * Ẩn/hiện nút chỉ là trải nghiệm; quyền thật do server trả 403 nếu vượt phạm vi.
 */
export function TeacherDashboard({ classId, students }: { classId: string; students: Student[] }) {
  const [marks, setMarks] = useState<Record<string, AttendanceStatus>>({});
  const [submitState, setSubmitState] = useState<SubmitState>('idle');
  const [error, setError] = useState<unknown>(null);

  function setMark(studentId: string, status: AttendanceStatus) {
    setMarks((prev) => ({ ...prev, [studentId]: status }));
  }

  async function handleSubmit() {
    if (submitState === 'loading') return; // chặn double-submit
    const entries: AttendanceEntry[] = Object.entries(marks).map(([student_id, status]) => ({
      student_id,
      status,
    }));
    setSubmitState('loading');
    setError(null);
    try {
      await apiClient.bulkAttendance(classId, { entries });
      setSubmitState('success');
    } catch (err) {
      setError(err);
      setSubmitState('error');
      // giữ nguyên `marks` để giáo viên không phải đánh dấu lại
    }
  }

  return (
    <main>
      <h1>{t('teacher_dashboard.title')}</h1>
      <ul>
        {students.map((s) => (
          <li key={s.id}>
            <span>{s.full_name}</span>
            <label>
              <input
                type="radio"
                name={`status-${s.id}`}
                checked={marks[s.id] === 'present'}
                onChange={() => setMark(s.id, 'present')}
              />
              {t('teacher_dashboard.status_present')}
            </label>
            <label>
              <input
                type="radio"
                name={`status-${s.id}`}
                checked={marks[s.id] === 'absent'}
                onChange={() => setMark(s.id, 'absent')}
              />
              {t('teacher_dashboard.status_absent')}
            </label>
            <label>
              <input
                type="radio"
                name={`status-${s.id}`}
                checked={marks[s.id] === 'late'}
                onChange={() => setMark(s.id, 'late')}
              />
              {t('teacher_dashboard.status_late')}
            </label>
            <label>
              <input
                type="radio"
                name={`status-${s.id}`}
                checked={marks[s.id] === 'excused'}
                onChange={() => setMark(s.id, 'excused')}
              />
              {t('teacher_dashboard.status_excused')}
            </label>
          </li>
        ))}
      </ul>
      <button type="button" onClick={handleSubmit} disabled={submitState === 'loading'}>
        {submitState === 'loading' ? t('common.loading') : t('teacher_dashboard.submit_attendance')}
      </button>
      {submitState === 'error' && <ErrorBanner error={error} onRetry={handleSubmit} />}
      {submitState === 'success' && <p role="status">{t('teacher_dashboard.submit_success')}</p>}
    </main>
  );
}
