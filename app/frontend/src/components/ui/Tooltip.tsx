import {cloneElement, isValidElement, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode, type MouseEvent, type FocusEvent} from 'react';
import {createPortal} from 'react-dom';
import {cn} from '@/lib/utils';

type Side = 'top' | 'bottom' | 'right';

/**
 * Hover/focus tooltip rendered in a portal so it never gets clipped by scroll containers.
 * The child must accept ref-less mouse/focus handlers (any DOM element or forwarding component).
 */
export function Tooltip({
  content,
  children,
  side = 'top',
  disabled,
  className,
  delay = 250,
}: {
  content: ReactNode;
  children: ReactElement;
  side?: Side;
  disabled?: boolean;
  className?: string;
  delay?: number;
}) {
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const tipRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{left: number; top: number} | null>(null);

  useLayoutEffect(() => {
    if (!anchor || !tipRef.current) return;
    const tip = tipRef.current.getBoundingClientRect();
    let left = anchor.left + anchor.width / 2 - tip.width / 2;
    let top = side === 'bottom' ? anchor.bottom + 6 : anchor.top - tip.height - 6;
    if (side === 'right') {
      left = anchor.right + 8;
      top = anchor.top + anchor.height / 2 - tip.height / 2;
    }
    if (side === 'top' && top < 4) top = anchor.bottom + 6;
    left = Math.max(6, Math.min(left, window.innerWidth - tip.width - 6));
    setPos({left, top});
  }, [anchor, side]);

  if (disabled || content === null || content === undefined || content === '' || !isValidElement(children)) return children;

  const show = (el: Element) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setAnchor(el.getBoundingClientRect()), delay);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    setAnchor(null);
    setPos(null);
  };

  const props = children.props as Record<string, unknown>;
  const child = cloneElement(children as ReactElement<Record<string, unknown>>, {
    onMouseEnter: (e: MouseEvent) => {
      (props.onMouseEnter as ((e: MouseEvent) => void) | undefined)?.(e);
      show(e.currentTarget);
    },
    onMouseLeave: (e: MouseEvent) => {
      (props.onMouseLeave as ((e: MouseEvent) => void) | undefined)?.(e);
      hide();
    },
    onFocus: (e: FocusEvent) => {
      (props.onFocus as ((e: FocusEvent) => void) | undefined)?.(e);
      show(e.currentTarget);
    },
    onBlur: (e: FocusEvent) => {
      (props.onBlur as ((e: FocusEvent) => void) | undefined)?.(e);
      hide();
    },
  });

  return (
    <>
      {child}
      {anchor &&
        createPortal(
          <div
            ref={tipRef}
            role="tooltip"
            style={{left: pos?.left ?? -9999, top: pos?.top ?? -9999}}
            className={cn(
              'pointer-events-none fixed z-[100] max-w-xs animate-fade-in rounded-md border border-line-strong bg-elevated px-2 py-1 text-[11.5px] leading-4 text-fg shadow-pop',
              className,
            )}
          >
            {content}
          </div>,
          document.body,
        )}
    </>
  );
}
