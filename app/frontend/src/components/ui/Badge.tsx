import type {ReactNode} from 'react';
import {Ban, Blocks, CircleCheck, CircleX, Clock, LoaderCircle, Regex, Sparkles} from 'lucide-react';
import {cn} from '@/lib/utils';
import {SEVERITY_CLASS, SEVERITY_LABEL, SEVERITY_VAR} from '@/lib/severity';
import {OBJECT_TYPE_LABEL, OBJECT_TYPE_SHORT, RUN_STATUS_LABEL} from '@/lib/format';
import type {ObjectType, RuleKind, RunStatus, Severity} from '@/types';
import {Tooltip} from './Tooltip';

export type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'bad';

const TONE: Record<Tone, string> = {
  neutral: 'bg-surface-3/70 text-fg-muted ring-line-strong',
  accent: 'bg-accent-soft text-accent ring-accent/25',
  ok: 'bg-ok-soft text-ok ring-ok/25',
  warn: 'bg-warn-soft text-warn ring-warn/25',
  bad: 'bg-bad-soft text-bad ring-bad/25',
};

export function Badge({
  tone = 'neutral',
  children,
  className,
  icon,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  icon?: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-1.5 text-[11px] font-medium leading-none ring-1 ring-inset',
        TONE[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

export function SeverityDot({severity, className}: {severity: Severity; className?: string}) {
  return (
    <span
      className={cn('inline-block size-2 shrink-0 rounded-full', className)}
      style={{background: SEVERITY_VAR[severity], boxShadow: `0 0 0 3px color-mix(in srgb, ${SEVERITY_VAR[severity]} 18%, transparent)`}}
    />
  );
}

export function SeverityBadge({severity, className, compact}: {severity: Severity; className?: string; compact?: boolean}) {
  const c = SEVERITY_CLASS[severity];
  return (
    <span
      className={cn(
        'inline-flex h-5 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-1.5 text-[11px] font-semibold leading-none ring-1 ring-inset',
        c.soft,
        c.text,
        c.ring,
        className,
      )}
    >
      <span className={cn('size-1.5 rounded-full', c.bg)} />
      {!compact && SEVERITY_LABEL[severity]}
    </span>
  );
}

export function KindBadge({kind, compact}: {kind: RuleKind; compact?: boolean}) {
  if (kind === 'llm')
    return (
      <Badge
        tone="accent"
        title={compact ? 'LLM' : undefined}
        icon={<Sparkles className="size-3" />}
        className="bg-[linear-gradient(90deg,var(--color-accent-soft),color-mix(in_srgb,#c084fc_14%,transparent))]"
      >
        {!compact && 'LLM'}
      </Badge>
    );
  if (kind === 'builtin')
    return (
      <Badge title={compact ? 'Yerleşik' : undefined} icon={<Blocks className="size-3" />} className="bg-builtin-soft text-builtin ring-builtin/25">
        {!compact && 'Yerleşik'}
      </Badge>
    );
  return (
    <Badge title={compact ? 'Regex' : undefined} icon={<Regex className="size-3" />}>
      {!compact && 'Regex'}
    </Badge>
  );
}

export function TypeBadge({type, full}: {type: ObjectType; full?: boolean}) {
  return (
    <Tooltip content={OBJECT_TYPE_LABEL[type]} disabled={full}>
      <span className="inline-flex h-5 items-center rounded border border-line-strong bg-surface-2 px-1.5 font-mono text-[10.5px] font-medium text-fg-muted">
        {full ? OBJECT_TYPE_LABEL[type] : OBJECT_TYPE_SHORT[type]}
      </span>
    </Tooltip>
  );
}

const STATUS_STYLE: Record<RunStatus, {tone: string; icon: ReactNode}> = {
  queued: {tone: 'bg-surface-3/70 text-fg-muted ring-line-strong', icon: <Clock className="size-3" />},
  running: {tone: 'bg-accent-soft text-accent ring-accent/30', icon: <LoaderCircle className="size-3 animate-spin" />},
  completed: {tone: 'bg-ok-soft text-ok ring-ok/25', icon: <CircleCheck className="size-3" />},
  failed: {tone: 'bg-bad-soft text-bad ring-bad/25', icon: <CircleX className="size-3" />},
  cancelled: {tone: 'bg-warn-soft text-warn ring-warn/25', icon: <Ban className="size-3" />},
};

export function StatusPill({status, className}: {status: RunStatus; className?: string}) {
  const style = STATUS_STYLE[status] ?? STATUS_STYLE.queued;
  return (
    <span
      className={cn(
        'inline-flex h-[22px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-[11.5px] font-medium ring-1 ring-inset',
        style.tone,
        className,
      )}
    >
      {style.icon}
      {RUN_STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Kbd({children, className}: {children: ReactNode; className?: string}) {
  return (
    <kbd
      className={cn(
        'inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-line-strong bg-surface-2 px-1 font-sans text-[10.5px] font-medium text-fg-subtle shadow-[0_1px_0_var(--color-line-strong)]',
        className,
      )}
    >
      {children}
    </kbd>
  );
}

export function ColorDot({color, className}: {color: string; className?: string}) {
  return <span className={cn('inline-block size-2 shrink-0 rounded-full', className)} style={{background: color}} />;
}
