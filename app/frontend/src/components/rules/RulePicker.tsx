import {useMemo, useState} from 'react';
import {ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight} from 'lucide-react';
import {cn} from '@/lib/utils';
import {matchesSearch} from '@/lib/format';
import type {Rule} from '@/types';
import {KindBadge, SeverityBadge} from '@/components/ui/Badge';
import {SearchInput} from '@/components/ui/Input';
import {Button} from '@/components/ui/Button';

function Pane({
  title,
  rules,
  onMove,
  onMoveAll,
  direction,
  empty,
}: {
  title: string;
  rules: Rule[];
  onMove: (id: number) => void;
  onMoveAll: (ids: number[]) => void;
  direction: 'add' | 'remove';
  empty: string;
}) {
  const [q, setQ] = useState('');
  const shown = useMemo(() => rules.filter((r) => matchesSearch(q, r.code, r.name, r.kind === 'llm' ? 'LLM' : r.kind === 'builtin' ? 'Yerleşik' : 'Regex')), [rules, q]);
  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-surface-2/30">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <span className="text-xs font-semibold text-fg">
          {title} <span className="ml-1 font-normal text-fg-subtle tnum">{rules.length}</span>
        </span>
        <Button
          size="xs"
          variant="ghost"
          disabled={!shown.length}
          onClick={() => onMoveAll(shown.map((r) => r.id))}
          icon={direction === 'add' ? <ChevronsRight className="size-3.5" /> : <ChevronsLeft className="size-3.5" />}
        >
          {direction === 'add' ? 'Görünenleri ekle' : 'Görünenleri çıkar'}
        </Button>
      </div>
      <div className="border-b border-line p-2">
        <SearchInput value={q} onChange={setQ} inputSize="sm" placeholder="Kural ara…" />
      </div>
      <ul className="h-72 overflow-y-auto p-1">
        {shown.length === 0 && <li className="px-3 py-8 text-center text-xs text-fg-subtle">{q ? 'Eşleşen kural yok' : empty}</li>}
        {shown.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => onMove(r.id)}
              className={cn(
                'group flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-surface-3/70',
                !r.enabled && 'opacity-60',
              )}
            >
              {direction === 'remove' && <ChevronLeft className="size-3.5 shrink-0 text-fg-subtle opacity-0 group-hover:opacity-100" />}
              <span className="w-24 shrink-0 truncate font-mono text-[11.5px] font-medium text-fg-muted">{r.code}</span>
              <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg">{r.name}</span>
              <KindBadge kind={r.kind} compact />
              <SeverityBadge severity={r.severity} className="w-[74px]" />
              {direction === 'add' && <ChevronRight className="size-3.5 shrink-0 text-fg-subtle opacity-0 group-hover:opacity-100" />}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Two-pane picker: available ↔ selected, with search on both sides. */
export function RulePicker({rules, value, onChange}: {rules: Rule[]; value: number[]; onChange: (ids: number[]) => void}) {
  const selected = useMemo(() => new Set(value), [value]);
  const available = rules.filter((r) => !selected.has(r.id));
  const chosen = rules.filter((r) => selected.has(r.id));
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Pane
        title="Mevcut kurallar"
        rules={available}
        direction="add"
        empty="Tüm kurallar seçildi"
        onMove={(id) => onChange([...value, id])}
        onMoveAll={(ids) => onChange([...new Set([...value, ...ids])])}
      />
      <Pane
        title="Gruptaki kurallar"
        rules={chosen}
        direction="remove"
        empty="Soldan kural ekleyin"
        onMove={(id) => onChange(value.filter((x) => x !== id))}
        onMoveAll={(ids) => onChange(value.filter((x) => !ids.includes(x)))}
      />
    </div>
  );
}
