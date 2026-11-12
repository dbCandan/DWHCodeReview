import {useEffect, useMemo, useRef, useState} from 'react';
import {CircleAlert, CircleCheck, CircleDashed, LoaderCircle} from 'lucide-react';
import {cn} from '@/lib/utils';
import {formatDuration, formatNumber, OBJECT_STATUS_LABEL} from '@/lib/format';
import type {AnalysisDetail, AnalysisObject} from '@/types';
import {Card} from '@/components/ui/Card';
import {ProgressBar} from '@/components/ui/Progress';
import {TypeBadge} from '@/components/ui/Badge';
import {Tooltip} from '@/components/ui/Tooltip';

export function ObjectStatusIcon({status, className}: {status: AnalysisObject['status']; className?: string}) {
  switch (status) {
    case 'running':
      return <LoaderCircle className={cn('size-4 animate-spin text-accent', className)} />;
    case 'done':
      return <CircleCheck className={cn('size-4 text-ok', className)} />;
    case 'error':
      return <CircleAlert className={cn('size-4 text-bad', className)} />;
    default:
      return <CircleDashed className={cn('size-4 text-fg-subtle/60', className)} />;
  }
}

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [active]);
  return now;
}

/** Live "step-by-step" view of a running analysis: progress, ETA and the per-object step list. */
export function ExecutionPanel({analysis, onOpenObject}: {analysis: AnalysisDetail; onOpenObject: (o: AnalysisObject) => void}) {
  const active = analysis.status === 'queued' || analysis.status === 'running';
  const now = useNow(active);
  const listRef = useRef<HTMLUListElement>(null);
  const pct = analysis.total_checks ? (analysis.completed_checks / analysis.total_checks) * 100 : 0;
  const started = analysis.started_at ? new Date(analysis.started_at).getTime() : null;
  const elapsed = started ? now - started : null;
  const eta =
    elapsed && analysis.completed_checks > 0 && analysis.total_checks > analysis.completed_checks
      ? (elapsed / analysis.completed_checks) * (analysis.total_checks - analysis.completed_checks)
      : null;

  const counts = useMemo(() => {
    const c = {pending: 0, running: 0, done: 0, error: 0};
    for (const o of analysis.objects) c[o.status] += 1;
    return c;
  }, [analysis.objects]);
  const runningId = analysis.objects.find((o) => o.status === 'running')?.id;

  useEffect(() => {
    if (!runningId || !listRef.current) return;
    const el = listRef.current.querySelector<HTMLElement>(`[data-object="${runningId}"]`);
    const box = listRef.current;
    if (el) {
      const top = el.offsetTop;
      if (top < box.scrollTop || top > box.scrollTop + box.clientHeight - 40) {
        box.scrollTo({top: Math.max(0, top - box.clientHeight / 2), behavior: 'smooth'});
      }
    }
  }, [runningId]);

  return (
    <Card className="relative overflow-hidden">
      {active && <div className="hairline-top absolute inset-x-0 top-0 h-px" />}
      <div className="pointer-events-none absolute -top-24 left-1/3 h-48 w-1/2 rounded-full bg-accent/10 blur-3xl" />
      <div className="relative p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-medium text-fg-subtle">
              {analysis.status === 'queued' ? 'Sırada bekliyor…' : 'Kontroller adım adım işletiliyor'}
            </p>
            <p className="mt-1 text-[28px] leading-8 font-semibold tracking-tight text-fg tnum">
              %{Math.floor(pct)}
              <span className="ml-2 text-sm font-normal text-fg-subtle">
                {formatNumber(analysis.completed_checks)} / {formatNumber(analysis.total_checks)} kontrol
              </span>
            </p>
          </div>
          <div className="flex gap-5 text-right text-xs">
            <div>
              <p className="text-fg-subtle">Geçen süre</p>
              <p className="mt-0.5 font-medium text-fg tnum">{formatDuration(elapsed)}</p>
            </div>
            <div>
              <p className="text-fg-subtle">Tahmini kalan</p>
              <p className="mt-0.5 font-medium text-fg tnum">{eta !== null ? `~${formatDuration(eta)}` : '—'}</p>
            </div>
            <div>
              <p className="text-fg-subtle">Bulgu</p>
              <p className="mt-0.5 font-medium text-fg tnum">{formatNumber(analysis.finding_count)}</p>
            </div>
          </div>
        </div>
        <ProgressBar className="mt-4" value={analysis.completed_checks} max={analysis.total_checks || 1} active={active} size="lg" />
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-fg-subtle">
          <span className="flex items-center gap-1.5">
            <CircleCheck className="size-3.5 text-ok" /> {counts.done} tamamlandı
          </span>
          <span className="flex items-center gap-1.5">
            <LoaderCircle className="size-3.5 text-accent" /> {counts.running} işleniyor
          </span>
          <span className="flex items-center gap-1.5">
            <CircleDashed className="size-3.5" /> {counts.pending} bekliyor
          </span>
          {counts.error > 0 && (
            <span className="flex items-center gap-1.5 text-bad">
              <CircleAlert className="size-3.5" /> {counts.error} hata
            </span>
          )}
        </div>
      </div>
      <ul ref={listRef} className="relative max-h-80 overflow-y-auto border-t border-line p-2">
        {analysis.objects.map((o, i) => (
          <li key={o.id} data-object={o.id}>
            <button
              type="button"
              onClick={() => onOpenObject(o)}
              disabled={o.status === 'pending'}
              className={cn(
                'relative flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left transition-colors duration-300 disabled:cursor-default',
                o.status === 'running' ? 'bg-accent-soft' : 'hover:bg-surface-2/70',
              )}
            >
              <span className="w-8 shrink-0 text-right text-[11px] text-fg-subtle tnum">{i + 1}</span>
              <ObjectStatusIcon status={o.status} />
              <TypeBadge type={o.type} />
              <span className={cn('min-w-0 flex-1 truncate font-mono text-[12px]', o.status === 'pending' ? 'text-fg-subtle' : 'text-fg')}>
                {o.database}.{o.schema}.{o.name}
              </span>
              {o.status === 'error' ? (
                <Tooltip content={o.error}>
                  <span className="max-w-60 truncate text-[11.5px] text-bad">{o.error ?? 'Hata'}</span>
                </Tooltip>
              ) : o.status === 'done' ? (
                <span className={cn('text-[11.5px] tnum', o.finding_count ? 'font-medium text-warn' : 'text-fg-subtle')}>
                  {o.finding_count ? `${o.finding_count} bulgu` : 'temiz'}
                </span>
              ) : (
                <span className="text-[11.5px] text-fg-subtle">{OBJECT_STATUS_LABEL[o.status]}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
