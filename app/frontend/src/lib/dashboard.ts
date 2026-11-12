import type {AnalysisSummary} from '@/types';

/** Last `n` completed analyses, oldest → newest (for the trend chart). */
export function trendAnalyses(list: AnalysisSummary[] | null | undefined, n = 12): AnalysisSummary[] {
  const done = (list ?? []).filter((a) => a.status === 'completed');
  const time = (a: AnalysisSummary) => new Date(a.finished_at ?? a.created_at).getTime();
  return done.sort((a, b) => time(a) - time(b)).slice(-n);
}

/** "Nice" y-axis ticks from 0 to ≥ max (e.g. 0, 2.000, 4.000, 6.000). */
export function niceTicks(max: number, count = 4): number[] {
  if (!(max > 0)) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const top = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top + step / 2; v += step) ticks.push(Math.round(v * 1000) / 1000);
  return ticks;
}

/** "google/gemma-4-31b" → "gemma-4-31b" */
export function shortModelName(model: string | null | undefined): string {
  const m = (model ?? '').trim();
  if (!m) return '—';
  return m.split('/').pop() || m;
}
