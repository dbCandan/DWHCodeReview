import type {ReactNode} from 'react';
import {Link} from 'react-router';
import {useQuery} from '@tanstack/react-query';
import {Ban, CalendarClock, CircleCheck, CircleX, GitCompare, LoaderCircle, SkipForward} from 'lucide-react';
import {api as apiClient} from '@/lib/api';
import {qk} from '@/hooks/queries';
import {buttonClass} from '@/components/ui/Button';
import {cn} from '@/lib/utils';
import {formatNumber} from '@/lib/format';
import {RUN_STATUS_LABEL} from '@/lib/schedules';
import {ApiError, errorMessage} from '@/lib/api';
import type {ScheduledRun} from '@/types';

const RUN_STYLE: Record<ScheduledRun['status'], {cls: string; icon: ReactNode}> = {
  running: {cls: 'bg-accent-soft text-accent ring-accent/30', icon: <LoaderCircle className="size-3 animate-spin" />},
  completed: {cls: 'bg-ok-soft text-ok ring-ok/30', icon: <CircleCheck className="size-3" />},
  skipped: {cls: 'bg-surface-3 text-fg-muted ring-line-strong', icon: <SkipForward className="size-3" />},
  failed: {cls: 'bg-bad-soft text-bad ring-bad/30', icon: <CircleX className="size-3" />},
};

export function RunStatusPill({status, className}: {status: ScheduledRun['status']; className?: string}) {
  const s = RUN_STYLE[status] ?? {cls: 'bg-surface-3 text-fg-muted ring-line-strong', icon: <Ban className="size-3" />};
  return (
    <span className={cn('inline-flex h-[22px] shrink-0 items-center gap-1.5 rounded-full px-2 text-[11.5px] font-medium whitespace-nowrap ring-1 ring-inset', s.cls, className)}>
      {s.icon}
      {RUN_STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** "+3 yeni · −1 çözülen" */
export function DiffCounts({newCount, resolvedCount, className}: {newCount: number; resolvedCount: number; className?: string}) {
  return (
    <span className={cn('inline-flex items-center gap-2 text-[12px] tnum', className)}>
      <span className={newCount ? 'font-semibold text-warn' : 'text-fg-subtle'}>+{formatNumber(newCount)} yeni</span>
      <span className={resolvedCount ? 'font-semibold text-ok' : 'text-fg-muted'}>−{formatNumber(resolvedCount)} çözülen</span>
    </span>
  );
}

export function scheduleError(e: unknown): Error {
  if (e instanceof ApiError && e.status === 404)
    return new Error(`${e.message} Zamanlanmış analiz uç noktaları sunucuda henüz yoksa backend güncellenmelidir.`);
  return new Error(errorMessage(e));
}

/** Hand-made SVG: finding count line + new/resolved bars for the last runs (oldest → newest). */
export function RunTrend({runs, height = 120}: {runs: ScheduledRun[]; height?: number}) {
  const data = runs.filter((r) => r.status === 'completed').slice(0, 20).reverse();
  if (data.length < 2)
    return <p className="px-4 py-8 text-center text-xs text-fg-subtle">Trend için en az iki tamamlanmış çalıştırma gerekir.</p>;
  const W = 600;
  const H = height;
  const pad = {l: 30, r: 8, t: 10, b: 18};
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const maxF = Math.max(1, ...data.map((r) => r.finding_count));
  const maxD = Math.max(1, ...data.map((r) => Math.max(r.new_count, r.resolved_count)));
  const step = iw / data.length;
  const x = (i: number) => pad.l + step * i + step / 2;
  const yF = (v: number) => pad.t + ih - (v / maxF) * ih;
  const bh = (v: number) => (v / maxD) * (ih * 0.45);
  const line = data.map((r, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${yF(r.finding_count).toFixed(1)}`).join(' ');
  const bw = Math.max(2, Math.min(10, step * 0.28));
  return (
    <figure className="px-4 pt-3 pb-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Son çalıştırmalarda bulgu sayısı ve yeni/çözülen bulgular">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={pad.l} x2={W - pad.r} y1={pad.t + ih * (1 - f)} y2={pad.t + ih * (1 - f)} stroke="var(--color-line)" />
            <text x={pad.l - 6} y={pad.t + ih * (1 - f) + 3} textAnchor="end" fontSize="9" fill="var(--color-fg-subtle)">
              {Math.round(maxF * f)}
            </text>
          </g>
        ))}
        {data.map((r, i) => (
          <g key={r.id}>
            <title>{`${new Date(r.started_at).toLocaleString('tr-TR')} — ${r.finding_count} bulgu, +${r.new_count} yeni, −${r.resolved_count} çözülen`}</title>
            <rect x={x(i) - bw - 1} y={pad.t + ih - bh(r.new_count)} width={bw} height={bh(r.new_count)} rx="1.5" fill="var(--color-warn)" opacity="0.85" />
            <rect x={x(i) + 1} y={pad.t + ih - bh(r.resolved_count)} width={bw} height={bh(r.resolved_count)} rx="1.5" fill="var(--color-ok)" opacity="0.85" />
          </g>
        ))}
        <path d={line} fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {data.map((r, i) => (
          <circle key={r.id} cx={x(i)} cy={yF(r.finding_count)} r="2.6" fill="var(--color-surface)" stroke="var(--color-accent)" strokeWidth="1.6" />
        ))}
      </svg>
      <figcaption className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-fg-muted">
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded bg-accent" /> Bulgu sayısı
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-sm bg-warn" /> Yeni
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-sm bg-ok" /> Çözülen
        </span>
        <span className="ml-auto text-fg-subtle">Son {data.length} tamamlanmış çalıştırma</span>
      </figcaption>
    </figure>
  );
}

/** Banner on the analysis detail page when the analysis came from a scheduled run. */
export function ScheduledAnalysisBanner({scheduleId, scheduleName, runId}: {scheduleId: number; scheduleName: string | null; runId: number | null}) {
  const runs = useQuery({queryKey: qk.scheduleRuns(scheduleId), queryFn: () => apiClient.schedules.runs(scheduleId, 50), retry: false, staleTime: 30_000});
  const run = runs.data?.find((r) => r.id === runId) ?? null;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-accent/30 bg-accent-soft px-4 py-2.5">
      <CalendarClock className="size-4 shrink-0 text-accent" />
      <p className="min-w-0 flex-1 text-[13px] text-fg">
        <span className="font-semibold">Zamanlanmış:</span> {scheduleName ?? `#${scheduleId}`}
        {run && run.status === 'completed' && (
          <>
            {' · '}
            <DiffCounts newCount={run.new_count} resolvedCount={run.resolved_count} />
          </>
        )}
        {run && run.status !== 'completed' && <span className="text-fg-muted"> · çalıştırma {RUN_STATUS_LABEL[run.status]?.toLowerCase()}</span>}
      </p>
      <Link to={`/schedules/${scheduleId}`} className={buttonClass('secondary', 'sm')}>
        <GitCompare className="size-3.5" /> Farkları gör
      </Link>
    </div>
  );
}
