import {useEffect, useMemo, useState, type ReactNode} from 'react';
import {Link, useLocation, useNavigate, useParams} from 'react-router';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {ArrowLeft, CalendarClock, Check, Eye, Filter, Layers, ListChecks, ListPlus, Save, Sparkles, Trash2, TriangleAlert, X} from 'lucide-react';
import {api, ApiError} from '@/lib/api';
import {qk, useGroups, useLlmSettings, useRules} from '@/hooks/queries';
import {cn, hexAlpha} from '@/lib/utils';
import {formatNumber} from '@/lib/format';
import {EMPTY_FILTER, type FilterForm} from '@/lib/wizard';
import {
  addFilter,
  computeNextRuns,
  emptySchedule,
  filterFromForm,
  formatRunTime,
  fullyCoveredGroups,
  ruleIdsForSelection,
  scheduleText,
  uncoveredRuleIds,
  validateSchedule,
  WEEKDAYS,
} from '@/lib/schedules';
import type {RuleSelectionMode, ScheduledAnalysisInput, ScheduleKind} from '@/types';
import {PageHeader} from '@/components/layout/AppShell';
import {Card, CardHeader} from '@/components/ui/Card';
import {Button} from '@/components/ui/Button';
import {Field, Input, Textarea} from '@/components/ui/Input';
import {Chip, Segmented} from '@/components/ui/Tabs';
import {Switch, SwitchRow} from '@/components/ui/Switch';
import {Alert, ErrorState, Skeleton} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';
import {SourceStep} from '@/components/wizard/SourceStep';
import {FilterFields, QueryChips} from '@/components/wizard/PoolStep';
import {RulesStep} from '@/components/wizard/RulesStep';
import {scheduleError} from '@/components/schedules/ScheduleParts';
import {toScheduleInput} from './SchedulesPage';

function Section({n, title, hint, children, actions, id}: {n: number; title: string; hint?: ReactNode; children: ReactNode; actions?: ReactNode; id?: string}) {
  return (
    <Card id={id} className="scroll-mt-4">
      <CardHeader
        title={
          <span className="flex items-center gap-2.5">
            <span className="flex size-5 items-center justify-center rounded-full border border-line-strong bg-surface-2 text-[11px] font-semibold text-fg-muted tnum">{n}</span>
            {title}
          </span>
        }
        description={hint}
        actions={actions}
      />
      <div className="p-4">{children}</div>
    </Card>
  );
}

const MODE_OPTIONS: {value: RuleSelectionMode; title: string; hint: string}[] = [
  {value: 'all_enabled', title: 'Tüm etkin kurallar', hint: 'Her çalıştırmada o anki tüm etkin kurallar kullanılır; yeni kurallar otomatik dahil olur.'},
  {value: 'groups', title: 'Seçili gruplar', hint: 'Grupların çalıştırma anındaki etkin üyeleri kullanılır; gruba eklenen kural otomatik dahil olur.'},
  {value: 'rules', title: 'Seçili kurallar', hint: 'Yalnızca işaretlenen kurallar (etkin olanlar) çalışır.'},
];

const KIND_OPTIONS: {value: ScheduleKind; label: string}[] = [
  {value: 'daily', label: 'Günlük'},
  {value: 'weekly', label: 'Haftalık'},
  {value: 'monthly', label: 'Aylık'},
  {value: 'interval', label: 'Saatlik'},
];

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function ScheduleForm({initial, id, prefilled}: {initial: ScheduledAnalysisInput; id: number | null; prefilled: boolean}) {
  const [form, setForm] = useState<ScheduledAnalysisInput>(initial);
  const [filter, setFilter] = useState<FilterForm>(EMPTY_FILTER);
  const [touched, setTouched] = useState(false);
  const rules = useRules();
  const groups = useGroups();
  const llm = useLlmSettings();
  const client = useQueryClient();
  const feedback = useFeedback();
  const navigate = useNavigate();

  // Picker state (RulesStep works on rule ids); initialised once rules and groups are known.
  const [ruleIds, setRuleIds] = useState<number[]>([]);
  const [pickerReady, setPickerReady] = useState(false);
  if (!pickerReady && rules.data && groups.data) {
    setPickerReady(true);
    setRuleIds(ruleIdsForSelection(initial.rule_selection, rules.data, groups.data));
  }
  const covered = useMemo(() => fullyCoveredGroups(rules.data ?? [], groups.data ?? [], ruleIds), [rules.data, groups.data, ruleIds]);
  const uncovered = useMemo(() => uncoveredRuleIds(groups.data ?? [], covered, ruleIds), [groups.data, covered, ruleIds]);
  const mode = form.rule_selection.mode;
  const selection = useMemo(
    () =>
      mode === 'all_enabled'
        ? {mode, group_ids: [], rule_ids: []}
        : mode === 'groups'
          ? {mode, group_ids: covered, rule_ids: []}
          : {mode, group_ids: [], rule_ids: [...ruleIds]},
    [mode, covered, ruleIds],
  );
  const input: ScheduledAnalysisInput = {...form, name: form.name.trim(), rule_selection: selection};
  const errors = validateSchedule(input);
  const invalid = Object.values(errors).some(Boolean);

  const set = <K extends keyof ScheduledAnalysisInput>(k: K, v: ScheduledAnalysisInput[K]) => setForm((f) => ({...f, [k]: v}));
  const setSchedule = (patch: Partial<ScheduledAnalysisInput['schedule']>) => setForm((f) => ({...f, schedule: {...f.schedule, ...patch}}));
  const setScope = (patch: Partial<ScheduledAnalysisInput['scope']>) => setForm((f) => ({...f, scope: {...f.scope, ...patch}}));

  // Preview (debounced); falls back to client-side next runs when the endpoint is missing.
  const debounced = useDebounced(JSON.stringify(input), 600);
  const canPreview = !!form.connection_id && form.scope.databases.length > 0 && selection !== null;
  const preview = useQuery({
    queryKey: ['schedules', 'preview', debounced],
    queryFn: () => api.schedules.preview(JSON.parse(debounced) as ScheduledAnalysisInput),
    enabled: canPreview,
    retry: false,
    staleTime: 30_000,
  });
  const localRuns = useMemo(() => computeNextRuns(form.schedule, new Date(), 3), [form.schedule]);
  const nextRuns = preview.data?.next_runs?.length ? preview.data.next_runs : localRuns.map((d) => d.toISOString());

  const save = useMutation({
    mutationFn: () => (id ? api.schedules.update(id, input) : api.schedules.create(input)),
    onSuccess: (s) => {
      client.invalidateQueries({queryKey: qk.schedules});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success(id ? 'Zamanlanmış analiz güncellendi' : 'Zamanlanmış analiz oluşturuldu', `${s.name} · ${s.schedule_text}`);
      navigate(`/schedules/${s.id}`);
    },
    onError: (e) =>
      feedback.error(e instanceof ApiError && e.status === 409 ? 'Bu adla bir zamanlanmış analiz zaten var' : 'Kaydedilemedi', scheduleError(e)),
  });
  const submit = () => {
    setTouched(true);
    if (!invalid) save.mutate();
    else document.getElementById(errors.name ? 'sec-general' : errors.databases || errors.connection ? 'sec-source' : errors.rules ? 'sec-rules' : 'sec-schedule')?.scrollIntoView({behavior: 'smooth'});
  };

  const err = (k: keyof typeof errors) => (touched ? errors[k] : undefined);
  const addQuery = () => {
    setScope({queries: addFilter(form.scope.queries, filterFromForm(filter))});
    setFilter(EMPTY_FILTER);
  };
  const filterEmpty = JSON.stringify(filterFromForm(filter)) === JSON.stringify(filterFromForm(EMPTY_FILTER));
  const groupMap = new Map((groups.data ?? []).map((g) => [g.id, g]));
  const ruleMap = new Map((rules.data ?? []).map((r) => [r.id, r]));

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-w-0 flex-col gap-4">
        {prefilled && (
          <Alert tone="info" title="Yeni Analiz seçimleriyle dolduruldu">
            Bağlantı, veritabanları, havuz sorguları ve kural seçimi aktarıldı. Zamanlanmış analiz nesne listesi değil sorgu saklar: her çalıştırmada sorguların
            güncel sonuçları (artımlı modda yalnızca değişenler) analiz edilir.
          </Alert>
        )}

        <Section n={1} id="sec-general" title="Genel">
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_200px]">
            <Field label="Ad" required error={err('name')}>
              <Input data-autofocus value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Örn. EDWDM gece taraması" maxLength={200} aria-invalid={!!err('name')} />
            </Field>
            <Field label="Durum">
              <div className="flex h-8 items-center justify-between gap-3 rounded-lg border border-line-strong bg-surface-2/40 px-3">
                <span className="text-[12.5px] text-fg">{form.enabled ? 'Etkin' : 'Duraklatıldı'}</span>
                <Switch checked={form.enabled} onChange={(v) => set('enabled', v)} label="Etkin" />
              </div>
            </Field>
            <Field label="Açıklama" className="md:col-span-2">
              <Textarea rows={2} value={form.description} onChange={(e) => set('description', e.target.value)} placeholder="Bu zamanlamanın amacı (isteğe bağlı)" />
            </Field>
          </div>
        </Section>

        <div id="sec-source" className="flex scroll-mt-4 flex-col gap-2">
          <p className="flex items-center gap-2.5 px-1 text-[13px] font-semibold text-fg">
            <span className="flex size-5 items-center justify-center rounded-full border border-line-strong bg-surface-2 text-[11px] font-semibold text-fg-muted tnum">2</span>
            Kaynak
          </p>
          <SourceStep
            connectionId={form.connection_id || null}
            onConnection={(cid) => setForm((f) => (f.connection_id === cid ? f : {...f, connection_id: cid, scope: {databases: [], queries: []}}))}
            databases={form.scope.databases}
            onDatabases={(dbs) => setScope({databases: dbs})}
          />
          {(err('connection') || err('databases')) && <p className="px-1 text-[11.5px] text-bad">{err('connection') ?? err('databases')}</p>}
        </div>

        <Section
          n={3}
          title="Kapsam"
          hint="Havuz sorguları her çalıştırmada yeniden değerlendirilir; sonuçlar birleştirilir. Sorgu eklenmezse seçili veritabanlarındaki tüm nesneler kapsamdadır."
        >
          {form.scope.queries.length > 0 ? (
            <ul className="mb-4 flex flex-col divide-y divide-line overflow-hidden rounded-lg border border-line-strong">
              {form.scope.queries.map((q, i) => (
                <li key={i} className="flex items-start gap-3 bg-surface-2/30 px-3 py-2">
                  <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-3 text-[11px] font-medium text-fg-muted tnum">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <QueryChips query={q} />
                  </div>
                  <Button variant="ghost" size="xs" iconOnly aria-label={`Sorgu ${i + 1} kaldır`} className="hover:text-bad" onClick={() => setScope({queries: form.scope.queries.filter((_, j) => j !== i)})}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mb-4 flex items-center gap-2 rounded-lg border border-dashed border-line-strong px-3 py-2.5 text-[12.5px] text-fg-muted">
              <Filter className="size-3.5 shrink-0 text-fg-subtle" /> Sorgu yok — seçili veritabanlarındaki <span className="font-semibold text-fg">tüm nesneler</span> kapsamda.
            </p>
          )}
          {form.connection_id && form.scope.databases.length ? (
            <div className="grid gap-4 rounded-lg border border-line bg-surface-2/20 p-3 md:grid-cols-2">
              <FilterFields connectionId={form.connection_id} databases={form.scope.databases} filter={filter} onFilter={setFilter} />
              <div className="flex flex-wrap items-center gap-2 md:col-span-2">
                <Button icon={<ListPlus className="size-3.5" />} disabled={filterEmpty} onClick={addQuery}>
                  Sorguyu kapsama ekle
                </Button>
                <span className="text-xs text-fg-subtle">Filtreler VE ile birleşir; birden fazla sorgu eklenirse sonuçların birleşimi alınır.</span>
              </div>
            </div>
          ) : (
            <p className="text-[12.5px] text-fg-subtle">Filtre eklemek için önce bağlantı ve veritabanı seçin.</p>
          )}
        </Section>

        <Section n={4} id="sec-rules" title="Kurallar" hint="Kurallar her çalıştırmada yeniden çözülür.">
          <div role="radiogroup" className="grid gap-2 md:grid-cols-3">
            {MODE_OPTIONS.map((o) => {
              const on = mode === o.value;
              return (
                <button
                  key={o.value}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => set('rule_selection', {...form.rule_selection, mode: o.value})}
                  className={cn(
                    'flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors',
                    on ? 'border-accent bg-accent-soft ring-3 ring-accent/15' : 'border-line-control/60 bg-surface-2/30 hover:border-fg-subtle hover:bg-surface-2',
                  )}
                >
                  <span className="flex items-center gap-2 text-[13px] font-semibold text-fg">
                    {o.value === 'all_enabled' ? <ListChecks className="size-3.5" /> : o.value === 'groups' ? <Layers className="size-3.5" /> : <Check className="size-3.5" />}
                    {o.title}
                    {on && <Check className="ml-auto size-3.5 text-accent" strokeWidth={3} />}
                  </span>
                  <span className="text-[11.5px] leading-4 text-fg-muted">{o.hint}</span>
                </button>
              );
            })}
          </div>
          {mode === 'all_enabled' ? (
            <p className="mt-3 text-[12.5px] text-fg-muted">
              Şu an <span className="font-semibold text-fg tnum">{(rules.data ?? []).filter((r) => r.enabled).length}</span> etkin kural var.
            </p>
          ) : (
            <div className="mt-4 flex flex-col gap-3">
              {mode === 'groups' && (
                <div className="rounded-lg border border-line-strong bg-surface-2/30 px-3 py-2.5 text-[12.5px]">
                  <p className="font-medium text-fg">Kaydedilecek gruplar (tamamı seçili olanlar)</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {covered.length === 0 && <span className="text-fg-subtle">Henüz tamamen seçili grup yok — aşağıda grup başlığındaki kutuyu işaretleyin.</span>}
                    {covered.map((gid) => {
                      const g = groupMap.get(gid);
                      return g ? (
                        <span key={gid} className="inline-flex h-6 items-center gap-1.5 rounded-md border px-2 text-xs font-medium text-fg" style={{borderColor: hexAlpha(g.color, 0.5), background: hexAlpha(g.color, 0.12)}}>
                          <Layers className="size-3" style={{color: g.color}} />
                          {g.name}
                        </span>
                      ) : null;
                    })}
                  </div>
                  {uncovered.length > 0 && (
                    <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-warn">
                      <TriangleAlert className="mt-px size-3 shrink-0" />
                      {uncovered.length} kural tam seçili bir grupta değil ve kaydedilmeyecek ({uncovered.slice(0, 4).map((rid) => ruleMap.get(rid)?.code ?? rid).join(', ')}
                      {uncovered.length > 4 ? '…' : ''}). Bunları da çalıştırmak için “Seçili kurallar” modunu kullanın.
                    </p>
                  )}
                </div>
              )}
              <RulesStep compact groupIds={[]} onGroupIds={() => undefined} ruleIds={ruleIds} onRuleIds={setRuleIds} />
            </div>
          )}
          {err('rules') && <p className="mt-2 text-[11.5px] text-bad">{err('rules')}</p>}
        </Section>

        <Section n={5} id="sec-schedule" title="Zamanlama" hint="Saatler bu bilgisayarın yerel saatine göredir.">
          <div className="flex flex-col gap-4">
            <Segmented value={form.schedule.kind} onChange={(k) => setSchedule({kind: k})} options={KIND_OPTIONS} />
            <div className="flex flex-wrap items-start gap-4">
              {form.schedule.kind !== 'interval' ? (
                <Field label="Saat" error={err('time')}>
                  <Input type="time" mono className="w-32" value={form.schedule.time} onChange={(e) => setSchedule({time: e.target.value})} aria-invalid={!!err('time')} />
                </Field>
              ) : (
                <Field label="Aralık (saat)" error={err('interval')} hint="1–168 saat">
                  <Input
                    type="number"
                    mono
                    className="w-32"
                    min={1}
                    max={168}
                    value={form.schedule.interval_hours}
                    onChange={(e) => setSchedule({interval_hours: Number(e.target.value)})}
                    aria-invalid={!!err('interval')}
                  />
                </Field>
              )}
              {form.schedule.kind === 'monthly' && (
                <Field label="Ayın günü" error={err('month_day')} hint="Ayda o gün yoksa ayın son günü">
                  <Input type="number" mono className="w-32" min={1} max={31} value={form.schedule.month_day} onChange={(e) => setSchedule({month_day: Number(e.target.value)})} />
                </Field>
              )}
              {form.schedule.kind === 'weekly' && (
                <Field label="Günler" error={err('weekdays')}>
                  <div className="flex flex-wrap gap-1.5">
                    {WEEKDAYS.map((d) => {
                      const on = form.schedule.weekdays.includes(d.value);
                      return (
                        <Chip
                          key={d.value}
                          active={on}
                          onClick={() => setSchedule({weekdays: on ? form.schedule.weekdays.filter((x) => x !== d.value) : [...form.schedule.weekdays, d.value].sort()})}
                        >
                          {d.short}
                        </Chip>
                      );
                    })}
                  </div>
                </Field>
              )}
            </div>
            <div className="rounded-lg border border-line-strong bg-surface-2/30 px-3 py-2.5">
              <p className="flex items-center gap-2 text-[13px] font-semibold text-fg">
                <CalendarClock className="size-4 text-accent" /> {scheduleText(form.schedule)}
              </p>
              <p className="mt-1.5 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Sonraki çalıştırmalar{preview.data ? '' : ' (tahmini)'}</p>
              <ol className="mt-1 flex flex-wrap gap-1.5">
                {nextRuns.length === 0 && <li className="text-[12px] text-fg-subtle">—</li>}
                {nextRuns.map((r) => (
                  <li key={r} className="rounded-md border border-line bg-surface px-2 py-0.5 font-mono text-[11.5px] text-fg">
                    {formatRunTime(r)}
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </Section>

        <Section n={6} title="Artımlı tarama">
          <div className="grid gap-2 md:grid-cols-2">
            <SwitchRow
              title="Yalnızca değişen veya yeni oluşturulan nesneleri analiz et"
              description="Son başarılı çalıştırmadan bu yana değişen (modify_date) veya oluşturulan (create_date) nesneler; 5 dk örtüşmeyle."
              checked={form.incremental}
              onChange={(v) => set('incremental', v)}
            />
            <SwitchRow
              title="İlk çalıştırmada tüm kapsamı tara"
              description="Karşılaştırma tabanı oluşur. Kapalıysa ilk çalıştırma, tanımın oluşturulduğu andan sonraki değişiklikleri tarar."
              checked={form.first_run_full}
              onChange={(v) => set('first_run_full', v)}
              disabled={!form.incremental}
            />
          </div>
        </Section>
      </div>

      <div className="flex flex-col gap-4 xl:sticky xl:top-4">
        <Card className="overflow-hidden">
          <CardHeader icon={<Eye className="size-4" />} title="Önizleme" description="Şu anki katalog ve kurallarla tahmin." />
          <div className="p-4">
            {!canPreview ? (
              <p className="text-[12.5px] text-fg-subtle">Bağlantı ve veritabanı seçildiğinde nesne ve kontrol sayıları burada görünür.</p>
            ) : preview.isPending || preview.isFetching ? (
              <div className="flex flex-col gap-2">
                <Skeleton className="h-10" />
                <Skeleton className="h-16" />
              </div>
            ) : preview.isError ? (
              <p className="text-[12px] text-fg-muted">Önizleme alınamadı: {scheduleError(preview.error).message}</p>
            ) : preview.data ? (
              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-lg border border-line bg-surface-2/50 px-3 py-2">
                    <p className="text-[11px] text-fg-subtle">Kapsamdaki nesne</p>
                    <p className="text-[18px] font-semibold text-fg tnum">{formatNumber(preview.data.object_count)}</p>
                    {preview.data.changed_count !== null && <p className="text-[11px] text-fg-muted tnum">{formatNumber(preview.data.changed_count)} değişen</p>}
                  </div>
                  <div className="rounded-lg border border-line bg-surface-2/50 px-3 py-2">
                    <p className="text-[11px] text-fg-subtle">Kural</p>
                    <p className="text-[18px] font-semibold text-fg tnum">{formatNumber(preview.data.rule_count)}</p>
                    {preview.data.llm_rule_count > 0 && <p className="text-[11px] text-accent tnum">{preview.data.llm_rule_count} LLM</p>}
                  </div>
                </div>
                <div className="text-[12.5px] text-fg-muted">
                  Tahmini <span className="font-semibold text-fg tnum">{formatNumber(preview.data.estimated_checks)}</span> kontrol
                  {preview.data.estimated_llm_checks > 0 && (
                    <>
                      , bunların <span className="font-semibold text-accent tnum">{formatNumber(preview.data.estimated_llm_checks)}</span>’i LLM
                    </>
                  )}
                  .
                  {form.incremental && <span className="mt-0.5 block text-[11.5px] text-fg-subtle">Artımlı modda yalnız değişen nesneler çalışacağı için gerçek sayı genellikle çok daha düşüktür.</span>}
                </div>
                {preview.data.llm_rule_count > 0 && llm.data && !llm.data.enabled && (
                  <Alert tone="warn" title="LLM ayarları kapalı">
                    Seçimde LLM kuralı var; ayarlar açılmazsa çalıştırmalar başarısız olur.
                  </Alert>
                )}
              </div>
            ) : null}
            {mode !== 'all_enabled' && <p className="mt-3 flex items-center gap-1.5 text-[11.5px] text-fg-subtle"><Sparkles className="size-3" /> {mode === 'groups' ? `${covered.length} grup` : `${ruleIds.length} kural`} seçili</p>}
          </div>
        </Card>
        <Card className="p-4">
          {save.error && (
            <Alert tone="bad" className="mb-3" title="Kaydedilemedi">
              {scheduleError(save.error).message}
            </Alert>
          )}
          {touched && invalid && <p className="mb-3 text-[12px] text-bad">Eksik veya hatalı alanlar var; işaretli bölümleri kontrol edin.</p>}
          <div className="flex gap-2">
            <Link to={id ? `/schedules/${id}` : '/schedules'} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-fg-muted hover:bg-surface-3 hover:text-fg">
              <X className="size-4" /> Vazgeç
            </Link>
            <Button variant="primary" className="flex-1" loading={save.isPending} icon={<Save className="size-4" />} onClick={submit}>
              {id ? 'Değişiklikleri kaydet' : 'Kaydet'}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

export function ScheduleEditPage() {
  const {id} = useParams();
  const location = useLocation();
  const scheduleId = id ? Number(id) : null;
  const existing = useQuery({queryKey: qk.schedule(scheduleId ?? -1), queryFn: () => api.schedules.get(scheduleId!), enabled: scheduleId !== null, retry: false});
  const prefill = (location.state as {prefill?: ScheduledAnalysisInput} | null)?.prefill ?? null;
  const [newInitial] = useState<ScheduledAnalysisInput>(() => prefill ?? emptySchedule());

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow={
          <Link to={scheduleId ? `/schedules/${scheduleId}` : '/schedules'} className="inline-flex items-center gap-1 text-xs text-fg-subtle hover:text-fg">
            <ArrowLeft className="size-3.5" /> {scheduleId ? 'Zamanlanmış analiz' : 'Zamanlanmış analizler'}
          </Link>
        }
        title={scheduleId ? `Düzenle · ${existing.data?.name ?? '…'}` : 'Yeni zamanlanmış analiz'}
        description="Kapsamı, kuralları ve periyodu tanımlayın. Her çalıştırma normal bir analiz kaydı oluşturur ve önceki çalıştırmalarla karşılaştırılır."
      />
      {scheduleId === null ? (
        <ScheduleForm initial={newInitial} id={null} prefilled={!!prefill} />
      ) : existing.isPending ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-32 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      ) : existing.isError ? (
        <Card>
          <ErrorState title="Zamanlanmış analiz yüklenemedi" error={scheduleError(existing.error)} onRetry={() => existing.refetch()} />
        </Card>
      ) : (
        <ScheduleForm key={existing.data.id} initial={toScheduleInput(existing.data)} id={existing.data.id} prefilled={false} />
      )}
    </div>
  );
}
