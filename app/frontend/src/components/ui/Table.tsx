import type {HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes} from 'react';
import {ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown} from 'lucide-react';
import {cn} from '@/lib/utils';
import {Button} from './Button';

export function Table({className, children}: {className?: string; children: ReactNode}) {
  return (
    <div className={cn('w-full overflow-x-auto', className)}>
      <table className="w-full border-separate border-spacing-0 text-left text-[13px]">{children}</table>
    </div>
  );
}

export function THead({children, sticky}: {children: ReactNode; sticky?: boolean}) {
  return <thead className={cn(sticky && 'sticky top-0 z-10')}>{children}</thead>;
}

export function Th({className, children, ...rest}: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'h-8 whitespace-nowrap border-b border-line-strong bg-surface-2 px-3 text-[11px] font-semibold uppercase tracking-[0.04em] text-fg-muted first:pl-4 last:pr-4',
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function SortTh<K extends string>({
  label,
  sortKey,
  active,
  dir,
  onSort,
  className,
}: {
  label: ReactNode;
  sortKey: K;
  active: K;
  dir: 'asc' | 'desc';
  onSort: (key: K) => void;
  className?: string;
}) {
  const isActive = sortKey === active;
  return (
    <Th className={className} aria-sort={isActive ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn('-mx-1 inline-flex items-center gap-1 rounded px-1 uppercase transition-colors hover:text-fg', isActive && 'text-fg')}
      >
        {label}
        {isActive ? (
          dir === 'asc' ? (
            <ArrowUp className="size-3" />
          ) : (
            <ArrowDown className="size-3" />
          )
        ) : (
          <ChevronsUpDown className="size-3 opacity-50" />
        )}
      </button>
    </Th>
  );
}

export function Tr({className, children, interactive, selected, ...rest}: HTMLAttributes<HTMLTableRowElement> & {interactive?: boolean; selected?: boolean}) {
  return (
    <tr
      className={cn(
        'group/row transition-colors duration-100',
        interactive && 'cursor-pointer hover:bg-surface-2',
        selected && 'bg-accent-soft hover:bg-accent-soft [&>td:first-child]:shadow-[inset_3px_0_0_var(--color-accent)]',
        className,
      )}
      {...rest}
    >
      {children}
    </tr>
  );
}

export function Td({className, children, ...rest}: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn('h-10 border-b border-line px-3 align-middle first:pl-4 last:pr-4', className)} {...rest}>
      {children}
    </td>
  );
}

export function Pagination({
  page,
  pageCount,
  onPage,
  total,
  pageSize,
}: {
  page: number;
  pageCount: number;
  onPage: (page: number) => void;
  total: number;
  pageSize: number;
}) {
  if (total === 0) return null;
  const from = page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2 text-xs text-fg-subtle">
      <span className="tnum">
        {from.toLocaleString('tr-TR')}–{to.toLocaleString('tr-TR')} / {total.toLocaleString('tr-TR')}
      </span>
      <div className="flex items-center gap-1">
        <Button size="xs" variant="ghost" iconOnly aria-label="Önceki sayfa" disabled={page <= 0} onClick={() => onPage(page - 1)}>
          <ChevronLeft className="size-3.5" />
        </Button>
        <span className="min-w-14 text-center tnum">
          {page + 1} / {Math.max(1, pageCount)}
        </span>
        <Button
          size="xs"
          variant="ghost"
          iconOnly
          aria-label="Sonraki sayfa"
          disabled={page >= pageCount - 1}
          onClick={() => onPage(page + 1)}
        >
          <ChevronRight className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}
