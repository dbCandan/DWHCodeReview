import type {ReactNode} from 'react';
import {Check} from 'lucide-react';
import {cn} from '@/lib/utils';

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
  count?: number;
  icon?: ReactNode;
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  className,
}: {
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div role="tablist" className={cn('flex items-center gap-1 border-b border-line', className)}>
      {items.map((item) => {
        const active = item.id === value;
        return (
          <button
            key={item.id}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(item.id)}
            onKeyDown={(e) => {
              const index = items.findIndex((i) => i.id === value);
              if (e.key === 'ArrowRight') onChange(items[(index + 1) % items.length].id);
              if (e.key === 'ArrowLeft') onChange(items[(index - 1 + items.length) % items.length].id);
            }}
            className={cn(
              'relative -mb-px flex h-9 items-center gap-1.5 px-3 text-[13px] font-medium transition-colors duration-150',
              active ? 'text-fg' : 'text-fg-muted hover:text-fg',
            )}
          >
            {item.icon}
            {item.label}
            {item.count !== undefined && (
              <span
                className={cn(
                  'rounded-md px-1.5 py-px text-[11px] tnum',
                  active ? 'bg-accent-soft text-accent' : 'bg-surface-3 text-fg-subtle',
                )}
              >
                {item.count}
              </span>
            )}
            <span
              className={cn(
                'absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent transition-opacity duration-150',
                active ? 'opacity-100' : 'opacity-0',
              )}
            />
          </button>
        );
      })}
    </div>
  );
}

/** Pill-style segmented control. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
  size = 'md',
}: {
  options: {value: T; label: ReactNode; icon?: ReactNode; activeClass?: string}[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
  size?: 'sm' | 'md';
}) {
  return (
    <div
      role="radiogroup"
      className={cn('inline-flex items-center gap-0.5 rounded-lg border border-line-strong bg-surface-2 p-0.5', className)}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              'inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-all duration-150',
              size === 'sm' ? 'h-6 px-2 text-[11.5px]' : 'h-7 px-2.5 text-xs',
              active
                ? cn('bg-elevated font-semibold text-fg shadow-[0_1px_2px_rgb(0_0_0/0.25),0_0_0_1px_var(--color-accent)]', option.activeClass)
                : 'text-fg-muted hover:bg-surface-3 hover:text-fg',
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/** Toggleable filter chip. */
export function Chip({
  active,
  onClick,
  children,
  className,
  activeClass,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  className?: string;
  activeClass?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-all duration-150',
        active
          ? cn('border-accent bg-accent-soft text-fg', activeClass)
          : 'border-line-control bg-surface-2/50 text-fg-muted hover:border-fg-subtle hover:bg-surface-3 hover:text-fg',
        className,
      )}
    >
      {active && <Check className="-ml-0.5 size-3 text-accent" strokeWidth={3} />}
      {children}
    </button>
  );
}
