import {useEffect, useRef} from 'react';
import type {LineMark} from '@/lib/codeLines';

const SEVERITY_LABEL = {HIGH: 'yüksek', MEDIUM: 'orta', LOW: 'düşük'} as const;

/**
 * The reviewed SQL with line numbers; lines a finding points at carry its severity colour and the
 * rule codes. `focus` scrolls a line into view and briefly highlights it. Text only: the SQL is
 * rendered as plain text, never as markup.
 */
export function SqlCodeView({
  sql,
  marks,
  focus,
  label,
}: {
  sql: string;
  marks: Map<number, LineMark>;
  focus: {line: number; seq: number} | null;
  label: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const lines = sql.replace(/\r\n?/g, '\n').split('\n');
  const flagged = [...marks.keys()].filter((line) => line <= lines.length).length;

  useEffect(() => {
    if (focus === null) return;
    const row = container.current?.querySelector<HTMLElement>(`[data-line="${focus.line}"]`);
    if (!row) return;
    row.scrollIntoView?.({block: 'center', behavior: 'smooth'});
    row.classList.remove('is-focus');
    // Restart the highlight even when the same line is chosen twice.
    void row.offsetWidth;
    row.classList.add('is-focus');
  }, [focus]);

  return (
    <div className="code-view" role="region" aria-label={label}>
      <div className="code-view-head">
        <span className="mono">SQL</span>
        <span className="subtle tabular">
          {lines.length.toLocaleString('tr-TR')} satır · {flagged} işaretli satır
        </span>
      </div>
      <div className="code-view-body" ref={container}>
        {lines.map((text, index) => {
          const number = index + 1;
          const mark = marks.get(number);
          return (
            <div
              key={number}
              data-line={number}
              className={`code-line${mark ? ` is-${mark.severity.toLowerCase()}` : ''}`}
              title={mark ? `${mark.rules.join(', ')} · önem ${SEVERITY_LABEL[mark.severity]}` : undefined}
            >
              <span className="code-gutter" aria-hidden="true">
                {number}
              </span>
              <code className="code-text">{text || ' '}</code>
              {mark && (
                <span className="code-flag">
                  <span className="sr-only">Satır {number}: </span>
                  {mark.rules.join(', ')}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
