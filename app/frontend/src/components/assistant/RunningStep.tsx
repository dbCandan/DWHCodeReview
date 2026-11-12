import {useEffect, useRef} from 'react';
import {Ban, Check, CircleSlash, LoaderCircle, RotateCcw, Square, X} from 'lucide-react';
import {cn} from '@/lib/utils';
import {formatTime} from '@/lib/format';
import {STAGE_LABEL, TIMELINE, timelineStates, type StepState} from '@/lib/assistant';
import type {AssistantSession} from '@/types';
import {Card, CardHeader} from '@/components/ui/Card';
import {Button} from '@/components/ui/Button';
import {Alert} from '@/components/ui/Feedback';

function StepIcon({state}: {state: StepState}) {
  const base = 'flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold';
  if (state === 'done') return <span className={cn(base, 'border-accent-solid bg-accent-solid text-white')}><Check className="size-3.5" strokeWidth={3} /></span>;
  if (state === 'active')
    return (
      <span className={cn(base, 'border-accent bg-accent-soft text-accent shadow-[0_0_0_4px_var(--color-accent-soft)]')}>
        <LoaderCircle className="size-3.5 animate-spin" />
      </span>
    );
  if (state === 'failed') return <span className={cn(base, 'border-bad bg-bad-soft text-bad')}><X className="size-3.5" strokeWidth={3} /></span>;
  if (state === 'skipped') return <span className={cn(base, 'border-dashed border-line-control text-fg-subtle')}><CircleSlash className="size-3.5" /></span>;
  return <span className={cn(base, 'border-line-control bg-surface-2 text-fg-subtle')} />;
}

/** Iteration n of the validating ↔ refining loop (max 3). */
function roundOf(session: AssistantSession): number {
  const refines = session.log.filter((l) => l.stage === 'refining').length;
  return Math.min(3, Math.max(session.validation?.iterations ?? 0, refines + 1, 1));
}

export function StageTimeline({session}: {session: AssistantSession}) {
  const states = timelineStates(session);
  return (
    <ol className="grid gap-3 sm:grid-cols-5">
      {TIMELINE.map((t, i) => {
        const state = states[i];
        const sub =
          t.key === 'validating' && (state === 'active' || state === 'done' || state === 'failed')
            ? `tur ${roundOf(session)}/3${session.stage === 'refining' && state === 'active' ? ' · düzeltiliyor' : ''}`
            : state === 'skipped'
              ? 'atlandı'
              : state === 'active'
                ? 'çalışıyor…'
                : state === 'failed'
                  ? session.status === 'cancelled'
                    ? 'iptal edildi'
                    : 'başarısız'
                  : null;
        return (
          <li key={t.key} className="flex items-center gap-2.5 sm:flex-col sm:items-start">
            <div className="flex w-full items-center gap-2">
              <StepIcon state={state} />
              {i < TIMELINE.length - 1 && <span className={cn('hidden h-px flex-1 sm:block', state === 'done' || state === 'skipped' ? 'bg-accent' : 'bg-line-strong')} />}
            </div>
            <div className="min-w-0">
              <p className={cn('text-[13px] font-medium', state === 'pending' ? 'text-fg-subtle' : 'text-fg')}>{t.label}</p>
              {sub && <p className={cn('text-[11.5px]', state === 'failed' ? 'text-bad' : 'text-fg-subtle')}>{sub}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function RunningStep({
  session,
  onCancel,
  cancelling,
  onRestart,
}: {
  session: AssistantSession;
  onCancel: () => void;
  cancelling: boolean;
  onRestart: () => void;
}) {
  const logRef = useRef<HTMLOListElement>(null);
  const log = session.log ?? [];
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log.length]);
  const running = session.status === 'running';

  return (
    <div className="flex flex-col gap-4">
      <Card className="p-4">
        <StageTimeline session={session} />
      </Card>
      {session.status === 'failed' && (
        <Alert
          tone="bad"
          title="Asistan tamamlanamadı"
          action={
            <Button size="sm" icon={<RotateCcw className="size-3.5" />} onClick={onRestart}>
              Tanımı düzenle ve yeniden başlat
            </Button>
          }
        >
          {session.error || 'Bilinmeyen hata.'}
        </Alert>
      )}
      {session.status === 'cancelled' && (
        <Alert
          tone="warn"
          title="Oturum iptal edildi"
          action={
            <Button size="sm" icon={<RotateCcw className="size-3.5" />} onClick={onRestart}>
              Tanımı düzenle ve yeniden başlat
            </Button>
          }
        />
      )}
      <Card className="overflow-hidden">
        <CardHeader
          title="Canlı günlük"
          description={running ? `Şu an: ${STAGE_LABEL[session.stage]}. Sayfa 1,5 sn’de bir güncellenir.` : undefined}
          actions={
            running && (
              <Button size="sm" variant="danger" loading={cancelling} icon={<Square className="size-3 fill-current" />} onClick={onCancel}>
                İptal et
              </Button>
            )
          }
        />
        <ol ref={logRef} className="max-h-80 overflow-y-auto bg-canvas/40 p-3 font-mono text-[12px] leading-5">
          {log.length === 0 && <li className="text-fg-subtle">Bekleniyor…</li>}
          {log.map((l, i) => (
            <li key={i} className="flex gap-3">
              <span className="shrink-0 text-fg-subtle tnum">{formatTime(l.at)}</span>
              <span className="w-24 shrink-0 text-accent">{STAGE_LABEL[l.stage] ?? l.stage}</span>
              <span className="min-w-0 break-words text-fg">{l.message}</span>
            </li>
          ))}
          {running && (
            <li className="flex items-center gap-2 text-fg-subtle">
              <LoaderCircle className="size-3 animate-spin" /> çalışıyor…
            </li>
          )}
          {session.status === 'cancelled' && (
            <li className="flex items-center gap-2 text-warn">
              <Ban className="size-3" /> iptal edildi
            </li>
          )}
        </ol>
      </Card>
    </div>
  );
}
