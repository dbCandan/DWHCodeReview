import type {ReactNode} from 'react';
import {CircleAlert, RefreshCw, TriangleAlert, Info, CircleCheck} from 'lucide-react';
import {cn} from '@/lib/utils';
import {errorMessage} from '@/lib/api';
import {Button} from './Button';

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  compact,
}: {
  icon: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center', compact ? 'px-4 py-8' : 'px-6 py-14', className)}>
      <div className="relative mb-4">
        <div className="absolute inset-0 -m-3 rounded-full bg-accent/10 blur-xl" />
        <div className="relative flex size-11 items-center justify-center rounded-xl border border-line-strong bg-gradient-to-b from-surface-3 to-surface-2 text-fg-muted shadow-card [&>svg]:size-5">
          {icon}
        </div>
      </div>
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-[12.5px] leading-5 text-fg-subtle">{description}</p>}
      {action && <div className="mt-4 flex flex-wrap items-center justify-center gap-2">{action}</div>}
    </div>
  );
}

export function ErrorState({error, onRetry, className, title = 'Veriler yüklenemedi'}: {error: unknown; onRetry?: () => void; className?: string; title?: string}) {
  return (
    <EmptyState
      className={className}
      icon={<CircleAlert className="text-bad" />}
      title={title}
      description={errorMessage(error)}
      action={
        onRetry && (
          <Button size="sm" icon={<RefreshCw className="size-3.5" />} onClick={onRetry}>
            Tekrar dene
          </Button>
        )
      }
    />
  );
}

export function Skeleton({className}: {className?: string}) {
  return <div className={cn('skeleton rounded-md', className)} />;
}

export function SkeletonRows({rows = 6, className}: {rows?: number; className?: string}) {
  return (
    <div className={cn('divide-y divide-line', className)}>
      {Array.from({length: rows}).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-3">
          <Skeleton className="h-3.5 w-16" />
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-3.5 w-12" />
        </div>
      ))}
    </div>
  );
}

const ALERT_TONE = {
  info: {cls: 'border-accent/25 bg-accent-soft text-fg', icon: <Info className="size-4 text-accent" />},
  warn: {cls: 'border-warn/30 bg-warn-soft text-fg', icon: <TriangleAlert className="size-4 text-warn" />},
  bad: {cls: 'border-bad/30 bg-bad-soft text-fg', icon: <CircleAlert className="size-4 text-bad" />},
  ok: {cls: 'border-ok/30 bg-ok-soft text-fg', icon: <CircleCheck className="size-4 text-ok" />},
};

export function Alert({
  tone = 'info',
  title,
  children,
  action,
  className,
}: {
  tone?: keyof typeof ALERT_TONE;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const t = ALERT_TONE[tone];
  return (
    <div className={cn('flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-[12.5px]', t.cls, className)}>
      <span className="mt-px shrink-0">{t.icon}</span>
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cn('text-fg-muted', title && 'mt-0.5')}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
