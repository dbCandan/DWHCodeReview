import {useId, useMemo, useState, type ReactNode} from 'react';
import {Check, ChevronDown} from 'lucide-react';
import {cn} from '@/lib/utils';
import {fieldBase} from './Input';
import {Popover} from './Select';

/**
 * Free-text input with a themed suggestion list (replaces the browser's unstyled <datalist>).
 * Opening the list shows every option; typing filters it. The value is never restricted to the options.
 */
export function Combobox({
  value,
  onChange,
  options,
  placeholder,
  mono,
  emptyText = 'Öneri yok',
  onOpen,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder?: string;
  mono?: boolean;
  emptyText?: ReactNode;
  /** Called whenever the list opens (e.g. to lazy-load options). */
  onOpen?: () => void;
  className?: string;
}) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<string | null>(null); // null → show all
  const [active, setActive] = useState(0);

  const visible = useMemo(() => {
    if (!filter) return options;
    const q = filter.toLocaleLowerCase('tr');
    return options.filter((o) => o.toLocaleLowerCase('tr').includes(q));
  }, [options, filter]);

  const show = () => {
    if (!open) {
      setOpen(true);
      setFilter(null);
      setActive(Math.max(0, options.indexOf(value)));
      onOpen?.();
    }
  };
  const close = () => {
    setOpen(false);
    setFilter(null);
  };
  const choose = (option: string) => {
    onChange(option);
    close();
  };

  return (
    <Popover
      open={open}
      onClose={close}
      matchWidth
      className={cn('max-h-64 overflow-y-auto p-1', className)}
      trigger={
        <div className="relative">
          <input
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-autocomplete="list"
            value={value}
            placeholder={placeholder}
            spellCheck={false}
            onFocus={show}
            onClick={show}
            onChange={(e) => {
              onChange(e.target.value);
              setFilter(e.target.value);
              setActive(0);
              if (!open) setOpen(true);
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (!open) return show();
                setActive((i) => Math.min(i + 1, visible.length - 1));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActive((i) => Math.max(i - 1, 0));
              } else if (e.key === 'Enter' && open && visible[active]) {
                e.preventDefault();
                choose(visible[active]);
              } else if (e.key === 'Tab') {
                close();
              }
            }}
            className={cn(fieldBase, 'h-8 w-full pr-8 pl-2.5', mono && 'font-mono text-[12.5px]')}
          />
          <button
            type="button"
            tabIndex={-1}
            aria-label="Listeyi aç"
            onClick={() => (open ? close() : show())}
            className="absolute top-1/2 right-1 flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-fg-subtle transition-colors hover:bg-surface-3 hover:text-fg"
          >
            <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
          </button>
        </div>
      }
    >
      <ul id={listId} role="listbox">
        {visible.length === 0 ? (
          <li className="px-2.5 py-2 text-[12px] text-fg-subtle">{emptyText}</li>
        ) : (
          visible.map((option, i) => {
            const selected = option === value;
            return (
              <li key={option} role="option" aria-selected={selected}>
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(option)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition-colors',
                    mono && 'font-mono',
                    i === active ? 'bg-surface-3 text-fg' : 'text-fg-muted',
                    selected && 'text-fg',
                  )}
                >
                  <Check className={cn('size-3.5 shrink-0 text-accent', !selected && 'invisible')} />
                  <span className="truncate">{option}</span>
                </button>
              </li>
            );
          })
        )}
      </ul>
    </Popover>
  );
}
