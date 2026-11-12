import {useMemo, useRef, useState, type ReactNode} from 'react';
import {Plus, X} from 'lucide-react';
import {cn} from '@/lib/utils';
import {matchesSearch} from '@/lib/format';
import {fieldBase} from '@/components/ui/Input';

/** Free-text tag input: type and press Enter (or comma); Backspace on an empty input removes the last tag. */
export function TagInput({
  value,
  onChange,
  suggestions = [],
  placeholder,
  mono,
  upperCase,
  icon,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
  mono?: boolean;
  upperCase?: boolean;
  icon?: ReactNode;
}) {
  const [text, setText] = useState('');
  const [focused, setFocused] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const has = (v: string) => value.some((x) => x.toLowerCase() === v.toLowerCase());

  const add = (raw: string) => {
    const parts = raw
      .split(/[,;\s]+/)
      .map((p) => p.trim())
      .filter(Boolean)
      .map((p) => (upperCase ? p.toUpperCase() : p));
    const next = [...value];
    for (const p of parts) if (!next.some((x) => x.toLowerCase() === p.toLowerCase())) next.push(p);
    if (next.length !== value.length) onChange(next);
    setText('');
  };

  const shown = useMemo(
    () => suggestions.filter((s) => !value.some((x) => x.toLowerCase() === s.toLowerCase()) && matchesSearch(text, s)).slice(0, 12),
    [suggestions, value, text],
  );

  return (
    <div className="flex flex-col gap-1.5">
      <div
        onClick={() => input.current?.focus()}
        className={cn(fieldBase, 'flex min-h-8 cursor-text flex-wrap items-center gap-1 px-1.5 py-1', focused && 'border-accent/70 bg-surface ring-3 ring-accent/15')}
      >
        {icon && <span className="flex pl-1 text-fg-subtle">{icon}</span>}
        {value.map((v) => (
          <span key={v} className={cn('inline-flex h-5 items-center gap-1 rounded-md bg-surface-3 pr-0.5 pl-1.5 text-[11.5px] text-fg', mono && 'font-mono')}>
            {v}
            <button
              type="button"
              aria-label={`${v} kaldır`}
              onClick={(e) => {
                e.stopPropagation();
                onChange(value.filter((x) => x !== v));
              }}
              className="flex size-4 items-center justify-center rounded text-fg-subtle hover:bg-surface-2 hover:text-fg"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          ref={input}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false);
            if (text.trim()) add(text);
          }}
          onKeyDown={(e) => {
            if ((e.key === 'Enter' || e.key === ',') && text.trim()) {
              e.preventDefault();
              add(text);
            } else if (e.key === 'Enter') {
              e.preventDefault();
            } else if (e.key === 'Backspace' && !text && value.length) {
              onChange(value.slice(0, -1));
            }
          }}
          placeholder={value.length ? '' : placeholder}
          className={cn('h-5 min-w-28 flex-1 bg-transparent px-1 text-[13px] text-fg outline-none placeholder:text-fg-subtle', mono && 'font-mono text-[12.5px]')}
        />
      </div>
      {focused && shown.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-0.5 text-[11px] text-fg-subtle">Öneriler:</span>
          {shown.map((s) => (
            <button
              key={s}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => !has(s) && add(s)}
              className={cn(
                'inline-flex h-5 items-center gap-0.5 rounded-md border border-line-strong bg-surface-2/60 px-1.5 text-[11px] text-fg-muted transition-colors hover:border-accent/40 hover:text-fg',
                mono && 'font-mono',
              )}
            >
              <Plus className="size-2.5" />
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
