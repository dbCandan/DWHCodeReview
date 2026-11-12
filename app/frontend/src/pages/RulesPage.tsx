import {useEffect, useMemo, useState} from 'react';
import {Link, useSearchParams} from 'react-router';
import {useMutation, useQueryClient} from '@tanstack/react-query';
import {ArrowRight, Blocks, Copy, Crosshair, Layers, ListChecks, Pencil, Plus, Regex, ShieldOff, Sparkles, Timer, Trash2} from 'lucide-react';
import {api} from '@/lib/api';
import {qk, useGroups, useRules} from '@/hooks/queries';
import {matchesSearch} from '@/lib/format';
import {builtinLabel, LLM_SECONDS_PER_CHECK, RULE_KIND_HINT, scopeShort, scopeSummary} from '@/lib/rules';
import {SEVERITIES, SEVERITY_LABEL, SEVERITY_RANK} from '@/lib/severity';
import {ruleToInput, toRulePayload} from '@/components/rules/RuleEditor';
import type {Rule, RuleGroup, RuleKind, Severity} from '@/types';
import {PageHeader} from '@/components/layout/AppShell';
import {RuleEditor} from '@/components/rules/RuleEditor';
import {Button, buttonClass} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {SearchInput} from '@/components/ui/Input';
import {Select} from '@/components/ui/Select';
import {Table, THead, Th, Tr, Td} from '@/components/ui/Table';
import {ColorDot, KindBadge, SeverityBadge} from '@/components/ui/Badge';
import {Switch} from '@/components/ui/Switch';
import {Tooltip} from '@/components/ui/Tooltip';
import {EmptyState, ErrorState, SkeletonRows} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';

export function RulesPage() {
  const rules = useRules();
  const groups = useGroups();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState<Rule | 'new' | null>(null);
  const [q, setQ] = useState('');
  const [severity, setSeverity] = useState<Severity | ''>('');
  const [kind, setKind] = useState<RuleKind | ''>('');
  const [groupId, setGroupId] = useState('');
  const [status, setStatus] = useState<'' | 'on' | 'off'>('');
  const client = useQueryClient();
  const feedback = useFeedback();

  useEffect(() => {
    if (params.get('new') === '1') {
      setEditing('new');
      params.delete('new');
      setParams(params, {replace: true});
    }
    const editId = params.get('edit');
    if (editId && rules.data) {
      const found = rules.data.find((r) => r.id === Number(editId));
      if (found) setEditing(found);
      params.delete('edit');
      setParams(params, {replace: true});
    }
  }, [params, setParams, rules.data]);

  const filtered = useMemo(() => {
    const list = (rules.data ?? []).filter(
      (r) =>
        (!severity || r.severity === severity) &&
        (!kind || r.kind === kind) &&
        (!groupId || r.group_ids.includes(Number(groupId))) &&
        (!status || (status === 'on' ? r.enabled : !r.enabled)) &&
        matchesSearch(q, r.code, r.name, r.description, r.pattern, r.name_pattern, r.kind === 'builtin' ? builtinLabel(r.builtin_check) : null, ...(r.databases ?? [])),
    );
    return list.sort((a, b) => a.code.localeCompare(b.code));
  }, [rules.data, severity, kind, groupId, status, q]);

  const toggle = useMutation({
    mutationFn: (rule: Rule) => api.rules.update(rule.id, toRulePayload({...ruleToInput(rule), enabled: !rule.enabled})),
    onMutate: async (rule) => {
      await client.cancelQueries({queryKey: qk.rules});
      const previous = client.getQueryData<Rule[]>(qk.rules);
      client.setQueryData<Rule[]>(qk.rules, (list) => list?.map((r) => (r.id === rule.id ? {...r, enabled: !r.enabled} : r)));
      return {previous};
    },
    onError: (e, _rule, ctx) => {
      if (ctx?.previous) client.setQueryData(qk.rules, ctx.previous);
      feedback.error('Kural güncellenemedi', e);
    },
    onSettled: () => {
      client.invalidateQueries({queryKey: qk.rules});
      client.invalidateQueries({queryKey: qk.dashboard});
    },
  });

  const duplicate = useMutation({
    mutationFn: (rule: Rule) => api.rules.duplicate(rule.id),
    onSuccess: (copy) => {
      client.invalidateQueries({queryKey: qk.rules});
      client.invalidateQueries({queryKey: qk.groups});
      feedback.success('Kural kopyalandı', copy.code);
      setEditing(copy);
    },
    onError: (e) => feedback.error('Kural kopyalanamadı', e),
  });

  const remove = useMutation({
    mutationFn: (rule: Rule) => api.rules.remove(rule.id),
    onSuccess: () => {
      client.invalidateQueries({queryKey: qk.rules});
      client.invalidateQueries({queryKey: qk.groups});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success('Kural silindi');
    },
    onError: (e) => feedback.error('Kural silinemedi', e),
  });

  const onDelete = async (rule: Rule) => {
    if (
      await feedback.confirm({
        title: `${rule.code} silinsin mi?`,
        description: 'Kural tüm gruplardan çıkarılır. Geçmiş analizlerdeki bulgular korunur. Bu işlem geri alınamaz.',
      })
    )
      remove.mutate(rule);
  };

  const total = rules.data?.length ?? 0;
  const enabledCount = rules.data?.filter((r) => r.enabled).length ?? 0;
  const filtersActive = !!(q || severity || kind || groupId || status);

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Kurallar"
        description={
          rules.data ? `${total} kural · ${enabledCount} etkin. Regex ve yerleşik kurallar anında, LLM kuralları yapılandırılmış modelle (daha yavaş) çalışır.` : 'Statik analiz kuralları'
        }
        actions={
          <>
            <Link data-tour="rules-assistant" to="/rules/assistant" className={buttonClass('subtle', 'md', 'ring-1 ring-accent/35 ring-inset')}>
              <Sparkles className="size-4" />
              LLM ile kural oluştur
            </Link>
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>
              Yeni Kural
            </Button>
          </>
        }
      />

      <FlowStrip />

      <Card data-tour="rules-table" className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <SearchInput value={q} onChange={setQ} placeholder="Kod, ad, açıklama veya desen ara…" className="w-full sm:w-72" />
          <Select value={severity} onChange={(e) => setSeverity(e.target.value as Severity | '')} className="w-36">
            <option value="">Tüm önemler</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {SEVERITY_LABEL[s]}
              </option>
            ))}
          </Select>
          <Select value={kind} onChange={(e) => setKind(e.target.value as RuleKind | '')} className="w-32">
            <option value="">Tüm türler</option>
            <option value="regex">Regex</option>
            <option value="llm">LLM</option>
            <option value="builtin">Yerleşik</option>
          </Select>
          <Select value={groupId} onChange={(e) => setGroupId(e.target.value)} className="w-44">
            <option value="">Tüm gruplar</option>
            {(groups.data ?? []).map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </Select>
          <Select value={status} onChange={(e) => setStatus(e.target.value as '' | 'on' | 'off')} className="w-32">
            <option value="">Tüm durumlar</option>
            <option value="on">Etkin</option>
            <option value="off">Devre dışı</option>
          </Select>
          {filtersActive && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setQ('');
                setSeverity('');
                setKind('');
                setGroupId('');
                setStatus('');
              }}
            >
              Filtreleri temizle
            </Button>
          )}
          <span className="ml-auto text-xs text-fg-subtle tnum">
            {filtered.length} / {total}
          </span>
        </div>

        {rules.isPending ? (
          <SkeletonRows rows={8} />
        ) : rules.isError ? (
          <ErrorState error={rules.error} onRetry={() => rules.refetch()} />
        ) : total === 0 ? (
          <div className="flex flex-col items-center px-6 py-12 text-center">
            <span className="flex size-11 items-center justify-center rounded-xl border border-line-strong bg-gradient-to-b from-surface-3 to-surface-2 text-fg-muted shadow-card">
              <ListChecks className="size-5" />
            </span>
            <h3 className="mt-4 text-sm font-semibold text-fg">Henüz kural yok</h3>
            <p className="mt-1 max-w-md text-[12.5px] leading-5 text-fg-subtle">
              Kural, kodda neyin ihlal sayılacağını tanımlar. Üç kontrol yöntemi vardır — ihtiyacınıza en uygun olanla başlayın:
            </p>
            <div className="mt-5 grid w-full max-w-2xl gap-2 text-left sm:grid-cols-3">
              {[
                {icon: <Regex className="size-3.5" />, title: 'Regex', text: RULE_KIND_HINT.regex, cls: 'border-line-strong bg-surface-3 text-fg-muted'},
                {icon: <Sparkles className="size-3.5" />, title: 'LLM', text: RULE_KIND_HINT.llm, cls: 'border-accent/30 bg-accent-soft text-accent'},
                {icon: <Blocks className="size-3.5" />, title: 'Yerleşik', text: RULE_KIND_HINT.builtin, cls: 'border-builtin/30 bg-builtin-soft text-builtin'},
              ].map((k) => (
                <div key={k.title} className="rounded-lg border border-line bg-surface-2/40 p-3">
                  <span className="flex items-center gap-2 text-[13px] font-semibold text-fg">
                    <span className={`flex size-6 items-center justify-center rounded-md border ${k.cls}`}>{k.icon}</span>
                    {k.title}
                  </span>
                  <p className="mt-1.5 text-[11.5px] leading-4 text-fg-subtle">{k.text}</p>
                </div>
              ))}
            </div>
            <Button className="mt-5" variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>
              Kural oluştur
            </Button>
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState compact icon={<ListChecks />} title="Filtreyle eşleşen kural yok" description="Arama veya filtreleri değiştirmeyi deneyin." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th className="w-12">Etkin</Th>
                <Th className="w-28">Kod</Th>
                <Th>Ad</Th>
                <Th className="w-24">Önem</Th>
                <Th className="w-28">Tür</Th>
                <Th className="hidden w-40 lg:table-cell">Kapsam</Th>
                <Th className="w-24 text-right">İşlemler</Th>
              </tr>
            </THead>
            <tbody>
              {filtered.map((r) => (
                <Tr key={r.id} interactive onClick={() => setEditing(r)} className={r.enabled ? '' : 'opacity-60'}>
                  <Td>
                    <Switch size="sm" checked={r.enabled} onChange={() => toggle.mutate(r)} label={`${r.code} etkin`} />
                  </Td>
                  <Td>
                    <span className="flex items-center gap-1.5">
                      <span className="whitespace-nowrap font-mono text-[12px] font-medium text-fg">{r.code}</span>
                      {(r.exception_count ?? 0) > 0 && (
                        <Tooltip content={`${r.exception_count} istisna`}>
                          <span className="inline-flex h-[18px] items-center gap-0.5 rounded-md border border-line-strong bg-surface-2 px-1 text-[10.5px] font-medium text-fg-muted tnum">
                            <ShieldOff className="size-2.5" />
                            {r.exception_count}
                          </span>
                        </Tooltip>
                      )}
                    </span>
                  </Td>
                  <Td className="max-w-0">
                    <div className="truncate font-medium text-fg">{r.name}</div>
                    {(r.description || r.pattern || r.kind === 'builtin') && (
                      <div className="truncate text-[11.5px] text-fg-subtle">
                        {r.kind === 'regex' && r.pattern ? (
                          <span className="font-mono">{r.pattern}</span>
                        ) : r.kind === 'builtin' ? (
                          <span>
                            <span className="text-builtin">{builtinLabel(r.builtin_check)}</span>
                            {r.description && <span> · {r.description}</span>}
                          </span>
                        ) : (
                          r.description
                        )}
                      </div>
                    )}
                  </Td>
                  <Td>
                    <SeverityBadge severity={r.severity} />
                  </Td>
                  <Td>
                    <span className="flex items-center gap-1.5">
                      <KindBadge kind={r.kind} />
                      {r.kind === 'llm' && (
                        <Tooltip
                          content={`Yavaş: nesne başına ~${LLM_SECONDS_PER_CHECK} sn. ${r.precondition || r.metadata_precondition ? 'Ön koşul, uymayan nesneleri atlayarak hızlandırır.' : 'Ön koşul tanımlanmamış; kapsamdaki her nesne modele gönderilir.'}`}
                        >
                          <span className={r.precondition || r.metadata_precondition ? 'flex text-fg-subtle' : 'flex text-warn'}>
                            <Timer className="size-3.5" />
                          </span>
                        </Tooltip>
                      )}
                    </span>
                  </Td>
                  <Td className="hidden max-w-0 lg:table-cell">
                    <Tooltip content={scopeSummary(r)}>
                      <span className={scopeShort(r) === 'Tümü' ? 'text-xs text-fg-subtle' : 'flex min-w-0 items-center gap-1 text-[11.5px] text-fg-muted'}>
                        {scopeShort(r) !== 'Tümü' && <Crosshair className="size-3 shrink-0 text-fg-subtle" />}
                        <span className={scopeShort(r) === 'Tümü' ? '' : 'truncate'}>{scopeShort(r)}</span>
                      </span>
                    </Tooltip>
                  </Td>
                  <Td className="text-right">
                    <div className="flex justify-end gap-0.5 opacity-60 transition-opacity group-hover/row:opacity-100" onClick={(e) => e.stopPropagation()}>
                      <Tooltip content="Düzenle">
                        <Button variant="ghost" size="xs" iconOnly aria-label="Düzenle" onClick={() => setEditing(r)}>
                          <Pencil className="size-3.5" />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Kopyala">
                        <Button variant="ghost" size="xs" iconOnly aria-label="Kopyala" onClick={() => duplicate.mutate(r)}>
                          <Copy className="size-3.5" />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Sil">
                        <Button variant="ghost" size="xs" iconOnly aria-label="Sil" className="hover:text-bad" onClick={() => onDelete(r)}>
                          <Trash2 className="size-3.5" />
                        </Button>
                      </Tooltip>
                    </div>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <RuleEditor
        key={editing === 'new' ? 'new' : (editing?.id ?? 'none')}
        open={editing !== null}
        rule={editing === 'new' ? null : editing}
        onClose={() => setEditing(null)}
      />
    </div>
  );
}

const FLOW_STEPS: {title: string; text: string; optional?: boolean; to?: string}[] = [
  {title: 'Kuralı tanımla', text: 'Regex, LLM veya yerleşik kontrol; kapsamıyla birlikte.'},
  {title: 'Gruba ekle', optional: true, text: 'Birlikte çalışan kuralları tek tıkla seçmek için.', to: '/rule-groups'},
  {title: 'Yeni Analiz’de kural veya grup seç', text: 'Varsayılan: tüm etkin kurallar seçili gelir.'},
];

/** Three-step explanation of how rules reach an analysis. */
function FlowStrip() {
  return (
    <Card className="mb-4 flex flex-col gap-3 p-3 lg:flex-row lg:items-center">
      <ol className="grid flex-1 gap-2 sm:grid-cols-3">
        {FLOW_STEPS.map((step, i) => (
          <li key={step.title} className="flex items-start gap-2.5 rounded-lg px-2 py-1.5">
            <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full border border-accent/30 bg-accent-soft text-[11px] font-semibold text-accent tnum">
              {i + 1}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5 text-[12.5px] font-semibold text-fg">
                {step.to ? (
                  <Link to={step.to} className="inline-flex items-center gap-1 hover:text-accent">
                    <Layers className="size-3 text-fg-subtle" />
                    {step.title}
                  </Link>
                ) : (
                  step.title
                )}
                {step.optional && <span className="text-[11px] font-normal text-fg-subtle">(isteğe bağlı)</span>}
                {i < FLOW_STEPS.length - 1 && <ArrowRight className="ml-auto hidden size-3.5 shrink-0 text-fg-subtle sm:block" />}
              </span>
              <span className="mt-0.5 block text-[11.5px] leading-4 text-fg-subtle">{step.text}</span>
            </span>
          </li>
        ))}
      </ol>
      <Link to="/analyses/new" className={buttonClass('secondary', 'sm', 'shrink-0 self-start lg:self-center')}>
        Yeni Analiz
        <ArrowRight className="size-3.5" />
      </Link>
    </Card>
  );
}

export function GroupChips({ids, map}: {ids: number[]; map: Map<number, RuleGroup>}) {
  const list = ids.map((id) => map.get(id)).filter(Boolean) as RuleGroup[];
  if (!list.length) return <span className="text-xs text-fg-subtle">—</span>;
  const shown = list.slice(0, 2);
  return (
    <Tooltip content={list.length > 2 ? list.map((g) => g.name).join(', ') : undefined}>
      <span className="flex min-w-0 items-center gap-1">
        {shown.map((g) => (
          <span key={g.id} className="inline-flex h-5 min-w-0 items-center gap-1 rounded-md border border-line bg-surface-2 px-1.5 text-[11px] text-fg-muted">
            <ColorDot color={g.color} className="size-1.5" />
            <span className="max-w-20 truncate">{g.name}</span>
          </span>
        ))}
        {list.length > 2 && <span className="text-[11px] text-fg-subtle">+{list.length - 2}</span>}
      </span>
    </Tooltip>
  );
}

export const severitySort = (a: Rule, b: Rule) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || a.code.localeCompare(b.code);
