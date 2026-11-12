import {useEffect, useMemo, useRef, useState, type ReactNode, type SelectHTMLAttributes} from 'react';
import {Check, ChevronDown, X} from 'lucide-react';
import {cn} from '@/lib/utils';
import {matchesSearch} from '@/lib/format';
import {fieldBase, SearchInput} from './Input';

export function Select({className, children, ...rest}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className={cn('relative', className)}>
      <select className={cn(fieldBase, 'h-8 appearance-none pr-8 pl-2.5 text-[13px] [&>option]:bg-elevated')} {...rest}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2 text-fg-subtle" />
    </div>
  );
}

/** Click-outside / Esc aware popover anchored below its trigger. */
export function Popover({
  open,
  onClose,
  trigger,
  children,
  align = 'start',
  className,
  matchWidth,
}: {
  open: boolean;
  onClose: () => void;
  trigger: ReactNode;
  children: ReactNode;
  align?: 'start' | 'end';
  className?: string;
  matchWidth?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open, onClose]);
  return (
    <div
      ref={root}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      {trigger}
      {open && (
        <div
          className={cn(
            'absolute top-full z-40 mt-1.5 animate-pop-in overflow-hidden rounded-xl border border-line-strong bg-elevated shadow-pop',
            align === 'end' ? 'right-0' : 'left-0',
            matchWidth && 'min-w-full',
            className,
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

export interface MultiOption {
  value: string;
  label: string;
  hint?: ReactNode;
  color?: string;
  group?: string;
}

export function MultiSelect({
  options,
  value,
  onChange,
  placeholder = 'Seçin…',
  searchPlaceholder = 'Ara…',
  emptyText = 'Sonuç yok',
  loading,
  disabled,
  className,
  allLabel,
}: {
  options: MultiOption[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  loading?: boolean;
  disabled?: boolean;
  className?: string;
  /** Text shown when nothing is selected and "empty means all". */
  allLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const selected = useMemo(() => new Set(value), [value]);
  const filtered = useMemo(
    () => options.filter((o) => matchesSearch(query, o.label, o.group, typeof o.hint === 'string' ? o.hint : '')),
    [options, query],
  );
  const toggle = (v: string) => onChange(selected.has(v) ? value.filter((x) => x !== v) : [...value, v]);
  const allFilteredSelected = filtered.length > 0 && filtered.every((o) => selected.has(o.value));
  const selectedOptions = options.filter((o) => selected.has(o.value));

  let groupHeader: string | undefined;
  return (
    <Popover
      open={open}
      onClose={() => {
        setOpen(false);
        setQuery('');
      }}
      matchWidth
      className="w-[min(380px,90vw)]"
      trigger={
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className={cn(fieldBase, 'flex min-h-8 items-center gap-1.5 py-1 pr-2 pl-2 text-left text-[13px]', className)}
        >
          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
            {selectedOptions.length === 0 ? (
              <span className="truncate pl-0.5 text-fg-subtle">{loading ? 'Yükleniyor…' : (allLabel ?? placeholder)}</span>
            ) : (
              <>
                {selectedOptions.slice(0, 4).map((o) => (
                  <span
                    key={o.value}
                    className="inline-flex h-5 max-w-44 items-center gap-1 rounded-md bg-surface-3 pr-0.5 pl-1.5 text-[11.5px] text-fg"
                  >
                    {o.color && <span className="size-1.5 shrink-0 rounded-full" style={{background: o.color}} />}
                    <span className="truncate">{o.label}</span>
                    <span
                      role="button"
                      tabIndex={-1}
                      aria-label={`${o.label} kaldır`}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggle(o.value);
                      }}
                      className="flex size-4 items-center justify-center rounded text-fg-subtle hover:bg-surface-2 hover:text-fg"
                    >
                      <X className="size-3" />
                    </span>
                  </span>
                ))}
                {selectedOptions.length > 4 && (
                  <span className="text-[11.5px] text-fg-subtle tnum">+{selectedOptions.length - 4}</span>
                )}
              </>
            )}
          </span>
          <ChevronDown className={cn('size-3.5 shrink-0 text-fg-subtle transition-transform', open && 'rotate-180')} />
        </button>
      }
    >
      <div className="border-b border-line p-2">
        <SearchInput value={query} onChange={setQuery} placeholder={searchPlaceholder} autoFocus inputSize="sm" />
      </div>
      <div className="flex items-center justify-between border-b border-line px-3 py-1.5 text-[11.5px]">
        <button
          type="button"
          className="font-medium text-accent hover:underline disabled:opacity-60"
          disabled={!filtered.length}
          onClick={() => {
            const vals = new Set(value);
            if (allFilteredSelected) filtered.forEach((o) => vals.delete(o.value));
            else filtered.forEach((o) => vals.add(o.value));
            onChange([...vals]);
          }}
        >
          {allFilteredSelected ? 'Görünenleri bırak' : 'Görünenleri seç'}
        </button>
        <span className="text-fg-subtle tnum">{value.length} seçili</span>
        <button type="button" className="text-fg-subtle hover:text-fg disabled:opacity-60" disabled={!value.length} onClick={() => onChange([])}>
          Temizle
        </button>
      </div>
      <ul className="max-h-72 overflow-y-auto p-1">
        {loading && <li className="px-3 py-6 text-center text-xs text-fg-subtle">Yükleniyor…</li>}
        {!loading && filtered.length === 0 && <li className="px-3 py-6 text-center text-xs text-fg-subtle">{emptyText}</li>}
        {!loading &&
          filtered.map((o) => {
            const header = o.group && o.group !== groupHeader ? o.group : null;
            groupHeader = o.group;
            const on = selected.has(o.value);
            return (
              <li key={o.value}>
                {header && <div className="px-2 pt-2 pb-1 text-[10.5px] font-semibold uppercase tracking-wider text-fg-subtle">{header}</div>}
                <button
                  type="button"
                  onClick={() => toggle(o.value)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-surface-2',
                    on && 'text-fg',
                  )}
                >
                  <span
                    className={cn(
                      'flex size-4 shrink-0 items-center justify-center rounded-[5px] border',
                      on ? 'border-accent-solid bg-accent-solid text-white' : 'border-line-control',
                    )}
                  >
                    {on && <Check className="size-3" strokeWidth={3} />}
                  </span>
                  {o.color && <span className="size-2 shrink-0 rounded-full" style={{background: o.color}} />}
                  <span className="min-w-0 flex-1 truncate">{o.label}</span>
                  {o.hint && <span className="shrink-0 text-[11.5px] text-fg-subtle tnum">{o.hint}</span>}
                </button>
              </li>
            );
          })}
      </ul>
    </Popover>
  );
}
