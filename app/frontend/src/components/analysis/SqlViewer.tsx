import {memo, useEffect, useMemo, useRef} from 'react';
import {cn} from '@/lib/utils';
import {highlightSql, TOKEN_CLASS} from '@/lib/sql';
import {SEVERITY_VAR} from '@/lib/severity';
import type {LineMark} from '@/lib/findings';
import {SeverityBadge} from '@/components/ui/Badge';
import {Tooltip} from '@/components/ui/Tooltip';

const Line = memo(function Line({
  number,
  tokens,
  mark,
  focused,
  showNotes,
}: {
  number: number;
  tokens: ReturnType<typeof highlightSql>[number];
  mark?: LineMark;
  focused: boolean;
  showNotes: boolean;
}) {
  const color = mark ? SEVERITY_VAR[mark.severity] : undefined;
  return (
    <>
      <div
        data-line={number}
        className={cn('group/line flex min-w-full', focused && 'outline outline-1 -outline-offset-1 outline-accent/50')}
        style={mark ? {background: `color-mix(in srgb, ${color} 9%, transparent)`} : undefined}
      >
        <div
          className="sticky left-0 z-[1] flex w-14 shrink-0 select-none items-center justify-end gap-1.5 border-r border-line bg-surface pr-2.5 text-right text-fg-subtle/80 tnum"
          style={mark ? {boxShadow: `inset 3px 0 0 ${color}`, background: `color-mix(in srgb, ${color} 10%, var(--color-surface))`} : undefined}
        >
          {mark && (
            <Tooltip
              content={
                <div className="flex max-w-72 flex-col gap-1.5 py-0.5">
                  {mark.notes.map((n, i) => (
                    <div key={i}>
                      <div className="flex items-center gap-1.5">
                        <SeverityBadge severity={n.severity} compact />
                        {n.code && <span className="font-mono text-[11px] font-semibold">{n.code}</span>}
                        {n.title && <span className="truncate text-fg-muted">{n.title}</span>}
                      </div>
                      <p className="mt-0.5 text-fg-muted">{n.message}</p>
                    </div>
                  ))}
                </div>
              }
              side="right"
              delay={80}
            >
              <span className="size-2 cursor-help rounded-full" style={{background: color, boxShadow: `0 0 0 3px color-mix(in srgb, ${color} 22%, transparent)`}} />
            </Tooltip>
          )}
          <span className={cn(mark && 'font-semibold text-fg')}>{number}</span>
        </div>
        <pre className="flex-1 py-px pr-6 pl-4 whitespace-pre">
          {tokens.length === 0 ? ' ' : tokens.map((t, i) => (
            <span key={i} className={TOKEN_CLASS[t.type]}>
              {t.value}
            </span>
          ))}
        </pre>
      </div>
      {mark && showNotes && (
        <div className="flex min-w-full">
          <div className="sticky left-0 z-[1] w-14 shrink-0 border-r border-line bg-surface" />
          <div className="flex flex-1 flex-col gap-1 py-1.5 pr-4 pl-4">
            {mark.notes.map((n, i) => (
              <div
                key={i}
                className="flex max-w-3xl items-start gap-2 rounded-md border border-line bg-elevated px-2.5 py-1.5 font-sans text-[12px] leading-[18px] shadow-card"
                style={{borderLeft: `2px solid ${SEVERITY_VAR[n.severity]}`}}
              >
                <SeverityBadge severity={n.severity} />
                <div className="min-w-0">
                  {(n.code || n.title) && (
                    <span className="mr-1.5 font-semibold text-fg">
                      {n.code && <span className="font-mono">{n.code}</span>}
                      {n.code && n.title && ' · '}
                      {n.title}
                    </span>
                  )}
                  <span className="text-fg-muted">{n.message}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
});

export function SqlViewer({
  source,
  marks,
  focusLine,
  showNotes = false,
  className,
  maxHeight,
}: {
  source: string;
  marks?: Map<number, LineMark>;
  focusLine?: number | null;
  showNotes?: boolean;
  className?: string;
  maxHeight?: string;
}) {
  const lines = useMemo(() => highlightSql(source), [source]);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!focusLine || !scroller.current) return;
    const el = scroller.current.querySelector<HTMLElement>(`[data-line="${focusLine}"]`);
    if (el) {
      const top = el.offsetTop - scroller.current.clientHeight / 3;
      scroller.current.scrollTo({top: Math.max(0, top), behavior: 'smooth'});
    }
  }, [focusLine, source]);

  return (
    <div
      ref={scroller}
      className={cn('relative overflow-auto bg-surface font-mono text-[12px] leading-[20px]', className)}
      style={maxHeight ? {maxHeight} : undefined}
    >
      <div className="relative w-max min-w-full py-2">
        {lines.map((tokens, i) => (
          <Line key={i} number={i + 1} tokens={tokens} mark={marks?.get(i + 1)} focused={focusLine === i + 1} showNotes={showNotes} />
        ))}
      </div>
    </div>
  );
}
