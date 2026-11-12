import {forwardRef, useId, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes} from 'react';
import {Search, X} from 'lucide-react';
import {cn} from '@/lib/utils';

export const fieldBase =
  'w-full rounded-lg border border-line-control bg-surface-2/60 text-fg placeholder:text-fg-subtle transition-[border-color,box-shadow,background-color] duration-150 hover:border-fg-subtle focus:outline-none focus-visible:outline-none focus:border-accent focus:ring-3 focus:ring-accent/25 focus:bg-surface disabled:opacity-70 aria-[invalid=true]:border-bad aria-[invalid=true]:focus:ring-bad/20';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  leading?: ReactNode;
  trailing?: ReactNode;
  mono?: boolean;
  inputSize?: 'sm' | 'md';
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {leading, trailing, className, mono, inputSize = 'md', ...rest},
  ref,
) {
  const height = inputSize === 'sm' ? 'h-7 text-xs' : 'h-8 text-[13px]';
  if (!leading && !trailing) {
    return <input ref={ref} className={cn(fieldBase, height, 'px-2.5', mono && 'font-mono text-[12.5px]', className)} {...rest} />;
  }
  return (
    <div className={cn('relative flex items-center', className)}>
      {leading && <span className="pointer-events-none absolute left-2.5 flex text-fg-subtle">{leading}</span>}
      <input
        ref={ref}
        className={cn(fieldBase, height, leading ? 'pl-8' : 'pl-2.5', trailing ? 'pr-8' : 'pr-2.5', mono && 'font-mono text-[12.5px]')}
        {...rest}
      />
      {trailing && <span className="absolute right-1.5 flex">{trailing}</span>}
    </div>
  );
});

export function SearchInput({
  value,
  onChange,
  placeholder = 'Ara…',
  className,
  autoFocus,
  inputSize,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  autoFocus?: boolean;
  inputSize?: 'sm' | 'md';
}) {
  return (
    <Input
      className={className}
      inputSize={inputSize}
      value={value}
      autoFocus={autoFocus}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && value) {
          e.stopPropagation();
          onChange('');
        }
      }}
      leading={<Search className="size-3.5" />}
      trailing={
        value ? (
          <button
            type="button"
            aria-label="Temizle"
            onClick={() => onChange('')}
            className="flex size-5 items-center justify-center rounded text-fg-subtle hover:bg-surface-3 hover:text-fg"
          >
            <X className="size-3" />
          </button>
        ) : null
      }
    />
  );
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & {mono?: boolean}>(
  function Textarea({className, mono, ...rest}, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(
          fieldBase,
          'min-h-20 resize-y px-2.5 py-2 text-[13px] leading-5',
          mono && 'font-mono text-[12px] leading-[1.6]',
          className,
        )}
        spellCheck={mono ? false : undefined}
        {...rest}
      />
    );
  },
);

export function Field({
  label,
  hint,
  error,
  children,
  className,
  required,
  htmlFor,
  aside,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
  required?: boolean;
  htmlFor?: string;
  aside?: ReactNode;
}) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={htmlFor} className="text-xs font-medium text-fg-muted">
          {label}
          {required && <span className="ml-0.5 text-bad">*</span>}
        </label>
        {aside}
      </div>
      {children}
      {error ? (
        <p className="text-[11.5px] text-bad">{error}</p>
      ) : hint ? (
        <p className="text-[11.5px] text-fg-subtle">{hint}</p>
      ) : null}
    </div>
  );
}

export function useFieldId(prefix = 'f') {
  return `${prefix}-${useId().replace(/:/g, '')}`;
}
