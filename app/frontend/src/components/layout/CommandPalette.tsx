import {useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {useNavigate} from 'react-router';
import {useQuery} from '@tanstack/react-query';
import {api} from '@/lib/api';
import {CircleHelp, CornerDownLeft, Database, FileSearch, Layers, ListChecks, Moon, Play, Plus, Search, Sparkles, Sun} from 'lucide-react';
import {cn} from '@/lib/utils';
import {fold, RUN_STATUS_LABEL} from '@/lib/format';
import {useTheme} from '@/hooks/theme';
import {qk} from '@/hooks/queries';
import {openTour} from '@/lib/tour';
import type {AnalysisSummary, Rule} from '@/types';
import {Kbd} from '@/components/ui/Badge';
import {NAV_ITEMS} from './nav';

interface Command {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: ReactNode;
  keywords?: string;
  run: () => void;
}

export function CommandPalette({open, onClose}: {open: boolean; onClose: () => void}) {
  const navigate = useNavigate();
  const {theme, toggle} = useTheme();
  const rulesQuery = useQuery({queryKey: qk.rules, queryFn: () => api.rules.list(), enabled: open});
  const analysesQuery = useQuery({queryKey: qk.analyses, queryFn: () => api.analyses.list(), enabled: open});
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setActive(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    if (!open) return [];
    const go = (to: string) => () => navigate(to);
    const list: Command[] = [
      ...NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        return {
          id: `nav:${item.to}`,
          group: 'Git',
          label: item.label,
          icon: <Icon className="size-4" />,
          keywords: item.keywords,
          run: go(item.to),
        };
      }),
      {id: 'act:analysis', group: 'Eylemler', label: 'Yeni analiz başlat', icon: <Play className="size-4" />, keywords: 'calistir', run: go('/analyses/new')},
      {id: 'act:rule', group: 'Eylemler', label: 'Yeni kural oluştur', icon: <Plus className="size-4" />, keywords: 'regex llm', run: go('/rules?new=1')},
      {id: 'act:assistant', group: 'Eylemler', label: 'LLM ile kural oluştur', icon: <Sparkles className="size-4" />, keywords: 'asistan sihirbaz yapay zeka ornek', run: go('/rules/assistant')},
      {id: 'act:group', group: 'Eylemler', label: 'Yeni kural grubu', icon: <Layers className="size-4" />, run: go('/rule-groups?new=1')},
      {id: 'act:conn', group: 'Eylemler', label: 'Yeni bağlantı ekle', icon: <Database className="size-4" />, keywords: 'sql server', run: go('/connections?new=1')},
      {
        id: 'act:theme',
        group: 'Eylemler',
        label: theme === 'dark' ? 'Açık temaya geç' : 'Koyu temaya geç',
        icon: theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />,
        keywords: 'tema gorunum dark light',
        run: toggle,
      },
      {id: 'act:tour', group: 'Eylemler', label: 'Tanıtım turunu başlat', icon: <CircleHelp className="size-4" />, keywords: 'yardim rehber demo ogretici nasil', run: () => openTour()},
    ];
    const analyses: AnalysisSummary[] = analysesQuery.data ?? [];
    for (const a of analyses.slice(0, 8)) {
      list.push({
        id: `an:${a.id}`,
        group: 'Analizler',
        label: a.name,
        hint: `${RUN_STATUS_LABEL[a.status]} · ${a.finding_count} bulgu`,
        icon: <FileSearch className="size-4" />,
        keywords: a.connection_name,
        run: go(`/analyses/${a.id}`),
      });
    }
    const rules: Rule[] = rulesQuery.data ?? [];
    for (const r of rules) {
      list.push({
        id: `rule:${r.id}`,
        group: 'Kurallar',
        label: `${r.code} · ${r.name}`,
        icon: <ListChecks className="size-4" />,
        keywords: r.description,
        run: go(`/rules?edit=${r.id}`),
      });
    }
    return list;
  }, [open, navigate, theme, toggle, analysesQuery.data, rulesQuery.data]);

  const needle = fold(query.trim());
  const shown = useMemo(() => {
    const filtered = needle
      ? commands.filter((c) => fold(`${c.label} ${c.group} ${c.keywords ?? ''} ${c.hint ?? ''}`).includes(needle))
      : commands.filter((c) => c.group !== 'Kurallar');
    return filtered.slice(0, 40);
  }, [commands, needle]);
  const current = Math.min(active, Math.max(0, shown.length - 1));

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${current}"]`)?.scrollIntoView({block: 'nearest'});
  }, [current]);

  if (!open) return null;

  const runAt = (index: number) => {
    const command = shown[index];
    if (!command) return;
    onClose();
    command.run();
  };

  let lastGroup = '';
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-start justify-center p-4 pt-[12vh]">
      <div className="fixed inset-0 animate-fade-in bg-black/50 backdrop-blur-[3px]" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Komut paleti"
        className="relative w-full max-w-xl animate-pop-in overflow-hidden rounded-2xl border border-line-strong bg-elevated/95 shadow-pop backdrop-blur-xl"
      >
        <div className="hairline-top absolute inset-x-0 top-0 h-px" />
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search className="size-4 shrink-0 text-fg-subtle" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setActive((current + 1) % Math.max(1, shown.length));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActive((current - 1 + shown.length) % Math.max(1, shown.length));
              } else if (e.key === 'Enter') {
                e.preventDefault();
                runAt(current);
              } else if (e.key === 'Escape') {
                e.preventDefault();
                onClose();
              }
            }}
            placeholder="Sayfa, eylem, analiz veya kural ara…"
            className="h-12 flex-1 bg-transparent text-sm text-fg placeholder:text-fg-subtle focus:outline-none"
            aria-label="Komut ara"
          />
          <Kbd>Esc</Kbd>
        </div>
        <div ref={listRef} className="max-h-[50vh] overflow-y-auto p-1.5">
          {shown.length === 0 && <div className="px-3 py-10 text-center text-[13px] text-fg-subtle">“{query}” için sonuç yok</div>}
          {shown.map((c, i) => {
            const header = c.group !== lastGroup ? c.group : null;
            lastGroup = c.group;
            return (
              <div key={c.id}>
                {header && <div className="px-2.5 pt-2.5 pb-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-fg-subtle">{header}</div>}
                <button
                  type="button"
                  data-index={i}
                  onMouseMove={() => setActive(i)}
                  onClick={() => runAt(i)}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors duration-75',
                    i === current ? 'bg-surface-3 text-fg' : 'text-fg-muted',
                  )}
                >
                  <span className={cn('flex', i === current ? 'text-accent' : 'text-fg-subtle')}>{c.icon}</span>
                  <span className="min-w-0 flex-1 truncate">{c.label}</span>
                  {c.hint && <span className="shrink-0 text-[11.5px] text-fg-subtle">{c.hint}</span>}
                  {i === current && <CornerDownLeft className="size-3.5 shrink-0 text-fg-subtle" />}
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-4 border-t border-line bg-surface-2/50 px-4 py-2 text-[11px] text-fg-subtle">
          <span className="flex items-center gap-1.5">
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> gezin
          </span>
          <span className="flex items-center gap-1.5">
            <Kbd>↵</Kbd> çalıştır
          </span>
          <span className="ml-auto">DWH Code Review</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
