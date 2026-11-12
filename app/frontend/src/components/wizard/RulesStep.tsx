import {useMemo, useState} from 'react';
import {Link} from 'react-router';
import {CheckCheck, ChevronDown, ChevronsDownUp, ChevronsUpDown, Gauge, Layers, List, ListChecks, Sparkles, Timer, X, Zap} from 'lucide-react';
import {useGroups, useLlmSettings, useRules} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {formatNumber, matchesSearch} from '@/lib/format';
import {countBySeverity, SEVERITIES, SEVERITY_LABEL} from '@/lib/severity';
import {effectiveRules} from '@/lib/wizard';
import {estimateCheckSplit, formatLlmEstimate, LLM_SECONDS_PER_CHECK} from '@/lib/rules';
import type {DbObject, Rule, Severity} from '@/types';
import {Card} from '@/components/ui/Card';
import {SearchInput} from '@/components/ui/Input';
import {Checkbox} from '@/components/ui/Switch';
import {KindBadge, SeverityBadge} from '@/components/ui/Badge';
import {SeverityBar} from '@/components/ui/Charts';
import {Chip, Segmented} from '@/components/ui/Tabs';
import {Button, buttonClass} from '@/components/ui/Button';
import {Alert, EmptyState, ErrorState, Skeleton} from '@/components/ui/Feedback';

interface Section {
  key: string;
  name: string;
  description: string;
  color: string | null;
  rules: Rule[];
}

export function RulesStep({
  groupIds,
  onGroupIds,
  ruleIds,
  onRuleIds,
  pool = [],
  compact = false,
}: {
  groupIds: number[];
  onGroupIds: (ids: number[]) => void;
  ruleIds: number[];
  onRuleIds: (ids: number[]) => void;
  pool?: DbObject[];
  /** Hide the right-hand summary/estimate card (embedded use, e.g. the schedule editor). */
  compact?: boolean;
}) {
  const rules = useRules();
  const groups = useGroups();
  const llm = useLlmSettings();
  const [q, setQ] = useState('');
  const [sev, setSev] = useState<Severity | null>(null);
  const [view, setView] = useState<'grouped' | 'flat'>('grouped');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const effective = useMemo(() => effectiveRules(rules.data ?? [], groups.data ?? [], groupIds, ruleIds), [rules.data, groups.data, groupIds, ruleIds]);
  // Selection is kept per rule: a rule that sits in several groups has one checkbox state everywhere.
  const selected = useMemo(() => new Set(effective.map((r) => r.id)), [effective]);
  const setSelection = (ids: Iterable<number>) => {
    onGroupIds([]);
    onRuleIds([...new Set(ids)]);
  };
  const hasLlm = effective.some((r) => r.kind === 'llm');
  const enabledRules = useMemo(() => (rules.data ?? []).filter((r) => r.enabled), [rules.data]);
  const allSelected = enabledRules.length > 0 && enabledRules.every((r) => selected.has(r.id));
  const estimate = useMemo(() => estimateCheckSplit(pool, effective), [pool, effective]);
  const selectAll = () => setSelection(enabledRules.map((r) => r.id));
  const clearSelection = () => setSelection([]);
  const dropLlm = () => setSelection(effective.filter((r) => r.kind !== 'llm').map((r) => r.id));
  const toggleRule = (r: Rule) => {
    if (!r.enabled) return;
    const next = new Set(selected);
    if (next.has(r.id)) next.delete(r.id);
    else next.add(r.id);
    setSelection(next);
  };
  const toggleMany = (list: Rule[], on: boolean) => {
    const next = new Set(selected);
    for (const r of list) {
      if (!r.enabled) continue;
      if (on) next.add(r.id);
      else next.delete(r.id);
    }
    setSelection(next);
  };

  const filtering = q.trim() !== '' || sev !== null;
  const shownRules = useMemo(
    () => (rules.data ?? []).filter((r) => (!sev || r.severity === sev) && matchesSearch(q, r.code, r.name, r.description)),
    [rules.data, q, sev],
  );
  const shownIds = useMemo(() => new Set(shownRules.map((r) => r.id)), [shownRules]);
  const sections = useMemo(() => {
    const byId = new Map((rules.data ?? []).map((r) => [r.id, r]));
    // The quick-scan group (no LLM) is the usual first pick, so it leads the list.
    const quickFirst = (name: string) => (name.toLocaleLowerCase('tr').startsWith('hızlı tarama') ? 0 : 1);
    const ordered = [...(groups.data ?? [])].sort((a, b) => quickFirst(a.name) - quickFirst(b.name));
    const list: Section[] = ordered.map((g) => ({
      key: `g${g.id}`,
      name: g.name,
      description: g.description,
      color: g.color,
      rules: g.rule_ids.map((id) => byId.get(id)).filter((r): r is Rule => r !== undefined),
    }));
    const grouped = new Set((groups.data ?? []).flatMap((g) => g.rule_ids));
    const loose = (rules.data ?? []).filter((r) => !grouped.has(r.id));
    if (loose.length > 0) list.push({key: 'none', name: 'Grupsuz kurallar', description: 'Hiçbir gruba atanmamış kurallar.', color: null, rules: loose});
    return list;
  }, [rules.data, groups.data]);
  const visibleSections = filtering ? sections.filter((s) => s.rules.some((r) => shownIds.has(r.id))) : sections;
  const isOpen = (key: string) => filtering || expanded.has(key);
  const toggleSection = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const allExpanded = sections.length > 0 && sections.every((s) => expanded.has(s.key));

  if (rules.isPending || groups.isPending)
    return (
      <div className="grid gap-4">
        <Skeleton className="h-16 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    );
  if (rules.isError) return <Card><ErrorState error={rules.error} onRetry={() => rules.refetch()} /></Card>;
  if ((rules.data ?? []).length === 0)
    return (
      <Card>
        <EmptyState
          icon={<ListChecks />}
          title="Henüz kural yok"
          description="Analiz için en az bir etkin kural gerekir."
          action={
            <Link to="/rules?new=1" className={buttonClass('primary', 'sm')}>
              Kural oluştur
            </Link>
          }
        />
      </Card>
    );

  return (
    <div className={cn('grid items-start gap-4', !compact && 'xl:grid-cols-[minmax(0,1fr)_300px]')}>
      <Card className="min-w-0 overflow-hidden">
        {/* Toolbar: selection state + bulk actions */}
        <div
          className={cn(
            'flex flex-wrap items-center gap-3 border-b px-4 py-3',
            allSelected ? 'border-accent/30 bg-accent-soft/40' : effective.length === 0 ? 'border-warn/35 bg-warn-soft/50' : 'border-line',
          )}
        >
          <span
            className={cn(
              'flex size-8 shrink-0 items-center justify-center rounded-lg border',
              allSelected ? 'border-accent/30 bg-accent-soft text-accent' : 'border-line-strong bg-surface-2 text-fg-muted',
            )}
          >
            {allSelected ? <CheckCheck className="size-4" /> : <ListChecks className="size-4" />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-fg">
              {allSelected
                ? `Tüm etkin kurallar seçili (${enabledRules.length})`
                : effective.length === 0
                  ? 'Hiç kural seçili değil'
                  : `${effective.length} / ${enabledRules.length} etkin kural seçili`}
            </p>
            <p className="text-[11.5px] text-fg-subtle">Grup başlığındaki kutu grubun tüm kurallarını seçer; başlığa tıklayınca kurallar açılır.</p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button size="sm" variant="secondary" icon={<CheckCheck className="size-3.5" />} onClick={selectAll} disabled={allSelected}>
              Tümünü seç
            </Button>
            <Button size="sm" variant="secondary" icon={<X className="size-3.5" />} onClick={clearSelection} disabled={effective.length === 0}>
              Tümünü kaldır
            </Button>
          </div>
        </div>

        {/* Filters + view */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
          <SearchInput value={q} onChange={setQ} placeholder="Kural ara…" className="w-full sm:w-60" />
          {SEVERITIES.map((s) => (
            <Chip key={s} active={sev === s} onClick={() => setSev(sev === s ? null : s)}>
              {SEVERITY_LABEL[s]}
            </Chip>
          ))}
          <span className="ml-auto flex items-center gap-1.5">
            {view === 'grouped' && !filtering && (
              <Button
                size="sm"
                variant="ghost"
                icon={allExpanded ? <ChevronsDownUp className="size-3.5" /> : <ChevronsUpDown className="size-3.5" />}
                onClick={() => setExpanded(allExpanded ? new Set() : new Set(sections.map((s) => s.key)))}
              >
                {allExpanded ? 'Tümünü daralt' : 'Tümünü genişlet'}
              </Button>
            )}
            <Segmented
              size="sm"
              value={view}
              onChange={setView}
              options={[
                {value: 'grouped', label: 'Gruplu', icon: <Layers className="size-3" />},
                {value: 'flat', label: 'Düz liste', icon: <List className="size-3" />},
              ]}
            />
          </span>
        </div>

        {view === 'grouped' ? (
          <div className="divide-y divide-line">
            {visibleSections.length === 0 && <p className="px-4 py-8 text-center text-xs text-fg-subtle">Eşleşen kural yok</p>}
            {visibleSections.map((s) => {
              const members = s.rules.filter((r) => r.enabled);
              const on = members.filter((r) => selected.has(r.id)).length;
              const open = isOpen(s.key);
              const shown = filtering ? s.rules.filter((r) => shownIds.has(r.id)) : s.rules;
              return (
                <section key={s.key}>
                  <div
                    role="button"
                    tabIndex={0}
                    aria-expanded={open}
                    onClick={() => !filtering && toggleSection(s.key)}
                    onKeyDown={(e) => {
                      if ((e.key === 'Enter' || e.key === ' ') && !filtering) {
                        e.preventDefault();
                        toggleSection(s.key);
                      }
                    }}
                    className={cn('flex cursor-pointer items-center gap-3 px-4 py-2.5 transition-colors hover:bg-surface-2/60', open && 'bg-surface-2/40')}
                  >
                    <Checkbox
                      checked={members.length > 0 && on === members.length}
                      indeterminate={on > 0 && on < members.length}
                      disabled={members.length === 0}
                      onChange={(v) => toggleMany(members, v)}
                      label={`${s.name} grubunun tümünü seç`}
                    />
                    <span className="size-2.5 shrink-0 rounded-full" style={{background: s.color ?? 'var(--color-fg-subtle)'}} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-semibold text-fg">{s.name}</span>
                      {s.description && <span className="block truncate text-[11.5px] text-fg-subtle">{s.description}</span>}
                    </span>
                    {members.some((r) => r.kind === 'llm') && (
                      <span className="hidden items-center gap-1 text-[11px] text-accent sm:flex">
                        <Sparkles className="size-3" /> LLM
                      </span>
                    )}
                    <div className="hidden w-24 shrink-0 md:block">
                      <SeverityBar counts={countBySeverity(members)} height={4} />
                    </div>
                    <span className={cn('w-14 shrink-0 text-right text-[12px] tnum', on > 0 ? 'font-semibold text-fg' : 'text-fg-subtle')}>
                      {on}/{members.length}
                    </span>
                    <ChevronDown className={cn('size-4 shrink-0 text-fg-subtle transition-transform', open && 'rotate-180', filtering && 'opacity-0')} />
                  </div>
                  {open && (
                    <ul className="divide-y divide-line border-t border-line bg-canvas/30">
                      {shown.map((r) => (
                        <RuleRow key={r.id} rule={r} on={selected.has(r.id)} onToggle={() => toggleRule(r)} inset />
                      ))}
                    </ul>
                  )}
                </section>
              );
            })}
          </div>
        ) : (
          <ul className="max-h-[560px] divide-y divide-line overflow-y-auto">
            {shownRules.map((r) => (
              <RuleRow key={r.id} rule={r} on={selected.has(r.id)} onToggle={() => toggleRule(r)} />
            ))}
            {shownRules.length === 0 && <li className="px-4 py-8 text-center text-xs text-fg-subtle">Eşleşen kural yok</li>}
          </ul>
        )}
      </Card>

      {!compact && (
      <Card className="xl:sticky xl:top-4">
        <div className="relative p-4">
          <div className="hairline-top absolute inset-x-0 top-0 h-px" />
          <p className="text-xs font-medium text-fg-subtle">Çalıştırılacak kurallar</p>
          <p className="mt-1 text-[28px] leading-8 font-semibold tracking-tight text-fg tnum">{effective.length}</p>
          <p className="mt-0.5 text-[11.5px] text-fg-subtle">Yalnızca etkin kurallar çalıştırılır.</p>
          <SeverityBar className="mt-3" counts={countBySeverity(effective)} />
          <ul className="mt-3 flex flex-col gap-1">
            {SEVERITIES.map((s) => {
              const n = effective.filter((r) => r.severity === s).length;
              return (
                <li key={s} className="flex items-center justify-between text-xs">
                  <SeverityBadge severity={s} />
                  <span className="text-fg tnum">{n}</span>
                </li>
              );
            })}
          </ul>
          <div className="mt-4 border-t border-line pt-3">
            <p className="flex items-center gap-1.5 text-xs font-medium text-fg-subtle">
              <Gauge className="size-3.5" />
              Tahmini kontrol {pool.length > 0 && <span className="font-normal">· {formatNumber(pool.length)} nesne</span>}
            </p>
            {pool.length === 0 ? (
              <p className="mt-1.5 text-[11.5px] text-fg-subtle">Havuza nesne eklendiğinde kontrol sayısı burada görünür.</p>
            ) : (
              <ul className="mt-2 flex flex-col gap-1.5 text-xs">
                <li className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-fg-muted">
                    <Zap className="size-3 text-ok" /> Anında (regex/yerleşik)
                  </span>
                  <span className="font-semibold text-fg tnum">{formatNumber(estimate.instant)}</span>
                </li>
                <li className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-fg-muted">
                    <Sparkles className="size-3 text-accent" /> LLM
                  </span>
                  <span className="font-semibold text-fg tnum">{formatNumber(estimate.llm)}</span>
                </li>
                {estimate.llm > 0 && (
                  <li className="mt-1 rounded-lg border border-accent/20 bg-accent-soft/40 px-2.5 py-2 text-[11.5px] text-fg-muted">
                    <span className="flex items-center gap-1.5 font-medium text-fg">
                      <Timer className="size-3 text-accent" /> LLM süresi {formatLlmEstimate(estimate.llmMaxMs)}
                    </span>
                    <span className="mt-0.5 block text-fg-subtle">
                      Kontrol başına ~{LLM_SECONDS_PER_CHECK} sn. Ön koşul ve kapsam LLM kontrollerinin çoğunu atlayabilir; bu bir üst sınırdır.
                    </span>
                  </li>
                )}
              </ul>
            )}
          </div>
          {hasLlm && llm.data && !llm.data.enabled && (
            <Alert className="mt-3" tone="warn" title="LLM ayarları devre dışı">
              Seçimde LLM kuralı var; analiz başlatılamaz.
              <span className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
                <button type="button" onClick={dropLlm} className="font-medium text-accent hover:underline">
                  LLM kurallarını çıkar
                </button>
                <Link to="/settings" className="font-medium text-accent hover:underline">
                  Ayarlara git
                </Link>
              </span>
            </Alert>
          )}
          {hasLlm && llm.data?.enabled && (
            <p className="mt-3 text-[11.5px] leading-4 text-fg-subtle">
              <Sparkles className="mr-1 inline size-3 align-[-2px] text-accent" /> LLM kuralları <span className="font-mono break-all">{llm.data.model}</span> ile çalışacak.
            </p>
          )}
        </div>
      </Card>
      )}
    </div>
  );
}

function RuleRow({rule: r, on, onToggle, inset}: {rule: Rule; on: boolean; onToggle: () => void; inset?: boolean}) {
  return (
    <li>
      <div
        role="button"
        tabIndex={r.enabled ? 0 : -1}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === ' ' || e.key === 'Enter') {
            e.preventDefault();
            onToggle();
          }
        }}
        className={cn(
          'flex items-center gap-3 py-2 pr-4 transition-colors',
          inset ? 'pl-11' : 'pl-4',
          r.enabled ? 'cursor-pointer hover:bg-surface-2/60' : 'opacity-60',
          on && 'bg-accent-soft',
        )}
      >
        <Checkbox checked={on} disabled={!r.enabled} onChange={onToggle} label={r.code} />
        <span className="w-28 shrink-0 font-mono text-[12px] font-medium whitespace-nowrap text-fg">{r.code}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] text-fg">{r.name}</span>
          {r.description && <span className="block truncate text-[11.5px] text-fg-subtle">{r.description}</span>}
        </span>
        {!r.enabled && <span className="text-[11px] text-fg-subtle">devre dışı</span>}
        <KindBadge kind={r.kind} />
        <SeverityBadge severity={r.severity} />
      </div>
    </li>
  );
}
