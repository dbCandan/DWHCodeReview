import {Check, Minus} from 'lucide-react';
import type {ReactNode} from 'react';
import {cn} from '@/lib/utils';

export function Switch({
  checked,
  onChange,
  disabled,
  label,
  size = 'md',
  id,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: string;
  size?: 'sm' | 'md';
  id?: string;
}) {
  const track = size === 'sm' ? 'h-4 w-7' : 'h-5 w-9';
  const knob = size === 'sm' ? 'size-3 data-[on=true]:translate-x-3' : 'size-4 data-[on=true]:translate-x-4';
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      className={cn(
        'relative inline-flex shrink-0 items-center rounded-full border p-px transition-colors duration-200 disabled:opacity-60',
        track,
        checked ? 'border-accent-solid bg-accent-solid' : 'border-line-control bg-surface-3 hover:border-fg-subtle',
      )}
    >
      <span
        data-on={checked}
        className={cn(
          'block rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/0.35)] transition-transform duration-200 ease-out',
          knob,
        )}
      />
    </button>
  );
}

export function Checkbox({
  checked,
  indeterminate,
  onChange,
  label,
  disabled,
  className,
}: {
  checked: boolean;
  indeterminate?: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  disabled?: boolean;
  className?: string;
}) {
  const on = checked || indeterminate;
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? 'mixed' : checked}
      aria-label={label}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      className={cn(
        'flex size-4 shrink-0 items-center justify-center rounded-[5px] border transition-colors duration-150 disabled:opacity-60',
        on ? 'border-accent-solid bg-accent-solid text-white' : 'border-line-control bg-surface hover:border-fg-muted',
        className,
      )}
    >
      {indeterminate ? <Minus className="size-3" strokeWidth={3} /> : checked ? <Check className="size-3" strokeWidth={3} /> : null}
    </button>
  );
}

export function SwitchRow({
  title,
  description,
  checked,
  onChange,
  disabled,
}: {
  title: ReactNode;
  description?: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-lg border border-line-strong bg-surface-2/40 px-3 py-2.5 transition-colors hover:bg-surface-2">
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-fg">{title}</span>
        {description && <span className="mt-0.5 block text-xs text-fg-subtle">{description}</span>}
      </span>
      <Switch checked={checked} onChange={onChange} disabled={disabled} />
    </label>
  );
}
