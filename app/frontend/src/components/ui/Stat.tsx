import type {ReactNode} from 'react';
import {Link} from 'react-router';
import {cn} from '@/lib/utils';
import {formatNumber} from '@/lib/format';

export function Stat({
  label,
  value,
  icon,
  hint,
  to,
  extra,
  tone,
  className,
}: {
  label: ReactNode;
  value: number | string | null | undefined;
  icon?: ReactNode;
  hint?: ReactNode;
  to?: string;
  extra?: ReactNode;
  tone?: string;
  className?: string;
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-medium text-fg-subtle">{label}</span>
        {icon && (
          <span className="flex size-7 items-center justify-center rounded-lg border border-line bg-surface-2 text-fg-subtle transition-colors group-hover:text-fg-muted [&>svg]:size-3.5">
            {icon}
          </span>
        )}
      </div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className={cn('text-[26px] leading-8 font-semibold tracking-[-0.02em] text-fg tnum', tone)}>
            {typeof value === 'number' ? formatNumber(value) : (value ?? '—')}
          </div>
          {hint && <div className="mt-0.5 truncate text-[11.5px] text-fg-subtle">{hint}</div>}
        </div>
        {extra}
      </div>
    </>
  );
  const cls = cn(
    'group relative overflow-hidden rounded-xl border border-line bg-surface p-4 shadow-card transition-[border-color,background-color,transform] duration-200',
    to && 'hover:border-line-strong hover:bg-surface-2/40',
    className,
  );
  return to ? (
    <Link to={to} className={cls}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}
