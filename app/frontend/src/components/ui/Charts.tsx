import {useState, type ReactNode} from 'react';
import {cn} from '@/lib/utils';
import {SEVERITIES, SEVERITY_FG_VAR, SEVERITY_LABEL, SEVERITY_VAR, normalizeCounts, totalCount} from '@/lib/severity';
import {formatNumber} from '@/lib/format';
import type {Severity, SeverityCounts} from '@/types';
import {Tooltip} from './Tooltip';

/** Donut built from stroked circle arcs; a hovered segment lifts and shows its share in the center. */
export function Donut({
  counts,
  size = 168,
  thickness = 16,
  centerLabel = 'bulgu',
}: {
  counts: Partial<SeverityCounts> | null | undefined;
  size?: number;
  thickness?: number;
  centerLabel?: string;
}) {
  const data = normalizeCounts(counts);
  const total = totalCount(data);
  const [hover, setHover] = useState<Severity | null>(null);
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const gap = total > 0 && SEVERITIES.filter((s) => data[s] > 0).length > 1 ? 2.5 : 0;
  let offset = 0;
  const shown = hover ? data[hover] : total;
  return (
    <div className="relative shrink-0" style={{width: size, height: size}}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-surface-3)" strokeWidth={thickness} />
        {total > 0 &&
          SEVERITIES.map((s) => {
            const value = data[s];
            if (!value) return null;
            const len = (value / total) * c;
            const dash = Math.max(0.001, len - gap);
            const el = (
              <circle
                key={s}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={SEVERITY_VAR[s]}
                strokeWidth={hover === s ? thickness + 4 : thickness}
                strokeDasharray={`${dash} ${c - dash}`}
                strokeDashoffset={-offset}
                strokeLinecap="butt"
                className="cursor-pointer transition-[stroke-width,opacity] duration-200"
                style={{opacity: hover && hover !== s ? 0.35 : 1}}
                onMouseEnter={() => setHover(s)}
                onMouseLeave={() => setHover(null)}
              />
            );
            offset += len;
            return el;
          })}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-semibold tracking-tight text-fg tnum">{formatNumber(shown)}</span>
        <span className="text-[11px] text-fg-subtle">{hover ? SEVERITY_LABEL[hover] : centerLabel}</span>
      </div>
    </div>
  );
}

export function SeverityLegend({counts, className}: {counts: Partial<SeverityCounts> | null | undefined; className?: string}) {
  const data = normalizeCounts(counts);
  const total = totalCount(data);
  return (
    <ul className={cn('flex flex-col gap-2', className)}>
      {SEVERITIES.map((s) => {
        const pct = total ? (data[s] / total) * 100 : 0;
        return (
          <li key={s} className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-2.5 text-[12.5px]">
            <span className="size-2.5 rounded-[3px]" style={{background: SEVERITY_VAR[s]}} />
            <span className="text-fg-muted">{SEVERITY_LABEL[s]}</span>
            <span className="font-medium text-fg tnum">{formatNumber(data[s])}</span>
            <span className="w-10 text-right text-[11.5px] text-fg-subtle tnum">%{Math.round(pct)}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Horizontal stacked severity bar. */
export function SeverityBar({
  counts,
  className,
  height = 6,
  showEmpty = true,
}: {
  counts: Partial<SeverityCounts> | null | undefined;
  className?: string;
  height?: number;
  showEmpty?: boolean;
}) {
  const data = normalizeCounts(counts);
  const total = totalCount(data);
  const tip: ReactNode = (
    <div className="flex flex-col gap-1 py-0.5">
      {SEVERITIES.map((s) => (
        <div key={s} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-sm" style={{background: SEVERITY_VAR[s]}} />
            {SEVERITY_LABEL[s]}
          </span>
          <span className="tnum font-medium">{data[s]}</span>
        </div>
      ))}
    </div>
  );
  if (!total && !showEmpty) return null;
  return (
    <Tooltip content={total ? tip : 'Bulgu yok'}>
      <div
        className={cn('flex w-full gap-px overflow-hidden rounded-full bg-surface-3', className)}
        style={{height}}
        aria-label={SEVERITIES.map((s) => `${SEVERITY_LABEL[s]} ${data[s]}`).join(', ')}
      >
        {total > 0 &&
          SEVERITIES.map((s) =>
            data[s] ? (
              <div
                key={s}
                className="h-full transition-[width] duration-500"
                style={{width: `${(data[s] / total) * 100}%`, background: SEVERITY_VAR[s]}}
              />
            ) : null,
          )}
      </div>
    </Tooltip>
  );
}

/** Compact counts row: colored numbers for non-zero severities. */
export function SeverityCountsInline({counts, className}: {counts: Partial<SeverityCounts> | null | undefined; className?: string}) {
  const data = normalizeCounts(counts);
  const items = SEVERITIES.filter((s) => data[s] > 0);
  if (!items.length) return <span className={cn('text-xs text-fg-subtle', className)}>—</span>;
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      {items.map((s) => (
        <Tooltip key={s} content={SEVERITY_LABEL[s]}>
          <span className="inline-flex items-center gap-1 text-xs font-medium tnum" style={{color: SEVERITY_FG_VAR[s]}}>
            <span className="size-1.5 rounded-full" style={{background: SEVERITY_VAR[s]}} />
            {data[s]}
          </span>
        </Tooltip>
      ))}
    </span>
  );
}

export function Sparkline({
  values,
  width = 96,
  height = 28,
  className,
  color = 'var(--color-accent)',
}: {
  values: number[];
  width?: number;
  height?: number;
  className?: string;
  color?: string;
}) {
  if (values.length < 2) return <svg width={width} height={height} className={className} />;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const points = values.map((v, i) => [i * step, height - 3 - ((v - min) / span) * (height - 6)] as const);
  const line = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${line} L${width},${height} L0,${height} Z`;
  const id = `spark-${values.join('-').slice(0, 24)}-${values.length}`;
  const [lx, ly] = points[points.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn('overflow-visible', className)}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.28} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r={2.5} fill={color} />
    </svg>
  );
}
