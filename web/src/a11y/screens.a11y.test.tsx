import { describe, it, expect, afterAll } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import axe from 'axe-core';
import type { AxeResults, Result } from 'axe-core';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { Login } from '../pages/Login';
import { ParentDashboard } from '../pages/ParentDashboard';
import { TeacherDashboard } from '../pages/TeacherDashboard';
import { ErrorBanner } from '../components/ErrorBanner';
import { ApiError } from '../api/client';
import type { Student } from '../api/types';

/**
 * Kịch bản a11y (axe-core) cho 3 màn hình chính đã cam kết trong scope của
 * CR-RUNTIME-NFR-001 / TCK-CR-RUNTIME-04: đăng nhập, danh sách học viên
 * (ParentDashboard), điểm danh (TeacherDashboard).
 *
 * Cách chạy (đọc thêm README):
 *   cd web && npm run a11y
 *
 * GIỚI HẠN MÔI TRƯỜNG (nêu rõ, không giấu):
 * axe-core ở đây chạy trên DOM do jsdom dựng trong tiến trình vitest — KHÔNG
 * phải trình duyệt thật. jsdom không tính layout/CSS thật nên các rule phụ
 * thuộc render trực quan (`color-contrast`, kích thước target thật, v.v.)
 * không chạy được đáng tin cậy và axe-core sẽ liệt các rule đó vào
 * `incomplete` thay vì pass giả. Bộ test này phủ được: ngữ nghĩa HTML,
 * name/role/value, nhãn form, landmark, live region, thứ tự heading — không
 * phủ được contrast màu thật hay kích thước target theo pixel màn hình thật.
 * Muốn phủ đủ WCAG 2.2 AA (bao gồm contrast) cần chạy thêm bằng trình duyệt
 * thật (Lighthouse CI / Playwright + axe) — công cụ đó NGOÀI phạm vi bộ test
 * này vì môi trường thực thi hiện tại không có trình duyệt/mạng.
 *
 * Báo cáo: mỗi lần chạy ghi đè `docs/QLKH/a11y/report.md` với số liệu THẬT
 * (đếm violations theo severity) của lần chạy đó — không phải số liệu ước
 * lượng hay số liệu cũ giữ lại.
 */

type Severity = 'critical' | 'serious' | 'moderate' | 'minor';

interface ScreenReport {
  screen: string;
  state: string;
  violations: Result[];
  incompleteCount: number;
}

const reports: ScreenReport[] = [];

async function scan(container: HTMLElement, screen: string, state: string): Promise<AxeResults> {
  const results = await axe.run(container);
  reports.push({ screen, state, violations: results.violations, incompleteCount: results.incomplete.length });
  return results;
}

function countBySeverity(violations: Result[]): Record<Severity, number> {
  const out = { critical: 0, serious: 0, moderate: 0, minor: 0 } as Record<Severity, number>;
  for (const v of violations) {
    const impact = (v.impact ?? 'minor') as Severity;
    out[impact] = (out[impact] ?? 0) + 1;
  }
  return out;
}

function expectNoHighSeverity(violations: Result[]) {
  const counts = countBySeverity(violations);
  const detail = JSON.stringify(
    violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help })),
    null,
    2,
  );
  // Vi phạm critical/serious phải chặn (skill accessibility: "0 lỗi
  // critical/serious" là điều kiện cần) — không tự ý bỏ qua.
  expect(counts.critical, `critical violations:\n${detail}`).toBe(0);
  expect(counts.serious, `serious violations:\n${detail}`).toBe(0);
}

const students: Student[] = [
  { id: 's1', full_name: 'Nguyễn Văn A' },
  { id: 's2', full_name: 'Trần Thị B' },
];

describe('a11y: đăng nhập (Login)', () => {
  it('trạng thái mặc định', async () => {
    const { container } = render(<Login />);
    const results = await scan(container, 'login', 'default');
    expectNoHighSeverity(results.violations);
  });
});

describe('a11y: danh sách học viên (ParentDashboard)', () => {
  it('trạng thái loading', async () => {
    const { container } = render(<ParentDashboard />);
    const results = await scan(container, 'parent_dashboard', 'loading');
    expectNoHighSeverity(results.violations);
  });

  it('trạng thái lỗi', async () => {
    const error = new ApiError(429, undefined, 30);
    const { container } = render(
      <main>
        <h1>Học viên của bạn</h1>
        <ErrorBanner error={error} onRetry={() => {}} />
      </main>,
    );
    const results = await scan(container, 'parent_dashboard', 'error');
    expectNoHighSeverity(results.violations);
  });
});

describe('a11y: điểm danh (TeacherDashboard)', () => {
  it('trạng thái success (danh sách học viên)', async () => {
    const { container } = render(<TeacherDashboard classId="c1" students={students} />);
    const results = await scan(container, 'teacher_dashboard_attendance', 'success');
    expectNoHighSeverity(results.violations);
  });
});

afterAll(() => {
  cleanup();
  const lines: string[] = [];
  lines.push('# Báo cáo a11y (axe-core, jsdom) — QLKH web');
  lines.push('');
  lines.push('Tự động sinh bởi `web/src/a11y/screens.a11y.test.tsx` mỗi lần chạy `npm run a11y`.');
  lines.push('Số liệu dưới đây là kết quả THẬT của lần chạy gần nhất — không phải ước lượng.');
  lines.push('');
  lines.push(
    '> Giới hạn: chạy trên jsdom, không phải trình duyệt thật — không phủ được rule `color-contrast` ' +
      'và kích thước target theo pixel thật. Xem chú thích đầu file test.',
  );
  lines.push('');
  lines.push('| Màn hình | Trạng thái | critical | serious | moderate | minor | incomplete |');
  lines.push('|---|---|---|---|---|---|---|');
  for (const r of reports) {
    const c = countBySeverity(r.violations);
    lines.push(
      `| ${r.screen} | ${r.state} | ${c.critical} | ${c.serious} | ${c.moderate} | ${c.minor} | ${r.incompleteCount} |`,
    );
  }
  lines.push('');
  const anyViolations = reports.some((r) => r.violations.length > 0);
  if (anyViolations) {
    lines.push('## Chi tiết vi phạm');
    for (const r of reports) {
      if (r.violations.length === 0) continue;
      lines.push(`### ${r.screen} — ${r.state}`);
      for (const v of r.violations) {
        lines.push(`- **${v.id}** (${v.impact ?? 'unknown'}, ${v.nodes.length} node) — ${v.help}`);
      }
      lines.push('');
    }
  } else {
    lines.push('Không có vi phạm nào (mọi mức) trên các màn hình/trạng thái đã kiểm.');
  }

  const outPath = resolve(__dirname, '../../../docs/QLKH/a11y/report.md');
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, lines.join('\n') + '\n', 'utf-8');
});
