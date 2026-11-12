import {Check} from 'lucide-react';
import {cn} from '@/lib/utils';

export function ProgressBar({
  value,
  max = 100,
  active,
  className,
  tone = 'accent',
  size = 'md',
}: {
  value: number;
  max?: number;
  active?: boolean;
  className?: string;
  tone?: 'accent' | 'ok' | 'bad' | 'warn';
  size?: 'sm' | 'md' | 'lg';
}) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  const color = {accent: 'bg-accent', ok: 'bg-ok', bad: 'bg-bad', warn: 'bg-warn'}[tone];
  const height = {sm: 'h-1', md: 'h-1.5', lg: 'h-2.5'}[size];
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      className={cn('relative w-full overflow-hidden rounded-full bg-surface-3', height, className)}
    >
      <div
        className={cn('relative h-full rounded-full transition-[width] duration-500 ease-out', color, active && 'stripes')}
        style={{width: `${pct}%`}}
      >
        {active && <div className="absolute inset-y-0 right-0 w-8 bg-gradient-to-r from-transparent to-white/40 blur-[2px]" />}
      </div>
    </div>
  );
}

export interface Step {
  title: string;
  description?: string;
}

export function Stepper({
  steps,
  current,
  onStep,
  maxReachable,
}: {
  steps: Step[];
  current: number;
  onStep?: (index: number) => void;
  maxReachable: number;
}) {
  return (
    <ol className="flex w-full items-center gap-2">
      {steps.map((step, i) => {
        const done = i < current;
        const active = i === current;
        const reachable = i <= maxReachable;
        return (
          <li key={step.title} className="flex min-w-0 flex-1 items-center gap-2">
            <button
              type="button"
              disabled={!reachable || !onStep}
              onClick={() => onStep?.(i)}
              className={cn(
                'group flex min-w-0 items-center gap-2.5 rounded-lg px-1.5 py-1 text-left transition-colors disabled:cursor-default',
                reachable && onStep && 'hover:bg-surface-2',
              )}
            >
              <span
                className={cn(
                  'flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tnum transition-all duration-200',
                  done && 'border-accent-solid bg-accent-solid text-white',
                  active && 'border-accent bg-accent-soft text-accent shadow-[0_0_0_4px_var(--color-accent-soft)]',
                  !done && !active && 'border-line-strong bg-surface-2 text-fg-subtle',
                )}
              >
                {done ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
              </span>
              <span className="hidden min-w-0 sm:block">
                <span className={cn('block truncate text-[13px] font-medium', active || done ? 'text-fg' : 'text-fg-subtle')}>
                  {step.title}
                </span>
                {step.description && <span className="block truncate text-[11.5px] text-fg-subtle">{step.description}</span>}
              </span>
            </button>
            {i < steps.length - 1 && (
              <span className="relative h-px min-w-4 flex-1 bg-line-strong">
                <span
                  className="absolute inset-y-0 left-0 bg-accent transition-[width] duration-300"
                  style={{width: done ? '100%' : '0%'}}
                />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
