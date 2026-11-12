import {useMemo, useState} from 'react';
import {useNavigate} from 'react-router';
import {useMutation, useQueryClient} from '@tanstack/react-query';
import {ArrowLeft, ArrowRight, CalendarClock, Boxes, Database, Layers, ListChecks, Play, Rocket, Server, Sparkles, Timer, X, Zap} from 'lucide-react';
import {api, errorMessage} from '@/lib/api';
import {qk, useConnections, useGroups, useLlmSettings, useRules} from '@/hooks/queries';
import {formatNumber} from '@/lib/format';
import {mergePool, removeFromPool} from '@/lib/pool';
import {EMPTY_FILTER, effectiveRules, type FilterForm, type PoolQueryLog} from '@/lib/wizard';
import {estimateCheckSplit, formatLlmEstimate} from '@/lib/rules';
import {scheduleFromWizard} from '@/lib/schedules';
import {hexAlpha} from '@/lib/utils';
import type {DbObject, ObjectQuery} from '@/types';
import {PageHeader} from '@/components/layout/AppShell';
import {Stepper} from '@/components/ui/Progress';
import {Button} from '@/components/ui/Button';
import {Card, CardHeader} from '@/components/ui/Card';
import {Field, Input} from '@/components/ui/Input';
import {Alert} from '@/components/ui/Feedback';
import {SeverityDot} from '@/components/ui/Badge';
import {useFeedback} from '@/components/ui/Toast';
import {SourceStep} from '@/components/wizard/SourceStep';
import {PoolStep, QueryChips} from '@/components/wizard/PoolStep';
import {RulesStep} from '@/components/wizard/RulesStep';

const STEPS = [
  {title: 'Kaynak', description: 'Bağlantı ve veritabanı'},
  {title: 'Nesne Havuzu', description: 'Filtrele ve ekle'},
  {title: 'Kurallar', description: 'Grup ve kural seçimi'},
  {title: 'Özet', description: 'Gözden geçir ve başlat'},
];

export function NewAnalysisPage() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const feedback = useFeedback();
  const connections = useConnections();
  const rules = useRules();
  const groups = useGroups();
  const llm = useLlmSettings();

  const [step, setStep] = useState(0);
  const [connectionId, setConnectionId] = useState<number | null>(null);
  const [databases, setDatabases] = useState<string[]>([]);
  const [filter, setFilter] = useState<FilterForm>(EMPTY_FILTER);
  const [pool, setPool] = useState<DbObject[]>([]);
  const [queries, setQueries] = useState<PoolQueryLog[]>([]);
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [ruleIds, setRuleIds] = useState<number[]>([]);
  // Default selection: every enabled rule (applied once, as soon as the rule list is known).
  const [rulesInitialized, setRulesInitialized] = useState(false);
  if (!rulesInitialized && rules.data) {
    setRulesInitialized(true);
    setRuleIds(rules.data.filter((r) => r.enabled).map((r) => r.id));
  }
  const [name, setName] = useState('');

  const effective = useMemo(() => effectiveRules(rules.data ?? [], groups.data ?? [], groupIds, ruleIds), [rules.data, groups.data, groupIds, ruleIds]);
  const llmBlocked = effective.some((r) => r.kind === 'llm') && llm.data !== undefined && !llm.data.enabled;
  // Groups whose every enabled rule is selected (shown on the summary step).
  const coveredGroups = useMemo(() => {
    const on = new Set(effective.map((r) => r.id));
    const enabled = new Set((rules.data ?? []).filter((r) => r.enabled).map((r) => r.id));
    return (groups.data ?? []).filter((g) => {
      const members = g.rule_ids.filter((id) => enabled.has(id));
      return members.length > 0 && members.every((id) => on.has(id));
    });
  }, [effective, rules.data, groups.data]);
  const valid = [connectionId !== null && databases.length > 0, pool.length > 0, effective.length > 0 && !llmBlocked, true];
  const maxReachable = valid.findIndex((v) => !v) === -1 ? 3 : valid.findIndex((v) => !v);
  const connection = connections.data?.find((c) => c.id === connectionId);

  const changeConnection = (id: number) => {
    if (id === connectionId) return;
    if (pool.length) feedback.info('Havuz temizlendi', 'Bağlantı değiştiği için havuzdaki nesneler kaldırıldı.');
    setConnectionId(id);
    setDatabases([]);
    setPool([]);
    setQueries([]);
    setFilter(EMPTY_FILTER);
  };

  const onAdd = (items: DbObject[], query: ObjectQuery, matched: number) => {
    const result = mergePool(pool, items);
    setPool(result.pool);
    setQueries((q) => [
      ...q,
      {
        databases: query.databases,
        schemas: query.schemas ?? [],
        types: query.types ?? [],
        created_from: query.created_from ?? null,
        created_to: query.created_to ?? null,
        modified_from: query.modified_from ?? null,
        modified_to: query.modified_to ?? null,
        search: query.search ?? null,
        matched,
        added: result.added,
      },
    ]);
    if (result.added)
      feedback.success(`${formatNumber(result.added)} nesne havuza eklendi`, result.skipped ? `${formatNumber(result.skipped)} nesne zaten havuzdaydı.` : undefined);
    else feedback.info('Yeni nesne eklenmedi', 'Seçilen nesnelerin tamamı zaten havuzda.');
  };

  const estimate = useMemo(() => estimateCheckSplit(pool, effective), [pool, effective]);
  const checks = estimate.total;

  const start = useMutation({
    mutationFn: () =>
      api.analyses.create({
        name: name.trim() || undefined,
        connection_id: connectionId!,
        objects: pool.map(({database, schema, name, type}) => ({database, schema, name, type})),
        group_ids: groupIds,
        rule_ids: ruleIds,
        filters: {
          connection: connection?.name,
          databases,
          queries: queries.filter((q) => q.added > 0),
          group_ids: groupIds,
          rule_ids: ruleIds,
        },
      }),
    onSuccess: (a) => {
      client.invalidateQueries({queryKey: qk.analyses});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success('Analiz başlatıldı', a.name);
      navigate(`/analyses/${a.id}`);
    },
  });

  const go = (to: number) => setStep(Math.max(0, Math.min(to, maxReachable)));

  return (
    <div className="flex min-h-[calc(100dvh-3.5rem-3rem)] animate-fade-in flex-col lg:min-h-[calc(100dvh-3.5rem-3.5rem)]">
      <PageHeader title="Yeni Analiz" description="Kaynağı seçin, nesne havuzunu oluşturun, kuralları belirleyin ve analizi başlatın." />
      <Card data-tour="wizard-steps" className="mb-5 px-4 py-3">
        <Stepper steps={STEPS} current={step} onStep={go} maxReachable={maxReachable} />
      </Card>

      <div key={step} className="mb-6 animate-pop-in">
        {step === 0 && <SourceStep connectionId={connectionId} onConnection={changeConnection} databases={databases} onDatabases={setDatabases} />}
        {step === 1 && connectionId !== null && (
          <PoolStep
            connectionId={connectionId}
            databases={databases}
            filter={filter}
            onFilter={setFilter}
            pool={pool}
            onAdd={onAdd}
            onRemove={(keys) => setPool((p) => removeFromPool(p, keys))}
            onClear={async () => {
              if (await feedback.confirm({title: 'Havuz temizlensin mi?', description: `${formatNumber(pool.length)} nesne havuzdan çıkarılacak.`, confirmLabel: 'Temizle'})) {
                setPool([]);
                setQueries([]);
              }
            }}
          />
        )}
        {step === 2 && <RulesStep groupIds={groupIds} onGroupIds={setGroupIds} ruleIds={ruleIds} onRuleIds={setRuleIds} pool={pool} />}
        {step === 3 && (
          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
            <div className="flex min-w-0 flex-col gap-4">
              <Card>
                <CardHeader title="Analiz adı" description="Boş bırakılırsa otomatik olarak “Analiz #<id>” verilir." />
                <div className="p-4">
                  <Field label="Ad">
                    <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Örn. Aylık DWH incelemesi" maxLength={200} />
                  </Field>
                </div>
              </Card>
              <Card>
                <CardHeader icon={<Server className="size-4" />} title="Kaynak" />
                <div className="flex flex-col gap-2 p-4 text-[13px]">
                  <div className="flex items-center gap-2">
                    <span className="w-28 text-fg-subtle">Bağlantı</span>
                    <span className="font-medium text-fg">{connection?.name}</span>
                    <span className="font-mono text-xs text-fg-subtle">
                      {connection?.server}:{connection?.port}
                    </span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="w-28 shrink-0 text-fg-subtle">Veritabanları</span>
                    <span className="flex flex-wrap gap-1">
                      {databases.map((d) => (
                        <span key={d} className="inline-flex items-center gap-1 rounded-md border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[11.5px] text-fg-muted">
                          <Database className="size-3" />
                          {d}
                        </span>
                      ))}
                    </span>
                  </div>
                </div>
              </Card>
              <Card>
                <CardHeader icon={<Boxes className="size-4" />} title="Havuz sorguları" description="Havuza nesne ekleyen filtre çalıştırmaları" />
                <ul className="divide-y divide-line">
                  {queries.filter((q) => q.added > 0).map((q, i) => (
                    <li key={i} className="flex items-start gap-3 px-4 py-2.5">
                      <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-3 text-[11px] font-medium text-fg-muted tnum">{i + 1}</span>
                      <div className="min-w-0 flex-1">
                        <QueryChips query={q} />
                      </div>
                      <span className="shrink-0 text-xs text-fg-subtle tnum">
                        +{formatNumber(q.added)} <span className="text-fg-subtle/70">/ {formatNumber(q.matched)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
              <Card>
                <CardHeader icon={<ListChecks className="size-4" />} title="Kurallar" description={`${effective.length} kural seçili`} />
                <div className="flex flex-col gap-3 p-4">
                  {coveredGroups.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {coveredGroups.map((g) => (
                          <span
                            key={g.id}
                            className="inline-flex h-6 items-center gap-1.5 rounded-md border px-2 text-xs font-medium text-fg"
                            style={{borderColor: hexAlpha(g.color, 0.4), background: hexAlpha(g.color, 0.1)}}
                          >
                            <Layers className="size-3" style={{color: g.color}} />
                            {g.name}
                          </span>
                        ))}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-1.5">
                    {effective.map((r) => (
                      <span key={r.id} className="inline-flex h-6 items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 text-[11.5px]">
                        <SeverityDot severity={r.severity} className="size-1.5" />
                        <span className="font-mono font-medium text-fg">{r.code}</span>
                        {r.kind === 'llm' && <Sparkles className="size-3 text-accent" />}
                        {r.kind === 'builtin' && <span className="text-[10px] font-medium text-builtin">Y</span>}
                      </span>
                    ))}
                  </div>
                </div>
              </Card>
            </div>

            <Card className="relative overflow-hidden lg:sticky lg:top-4">
              <div className="pointer-events-none absolute -top-20 -right-10 size-56 rounded-full bg-accent/15 blur-3xl" />
              <div className="relative p-5">
                <span className="flex size-9 items-center justify-center rounded-lg border border-accent/30 bg-accent-soft text-accent">
                  <Rocket className="size-4" />
                </span>
                <p className="mt-4 text-xs font-medium text-fg-subtle">Kapsam</p>
                <div className="mt-2 flex items-baseline gap-2 text-fg">
                  <span className="text-[26px] font-semibold tracking-tight tnum">{formatNumber(pool.length)}</span>
                  <span className="text-xs text-fg-subtle">nesne</span>
                  <X className="size-4 self-center text-fg-subtle" />
                  <span className="text-[26px] font-semibold tracking-tight tnum">{formatNumber(effective.length)}</span>
                  <span className="text-xs text-fg-subtle">kural</span>
                </div>
                <div className="mt-1 text-[13px] text-fg-muted">
                  = <span className="font-semibold text-fg tnum">~{formatNumber(checks)}</span> kontrol
                </div>
                <p className="mt-1 text-[11.5px] text-fg-subtle">Kuralın kapsamına (nesne tipi, veritabanı, ad deseni) uymayan eşleşmeler atlanır.</p>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="rounded-lg border border-line bg-surface-2/50 px-3 py-2">
                    <p className="flex items-center gap-1 text-[11px] text-fg-subtle">
                      <Zap className="size-3 text-ok" /> Anında
                    </p>
                    <p className="text-[15px] font-semibold text-fg tnum">{formatNumber(estimate.instant)}</p>
                  </div>
                  <div className="rounded-lg border border-line bg-surface-2/50 px-3 py-2">
                    <p className="flex items-center gap-1 text-[11px] text-fg-subtle">
                      <Sparkles className="size-3 text-accent" /> LLM
                    </p>
                    <p className="text-[15px] font-semibold text-fg tnum">{formatNumber(estimate.llm)}</p>
                  </div>
                </div>
                {estimate.llm > 0 && (
                  <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-fg-muted">
                    <Timer className="mt-px size-3 shrink-0 text-accent" />
                    <span>
                      LLM süresi {formatLlmEstimate(estimate.llmMaxMs)}. Ön koşul ve kapsam birçok LLM kontrolünü atlayabilir.
                    </span>
                  </p>
                )}
                {llmBlocked && (
                  <Alert tone="warn" className="mt-3" title="LLM ayarları devre dışı">
                    LLM kurallarını çıkarın veya ayarlardan etkinleştirin.
                  </Alert>
                )}
                {start.error && (
                  <Alert tone="bad" className="mt-3" title="Analiz başlatılamadı">
                    {errorMessage(start.error)}
                  </Alert>
                )}
                <Button
                  variant="primary"
                  size="lg"
                  className="mt-5 w-full"
                  loading={start.isPending}
                  disabled={!valid.slice(0, 3).every(Boolean)}
                  icon={<Play className="size-4 fill-current" />}
                  onClick={() => start.mutate()}
                >
                  Analizi Başlat
                </Button>
                <Button
                  variant="secondary"
                  className="mt-2 w-full"
                  disabled={connectionId === null || databases.length === 0}
                  icon={<CalendarClock className="size-4" />}
                  onClick={() =>
                    navigate('/schedules/new', {
                      state: {
                        prefill: scheduleFromWizard({
                          connectionId,
                          databases,
                          queries,
                          ruleIds: effective.map((r) => r.id),
                          rules: rules.data ?? [],
                          groups: groups.data ?? [],
                          name,
                        }),
                      },
                    })
                  }
                >
                  Zamanlanmış analiz olarak kaydet
                </Button>
                <p className="mt-1.5 text-[11.5px] leading-4 text-fg-subtle">Aynı kapsam ve kurallarla periyodik, artımlı çalışan bir tanım oluşturur.</p>
              </div>
            </Card>
          </div>
        )}
      </div>

      <div className="glass sticky bottom-0 z-20 -mx-4 mt-auto -mb-6 border-t border-line lg:-mx-8 lg:-mb-7">
        <div className="flex items-center gap-3 px-4 py-3 lg:px-8">
          <Button variant="ghost" icon={<ArrowLeft className="size-4" />} disabled={step === 0} onClick={() => setStep(step - 1)}>
            Geri
          </Button>
          <div className="hidden flex-1 items-center justify-center gap-4 text-xs text-fg-subtle sm:flex">
            <span>
              <span className="font-semibold text-fg tnum">{databases.length}</span> veritabanı
            </span>
            <span className="h-3 w-px bg-line-strong" />
            <span>
              <span className="font-semibold text-fg tnum">{formatNumber(pool.length)}</span> nesne
            </span>
            <span className="h-3 w-px bg-line-strong" />
            <span>
              <span className="font-semibold text-fg tnum">{effective.length}</span> kural
            </span>
          </div>
          {step < 3 ? (
            <Button variant="primary" className="ml-auto sm:ml-0" disabled={!valid[step]} onClick={() => setStep(step + 1)}>
              {step === 0 && !valid[0] ? 'Bağlantı ve veritabanı seçin' : step === 1 && !valid[1] ? 'Havuza nesne ekleyin' : step === 2 && !valid[2] ? (llmBlocked ? 'LLM ayarları kapalı' : 'En az bir kural seçin') : 'İleri'}
              <ArrowRight className="size-4" />
            </Button>
          ) : (
            <Button variant="primary" className="ml-auto sm:ml-0" loading={start.isPending} disabled={!valid.slice(0, 3).every(Boolean)} icon={<Play className="size-3.5 fill-current" />} onClick={() => start.mutate()}>
              Analizi Başlat
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
