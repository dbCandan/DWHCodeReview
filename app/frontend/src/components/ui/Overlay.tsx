import {useEffect, useRef, type ReactNode, type RefObject} from 'react';
import {createPortal} from 'react-dom';
import {X} from 'lucide-react';
import {cn} from '@/lib/utils';
import {Button} from './Button';

/** Stack of open overlays so Esc closes only the topmost one. */
const stack: symbol[] = [];

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useOverlay(open: boolean, onClose: () => void, panel: RefObject<HTMLDivElement | null>) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const id = Symbol('overlay');
    stack.push(id);
    const previous = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => {
      const root = panel.current;
      if (!root) return;
      if (root.contains(document.activeElement)) return;
      const preferred = root.querySelector<HTMLElement>('[data-autofocus]') ?? root.querySelector<HTMLElement>('input, textarea, select');
      (preferred ?? root).focus({preventScroll: true});
    });
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== id) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        closeRef.current();
      } else if (e.key === 'Tab' && panel.current) {
        const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null);
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('keydown', onKey);
      const index = stack.indexOf(id);
      if (index >= 0) stack.splice(index, 1);
      if (!stack.length) document.body.style.overflow = overflow;
      previous?.focus?.({preventScroll: true});
    };
  }, [open, panel]);
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  icon,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  icon?: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useOverlay(open, onClose, panel);
  if (!open) return null;
  const width = {sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl'}[size];
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 pt-[10vh]">
      <div className="fixed inset-0 animate-fade-in bg-black/55 backdrop-blur-[2px]" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={cn(
          'relative w-full animate-pop-in rounded-xl border border-line-strong bg-elevated shadow-pop outline-none',
          width,
        )}
      >
        <div className="flex items-start gap-3 px-5 pt-4 pb-3">
          {icon && <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-line bg-surface-2">{icon}</div>}
          <div className="min-w-0 flex-1">
            <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-fg">{title}</h2>
            {description && <p className="mt-1 text-[12.5px] leading-5 text-fg-subtle">{description}</p>}
          </div>
          <Button variant="ghost" size="sm" iconOnly aria-label="Kapat" onClick={onClose} className="-mr-2 -mt-1">
            <X className="size-4" />
          </Button>
        </div>
        {children && <div className="px-5 pb-4">{children}</div>}
        {footer && <div className="flex items-center justify-end gap-2 rounded-b-xl border-t border-line bg-surface-2/40 px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = 'max-w-2xl',
  headerExtra,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
  headerExtra?: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useOverlay(open, onClose, panel);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="fixed inset-0 animate-fade-in bg-black/50 backdrop-blur-[2px]" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={cn(
          'relative flex h-full w-full animate-slide-in flex-col border-l border-line-strong bg-elevated shadow-pop outline-none',
          width,
        )}
      >
        <div className="flex items-start gap-3 border-b border-line px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-fg">{title}</h2>
            {description && <div className="mt-0.5 text-[12.5px] text-fg-subtle">{description}</div>}
          </div>
          {headerExtra}
          <Button variant="ghost" size="sm" iconOnly aria-label="Kapat" onClick={onClose} className="-mr-2">
            <X className="size-4" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t border-line bg-surface-2/40 px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
