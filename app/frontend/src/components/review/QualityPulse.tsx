import {useResource} from '@/hooks/useResource';
import {formatDateTime} from '@/lib/format';
import {ReviewService} from '@/services/reviews';
import type {ReviewRunSummary} from '@/types/sqlReview';

const WEEK = 7 * 24 * 60 * 60 * 1000;
const BARS = 14;

/**
 * "Kalite nabzı": the user's last reviews at a glance — reviews and findings of the last seven
 * days, the share of runs that finished, and a bar per recent run sized by its findings.
 * Read from the user's own history; nothing new is stored.
 */
export function QualityPulse() {
  // The week is measured from when the history was read, not from each render.
  const runs = useResource('home:pulse', (signal) =>
    ReviewService.runs('mine', 1, 30, signal).then((page) => ({items: page.items, readAt: Date.now()})),
  );
  if (runs.data === undefined || runs.data.items.length === 0) return null;
  const {items, readAt: now} = runs.data;
  const week = items.filter((run) => now - new Date(run.started_at).getTime() <= WEEK);
  const weekFindings = week.reduce((sum, run) => sum + run.finding_count, 0);
  const finished = items.filter((run) => run.status === 'completed').length;
  const bars = items.slice(0, BARS).reverse();
  const highest = Math.max(1, ...bars.map((run) => run.finding_count));

  return (
    <section className="card pulse" aria-labelledby="pulse-title">
      <div className="card-header">
        <h2 id="pulse-title">Kalite nabzı</h2>
        <span className="subtle">son {items.length} inceleme</span>
      </div>
      <div className="card-body stack">
        <dl className="pulse-facts">
          <div>
            <dt>Bu hafta</dt>
            <dd className="tabular">{week.length}</dd>
            <span className="subtle">inceleme</span>
          </div>
          <div>
            <dt>Bulgu</dt>
            <dd className="tabular">{weekFindings}</dd>
            <span className="subtle">bu hafta</span>
          </div>
          <div>
            <dt>Tamamlanan</dt>
            <dd className="tabular">%{Math.round((finished / items.length) * 100)}</dd>
            <span className="subtle">son incelemeler</span>
          </div>
        </dl>
        <div className="pulse-chart" role="img" aria-label={chartLabel(bars)}>
          {bars.map((run) => (
            <span
              key={run.id}
              className={`pulse-bar is-${run.status}`}
              style={{height: `${Math.max(6, (run.finding_count / highest) * 100)}%`}}
              title={`${run.title} · ${formatDateTime(run.started_at)} · ${run.finding_count} bulgu`}
            />
          ))}
        </div>
        <p className="subtle pulse-legend">Her çubuk bir inceleme; yükseklik bulgu sayısı. Soldan sağa eskiden yeniye.</p>
      </div>
    </section>
  );
}

function chartLabel(bars: ReviewRunSummary[]): string {
  return `Son ${bars.length} incelemenin bulgu sayıları: ${bars.map((run) => run.finding_count).join(', ')}`;
}
