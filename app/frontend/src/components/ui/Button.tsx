import {forwardRef, type ButtonHTMLAttributes, type ReactNode} from 'react';
import {LoaderCircle} from 'lucide-react';
import {cn} from '@/lib/utils';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle';
export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg';

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    'bg-accent-solid text-accent-fg shadow-[inset_0_1px_0_rgb(255_255_255/0.18),0_1px_2px_rgb(0_0_0/0.3),0_0_0_1px_var(--color-accent-solid)] hover:bg-accent-solid-hover disabled:bg-surface-3 disabled:text-fg-muted disabled:opacity-100 disabled:shadow-[0_0_0_1px_var(--color-line-strong)]',
  secondary:
    'bg-surface-2 text-fg border border-line-strong hover:bg-surface-3 hover:border-line-control shadow-[0_1px_0_rgb(255_255_255/0.03)_inset]',
  subtle: 'bg-accent-soft text-accent hover:bg-accent/20',
  ghost: 'text-fg-muted hover:text-fg hover:bg-surface-3',
  danger: 'bg-bad-solid text-white hover:brightness-110 shadow-[0_0_0_1px_var(--color-bad-solid)]',
};

const SIZE: Record<ButtonSize, string> = {
  xs: 'h-6 px-2 text-[11.5px] gap-1 rounded-md',
  sm: 'h-7 px-2.5 text-xs gap-1.5 rounded-md',
  md: 'h-8 px-3 text-[13px] gap-2 rounded-lg',
  lg: 'h-10 px-4 text-sm gap-2 rounded-lg',
};

const ICON_SIZE: Record<ButtonSize, string> = {xs: 'size-6', sm: 'size-7', md: 'size-8', lg: 'size-10'};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
  iconOnly?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {variant = 'secondary', size = 'md', loading, icon, iconOnly, className, children, disabled, type = 'button', ...rest},
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cn(
        'relative inline-flex shrink-0 select-none [&_svg]:shrink-0 items-center justify-center whitespace-nowrap font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-150 active:translate-y-px disabled:pointer-events-none disabled:opacity-60',
        VARIANT[variant],
        iconOnly ? cn(ICON_SIZE[size], size === 'lg' || size === 'md' ? 'rounded-lg' : 'rounded-md') : SIZE[size],
        className,
      )}
      {...rest}
    >
      {loading ? <LoaderCircle className="size-3.5 animate-spin" /> : icon}
      {children}
    </button>
  );
});

/** Class string to style a router Link like a button. */
export function buttonClass(variant: ButtonVariant = 'secondary', size: ButtonSize = 'md', className?: string) {
  return cn(
    'relative inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap font-medium transition-[background-color,border-color,color,box-shadow] duration-150',
    VARIANT[variant],
    SIZE[size],
    className,
  );
}
