import {useLayoutEffect, useRef, useState} from 'react';
import {useNavigate} from 'react-router';
import {SEVERITIES, SEVERITY_LABEL, SEVERITY_VAR, normalizeCounts, totalCount} from '@/lib/severity';
import {formatDateTime, formatNumber} from '@/lib/format';
import {niceTicks} from '@/lib/dashboard';
import type {AnalysisSummary} from '@/types';

const dayFmt = new Intl.DateTimeFormat('tr-TR', {day: 'numeric', month: 'short'});
const timeFmt = new Intl.DateTimeFormat('tr-TR', {hour: '2-digit', minute: '2-digit'});

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({w: 0, h: 0});
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({w: Math.floor(e.contentRect.width), h: Math.floor(e.contentRect.height)}));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

export type TrendScale = 'linear' | 'log';

/** Powers of ten (0, 1, 10, 100 …) covering `max`, for the logarithmic axis. */
export function logTicks(max: number): number[] {
  const ticks = [0, 1];
  while (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] * 10);
  return ticks;
}

/**
 * Stacked severity bars for the given analyses (oldest → newest); sized to its container.
 * In log scale the bar height is log10(1 + total) and its segments keep their share of the total,
 * so small analyses stay readable next to very large ones.
 */
export function FindingTrend({analyses, scale = 'linear'}: {analyses: AnalysisSummary[]; scale?: TrendScale}) {
  const [ref, {w, h}] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const navigate = useNavigate();
  const data = analyses.map((a) => ({a, c: normalizeCounts(a.severity_counts), t: totalCount(normalizeCounts(a.severity_counts))}));
  const maxTotal = Math.max(1, ...data.map((d) => d.t));
  const ticks = scale === 'log' ? logTicks(maxTotal) : niceTicks(maxTotal);
  const top = ticks[ticks.length - 1] || 1;
  const pad = {l: 44, r: 8, t: 8, b: 32};
  const when = (x: AnalysisSummary) => new Date(x.finished_at ?? x.created_at);
  const days = data.map((d) => dayFmt.format(when(d.a)));
  const showLabel = (i: number) => slot >= 40 || i % Math.ceil(40 / Math.max(1, slot)) === 0 || i === data.length - 1;
  const iw = Math.max(0, w - pad.l - pad.r);
  const ih = Math.max(0, h - pad.t - pad.b);
  const slot = data.length ? iw / data.length : 0;
  const bw = Math.max(4, Math.min(36, slot * 0.58));
  const frac = (v: number) => (scale === 'log' ? Math.log10(1 + v) / Math.log10(1 + top) : v / top);
  const y = (v: number) => pad.t + ih - frac(v) * ih;
  const hovered = hover !== null ? data[hover] : null;

  return (
    <div ref={ref} className="relative h-full min-h-40 w-full" onMouseLeave={() => setHover(null)}>
      {w > 0 && h > 0 && (
        <svg width={w} height={h} className="block" role="img" aria-label="Son tamamlanmış analizlerde önem derecesine göre bulgu sayıları">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} stroke="var(--color-line)" strokeDasharray={t === 0 ? undefined : '3 3'} />
              <text x={pad.l - 8} y={y(t) + 3.5} textAnchor="end" fontSize="10.5" fill="var(--color-fg-subtle)" style={{fontVariantNumeric: 'tabular-nums'}}>
                {formatNumber(t)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = pad.l + slot * i + slot / 2;
            let acc = 0;
            const active = hover === i;
            return (
              <g
                key={d.a.id}
                className="cursor-pointer"
                onMouseEnter={() => setHover(i)}
                onClick={() => navigate(`/analyses/${d.a.id}`)}
                style={{opacity: hover !== null && !active ? 0.5 : 1, transition: 'opacity 120ms'}}
              >
                <rect x={pad.l + slot * i} y={pad.t} width={slot} height={ih} fill={active ? 'var(--color-surface-2)' : 'transparent'} />
                {[...SEVERITIES].reverse().map((s) => {
                  const v = d.c[s];
                  if (!v) return null;
                  // Segment boundaries as a share of the bar, so the log axis keeps the mix readable.
                  const barTop = y(d.t);
                  const barH = y(0) - barTop;
                  const y0 = y(0) - (acc / d.t) * barH;
                  acc += v;
                  const y1 = y(0) - (acc / d.t) * barH;
                  return <rect key={s} x={cx - bw / 2} y={y1} width={bw} height={Math.max(1, y0 - y1 - (acc < d.t ? 1 : 0))} fill={SEVERITY_VAR[s]} rx={1.5} />;
                })}
                {d.t === 0 && <rect x={cx - bw / 2} y={y(0) - 2} width={bw} height={2} rx={1} fill="var(--color-line-strong)" />}
                {showLabel(i) && (
                  <text x={cx} y={h - 18} textAnchor="middle" fontSize="10.5" fill={active ? 'var(--color-fg)' : 'var(--color-fg-muted)'} style={{fontVariantNumeric: 'tabular-nums'}}>
                    {timeFmt.format(when(d.a))}
                  </text>
                )}
                {(i === 0 || days[i] !== days[i - 1]) && (
                  <text x={cx} y={h - 4} textAnchor="middle" fontSize="10" fill="var(--color-fg-subtle)">
                    {days[i]}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
      {hovered && hover !== null && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 w-52 rounded-lg border border-line-strong bg-elevated px-3 py-2 text-[11.5px] text-fg shadow-pop"
          style={{
            // Beside the hovered bar (right, or left near the edge) so the bar stays visible.
            left: (() => {
              const cx = pad.l + slot * hover + slot / 2;
              return cx + bw / 2 + 216 <= w ? cx + bw / 2 + 8 : Math.max(4, cx - bw / 2 - 216);
            })(),
            top: pad.t,
          }}
        >
          <p className="truncate font-semibold">{hovered.a.name}</p>
          <p className="text-fg-subtle">{formatDateTime(hovered.a.finished_at ?? hovered.a.created_at)}</p>
          <ul className="mt-1.5 flex flex-col gap-0.5">
            {SEVERITIES.map((s) => (
              <li key={s} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-1.5 text-fg-muted">
                  <span className="size-2 rounded-sm" style={{background: SEVERITY_VAR[s]}} />
                  {SEVERITY_LABEL[s]}
                </span>
                <span className="font-medium tnum">{formatNumber(hovered.c[s])}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1 flex justify-between border-t border-line pt-1 font-semibold">
            <span>Toplam</span>
            <span className="tnum">{formatNumber(hovered.t)}</span>
          </p>
        </div>
      )}
    </div>
  );
}
