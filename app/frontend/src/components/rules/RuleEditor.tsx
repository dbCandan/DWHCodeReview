import {useMemo, useState, type ReactNode} from 'react';
import {Link} from 'react-router';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Blocks, Check, CircleCheck, Crosshair, Database, FlaskConical, Info, Lock, Play, Regex, Sparkles, Timer, TriangleAlert} from 'lucide-react';
import {api, errorMessage} from '@/lib/api';
import {qk, useConnections, useGroups, useLlmSettings} from '@/hooks/queries';
import {cn, RULE_CODE_PATTERN} from '@/lib/utils';
import {OBJECT_TYPE_LABEL, OBJECT_TYPES} from '@/lib/format';
import {SEVERITIES, SEVERITY_CLASS, SEVERITY_LABEL} from '@/lib/severity';
import {SAMPLE_PROCEDURE} from '@/lib/sql';
import {buildLineMarks} from '@/lib/findings';
import {
  BUILTIN_CHECK_DETAIL,
  builtinLabel,
  isInfoNote,
  METADATA_PRECONDITION_LABEL,
  regexWarning,
  RULE_KIND_HINT,
  RULE_KIND_LABEL,
  ruleApplies,
  scopeSummary,
} from '@/lib/rules';
import type {BuiltinCheck, MetadataPrecondition, ObjectType, Rule, RuleInput, RuleKind, RuleTestResult} from '@/types';
import {Drawer} from '@/components/ui/Overlay';
import {Button} from '@/components/ui/Button';
import {Field, Input, Textarea} from '@/components/ui/Input';
import {Chip, Segmented} from '@/components/ui/Tabs';
import {MultiSelect, Select} from '@/components/ui/Select';
import {Switch, SwitchRow} from '@/components/ui/Switch';
import {Alert} from '@/components/ui/Feedback';
import {Kbd} from '@/components/ui/Badge';
import {Tooltip} from '@/components/ui/Tooltip';
import {useFeedback} from '@/components/ui/Toast';
import {SqlViewer} from '@/components/analysis/SqlViewer';
import {TagInput} from './TagInput';
import {RULE_FIELD_LABEL, type FieldChanges} from '@/lib/assistant';
import {RuleExceptions} from './RuleExceptions';

export function emptyRule(): RuleInput {
  return {
    code: '',
    name: '',
    description: '',
    recommendation: '',
    severity: 'medium',
    kind: 'regex',
    pattern: '',
    match_mode: 'match',
    target: 'definition',
    ignore_case: true,
    ignore_comments: true,
    llm_prompt: '',
    object_types: [],
    enabled: true,
    group_ids: [],
    builtin_check: null,
    precondition: '',
    metadata_precondition: null,
    requires_metadata: false,
    databases: [],
    name_pattern: '',
    sample_sql: null,
    sample_object_name: null,
    sample_object_type: null,
    sample_database: null,
  };
}

/** Form state for an existing rule; v1.1 fields default safely when an older backend omits them. */
export function ruleToInput(rule: Rule): RuleInput {
  const {id: _id, created_at: _c, updated_at: _u, exception_count: _e, ...input} = rule;
  void _id;
  void _c;
  void _u;
  void _e;
  return {
    ...input,
    pattern: input.pattern ?? '',
    llm_prompt: input.llm_prompt ?? '',
    object_types: input.object_types ?? [],
    group_ids: input.group_ids ?? [],
    builtin_check: input.builtin_check ?? null,
    precondition: input.precondition ?? '',
    metadata_precondition: input.metadata_precondition ?? null,
    requires_metadata: input.requires_metadata ?? false,
    databases: input.databases ?? [],
    name_pattern: input.name_pattern ?? '',
    sample_sql: input.sample_sql ?? null,
    sample_object_name: input.sample_object_name ?? null,
    sample_object_type: input.sample_object_type ?? null,
    sample_database: input.sample_database ?? null,
  };
}

const trimOrNull = (v: string | null | undefined) => (v ?? '').trim() || null;

/** Normalizes form state into the API payload (kind-specific fields are nulled when they do not apply). */
export function toRulePayload(form: RuleInput): RuleInput {
  const dbs: string[] = [];
  for (const d of form.databases ?? []) {
    const t = d.trim();
    if (t && !dbs.some((x) => x.toLowerCase() === t.toLowerCase())) dbs.push(t);
  }
  return {
    ...form,
    code: form.code.trim(),
    name: form.name.trim(),
    pattern: form.kind === 'regex' ? form.pattern || '' : form.pattern || null,
    llm_prompt: form.kind === 'llm' ? form.llm_prompt || '' : form.llm_prompt || null,
    builtin_check: form.kind === 'builtin' ? (form.builtin_check ?? null) : null,
    precondition: form.kind === 'regex' ? null : trimOrNull(form.precondition),
    metadata_precondition: form.kind === 'regex' ? null : (form.metadata_precondition ?? null),
    requires_metadata: form.kind === 'regex' ? false : !!form.requires_metadata,
    databases: dbs,
    name_pattern: trimOrNull(form.name_pattern),
    sample_sql: form.sample_sql?.trim() ? form.sample_sql : null,
    sample_object_name: trimOrNull(form.sample_object_name),
    sample_object_type: form.sample_object_type ?? null,
    sample_database: trimOrNull(form.sample_database),
  };
}

function useDatabaseSuggestions(): string[] {
  const connections = useConnections();
  const first = connections.data?.[0]?.id;
  const dbs = useQuery({
    queryKey: qk.databases(first ?? -1),
    queryFn: () => api.connections.databases(first!),
    enabled: first !== undefined,
    retry: false,
    staleTime: 5 * 60_000,
  });
  return dbs.data ?? [];
}

function EditorSection({n, title, hint, children, aside}: {n: number; title: ReactNode; hint: ReactNode; children: ReactNode; aside?: ReactNode}) {
  return (
    <section className="flex flex-col gap-4 border-t border-line pt-5 first:border-t-0 first:pt-0">
      <header className="flex items-start gap-3">
        <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full border border-line-strong bg-surface-2 text-[11px] font-semibold text-fg-muted tnum">
          {n}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[13.5px] font-semibold tracking-[-0.005em] text-fg">{title}</h3>
          <p className="mt-0.5 text-xs text-fg-subtle">{hint}</p>
        </div>
        {aside}
      </header>
      <div className="flex flex-col gap-4 sm:pl-8">{children}</div>
    </section>
  );
}

const KIND_ICON: Record<RuleKind, ReactNode> = {
  regex: <Regex className="size-3.5" />,
  llm: <Sparkles className="size-3.5" />,
  builtin: <Blocks className="size-3.5" />,
};
const KIND_ACTIVE: Record<RuleKind, string> = {
  regex: 'border-accent bg-accent-soft ring-3 ring-accent/15',
  llm: 'border-accent bg-accent-soft ring-3 ring-accent/15',
  builtin: 'border-builtin bg-builtin-soft ring-3 ring-builtin/15',
};
const KIND_ICON_BOX: Record<RuleKind, string> = {
  regex: 'border-line-strong bg-surface-3 text-fg-muted',
  llm: 'border-accent/30 bg-accent-soft text-accent',
  builtin: 'border-builtin/30 bg-builtin-soft text-builtin',
};

function KindPicker({value, onChange, lockedBuiltin}: {value: RuleKind; onChange: (k: RuleKind) => void; lockedBuiltin: boolean}) {
  const kinds: RuleKind[] = ['regex', 'llm', 'builtin'];
  return (
    <div role="radiogroup" aria-label="Kontrol yöntemi" className="grid gap-2 sm:grid-cols-3">
      {kinds.map((k) => {
        const active = value === k;
        const disabled = lockedBuiltin ? k !== 'builtin' : k === 'builtin';
        const reason = lockedBuiltin
          ? 'Yerleşik bir kural başka bir türe çevrilemez.'
          : 'Yerleşik kontroller sistemde tanımlıdır; yeni kural olarak eklenemez.';
        const button = (
          <button
            type="button"
            role="radio"
            aria-checked={active}
            aria-disabled={disabled}
            onClick={() => !disabled && onChange(k)}
            className={cn(
              'relative flex w-full flex-col gap-1.5 rounded-lg border p-3 text-left transition-all duration-150',
              active ? KIND_ACTIVE[k] : 'border-line-control/60 bg-surface-2/30',
              !active && !disabled && 'hover:border-fg-subtle/40 hover:bg-surface-2/70',
              disabled && 'cursor-not-allowed opacity-55',
            )}
          >
            <span className="flex items-center gap-2">
              <span className={cn('flex size-6 items-center justify-center rounded-md border', KIND_ICON_BOX[k])}>{KIND_ICON[k]}</span>
              <span className="flex-1 text-[13px] font-semibold text-fg">{RULE_KIND_LABEL[k]}</span>
              {active ? (
                <Check className="size-3.5 text-fg" strokeWidth={3} />
              ) : disabled ? (
                <Lock className="size-3 text-fg-subtle" />
              ) : k === 'llm' ? (
                <Timer className="size-3 text-fg-subtle" />
              ) : null}
            </span>
            <span className="text-[11.5px] leading-4 text-fg-subtle">{RULE_KIND_HINT[k]}</span>
          </button>
        );
        return disabled ? (
          <Tooltip key={k} content={reason}>
            <span className="flex">{button}</span>
          </Tooltip>
        ) : (
          <span key={k} className="flex">
            {button}
          </span>
        );
      })}
    </div>
  );
}

function RegexNote({warning}: {warning: string | null}) {
  if (!warning) return null;
  return (
    <p className="flex items-start gap-1.5 text-[11.5px] text-warn">
      <TriangleAlert className="mt-px size-3 shrink-0" />
      {warning}
    </p>
  );
}

/** Shared field sections (Kural · Nasıl kontrol edilir · Kapsam · Açıklama) used by the drawer and the rule assistant. */
export function RuleFormFields({
  form,
  set,
  touched,
  lockedBuiltin,
  onNavigate,
  changes,
}: {
  form: RuleInput;
  set: <K extends keyof RuleInput>(key: K, value: RuleInput[K]) => void;
  touched: boolean;
  lockedBuiltin: boolean;
  onNavigate?: () => void;
  /** Field → previous value text (extend proposals); changed fields are listed per section. */
  changes?: FieldChanges;
}) {
  const groups = useGroups();
  const llm = useLlmSettings();
  const dbSuggestions = useDatabaseSuggestions();
  const isBuiltin = form.kind === 'builtin';
  const errors = ruleFormErrors(form);
  const warnings = {
    pattern: form.kind === 'regex' ? regexWarning(form.pattern) : null,
    precondition: form.kind === 'llm' ? regexWarning(form.precondition) : null,
    name_pattern: regexWarning(form.name_pattern),
  };
  const groupOptions = useMemo(
    () => (groups.data ?? []).map((g) => ({value: String(g.id), label: g.name, color: g.color})),
    [groups.data],
  );
  return (
    <>
      {/* 1 — Kural */}
      <EditorSection n={1} aside={<ChangedBadge keys={['code', 'name', 'severity', 'enabled', 'group_ids']} changes={changes} />} title="Kural" hint="Kimlik, önem derecesi, etkinlik ve isteğe bağlı grup üyeliği.">
        <div className="grid gap-4 sm:grid-cols-[180px_1fr]">
          <Field label="Kod" required error={touched && errors.code} hint={isBuiltin ? 'Yerleşik kuralın kodu değiştirilemez' : 'Örn. DWH-SCD-02'}>
            <Input
              data-autofocus={!isBuiltin || undefined}
              mono
              value={form.code}
              disabled={isBuiltin}
              onChange={(e) => set('code', e.target.value.toUpperCase().replace(/\s/g, '_'))}
              placeholder="DWH-SCD-02"
              maxLength={32}
              aria-invalid={touched && !!errors.code}
            />
          </Field>
          <Field label="Ad" required error={touched && errors.name} hint="Bulgu listesinde görünen kısa başlık">
            <Input
              data-autofocus={isBuiltin || undefined}
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="EdwStatus filtresi kullanılmış"
              aria-invalid={touched && !!errors.name}
            />
          </Field>
        </div>
        <Field label="Önem derecesi">
          <Segmented
            size="sm"
            className="flex w-full flex-wrap [&>button]:flex-1"
            value={form.severity}
            onChange={(v) => set('severity', v)}
            options={SEVERITIES.map((s) => ({
              value: s,
              label: SEVERITY_LABEL[s],
              icon: <span className={cn('size-1.5 rounded-full', SEVERITY_CLASS[s].bg)} />,
              activeClass: cn(SEVERITY_CLASS[s].text),
            }))}
          />
        </Field>
        <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,220px)]">
          <Field label="Gruplar" hint="İsteğe bağlı. Grup, Yeni Analiz’de kuralları topluca seçmeyi sağlar.">
            <MultiSelect
              options={groupOptions}
              loading={groups.isPending}
              value={form.group_ids.map(String)}
              onChange={(v) => set('group_ids', v.map(Number))}
              placeholder="Grup seçin (isteğe bağlı)"
              emptyText="Henüz grup yok"
            />
          </Field>
          <Field label="Durum">
            <div className="flex h-8 items-center justify-between gap-3 rounded-lg border border-line bg-surface-2/40 px-3">
              <span className="text-[12.5px] text-fg">{form.enabled ? 'Etkin' : 'Devre dışı'}</span>
              <Switch checked={form.enabled} onChange={(v) => set('enabled', v)} label="Etkin" />
            </div>
          </Field>
        </div>
        <ChangedFields keys={['code', 'name', 'severity', 'enabled', 'group_ids']} changes={changes} />
      </EditorSection>

      {/* 2 — Nasıl kontrol edilir */}
      <EditorSection n={2} aside={<ChangedBadge keys={['kind', 'builtin_check', 'pattern', 'match_mode', 'target', 'ignore_case', 'ignore_comments', 'llm_prompt', 'requires_metadata', 'precondition', 'metadata_precondition']} changes={changes} />} title="Nasıl kontrol edilir" hint="Kontrol yöntemini seçin; yöntem hızı ve neyi yakalayabileceğini belirler.">
        <KindPicker value={form.kind} onChange={(k) => set('kind', k)} lockedBuiltin={lockedBuiltin} />

        {form.kind === 'regex' && (
          <div className="flex flex-col gap-4 rounded-xl border border-line bg-surface-2/30 p-4">
            <Field label="Desen (regex)" required error={touched && errors.pattern} hint="Python regex sözdizimi. Örn. \bSELECT\s+\*">
              <Textarea
                mono
                rows={3}
                value={form.pattern ?? ''}
                onChange={(e) => set('pattern', e.target.value)}
                placeholder={'\\bSELECT\\s+\\*'}
                aria-invalid={touched && !!errors.pattern}
              />
            </Field>
            <RegexNote warning={warnings.pattern} />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Eşleşme modu">
                <Segmented
                  size="sm"
                  value={form.match_mode}
                  onChange={(v) => set('match_mode', v)}
                  options={[
                    {value: 'match', label: 'Eşleşirse bulgu'},
                    {value: 'absent', label: 'Bulunmazsa bulgu'},
                  ]}
                />
              </Field>
              <Field label="Hedef">
                <Segmented
                  size="sm"
                  value={form.target}
                  onChange={(v) => set('target', v)}
                  options={[
                    {value: 'definition', label: 'Tanım (SQL)'},
                    {value: 'name', label: 'Nesne adı'},
                  ]}
                />
              </Field>
            </div>
            <p className="-mt-1 text-[11.5px] text-fg-subtle">
              {form.match_mode === 'match'
                ? 'Her eşleşme ayrı bir bulgu üretir.'
                : 'Desen nesnede hiç bulunmazsa nesne başına tek bulgu üretilir (örn. zorunlu TRY/CATCH).'}
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <SwitchRow title="Büyük/küçük harf duyarsız" checked={form.ignore_case} onChange={(v) => set('ignore_case', v)} />
              <SwitchRow
                title="Yorumları yok say"
                description="-- / /* */ ve string literal'ler hariç"
                checked={form.ignore_comments}
                onChange={(v) => set('ignore_comments', v)}
              />
            </div>
          </div>
        )}

        {form.kind === 'llm' && (
          <div className="flex flex-col gap-4 rounded-xl border border-accent/20 bg-accent-soft/30 p-4">
            {llm.data && !llm.data.enabled && (
              <Alert
                tone="warn"
                title="LLM ayarları devre dışı"
                action={
                  <Link to="/settings" className="text-xs font-medium text-accent hover:underline" onClick={onNavigate}>
                    Ayarlara git
                  </Link>
                }
              >
                Bu kural kaydedilebilir ama LLM etkinleştirilmeden analizlerde ya da testte çalışmaz.
              </Alert>
            )}
            <Field
              label="LLM talimatı"
              required
              error={touched && errors.llm_prompt}
              hint="Modelin neyi ihlal sayacağını ve neyi saymayacağını net yazın. Model, ihlal bulduğu satırları gerekçesiyle döndürür."
            >
              <Textarea
                mono
                rows={12}
                value={form.llm_prompt ?? ''}
                onChange={(e) => set('llm_prompt', e.target.value)}
                placeholder={'Bu kural … denetler.\n\nSTANDART:\n- …\n\nİHLAL SAY:\n1. …'}
                aria-invalid={touched && !!errors.llm_prompt}
              />
            </Field>
            <SwitchRow
              title="Katalog metadatasını modele gönder"
              description="Tablo tipleri, kolon tipleri, SCD ve partition bilgisi isteme eklenir."
              checked={!!form.requires_metadata}
              onChange={(v) => set('requires_metadata', v)}
            />
            <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface/60 p-3">
              <p className="flex items-center gap-1.5 text-xs font-medium text-fg">
                <Timer className="size-3.5 text-accent" />
                Hızlandırma — ön koşullar
              </p>
              <Field label="Ön koşul deseni (regex)" hint="Eşleşmeyen nesneler modele gönderilmez, analiz hızlanır. Boş = tüm nesneler gönderilir.">
                <Input
                  mono
                  value={form.precondition ?? ''}
                  onChange={(e) => set('precondition', e.target.value)}
                  placeholder={'\\$PARTITION|WITH\\s*\\(\\s*PARTITIONS'}
                />
              </Field>
              <RegexNote warning={warnings.precondition} />
              <Field label="Katalog ön koşulu" hint="Katalog metadatasına göre koşulu sağlamayan nesneler atlanır.">
                <Select
                  value={form.metadata_precondition ?? ''}
                  onChange={(e) => set('metadata_precondition', (e.target.value || null) as MetadataPrecondition | null)}
                >
                  <option value="">Yok</option>
                  {(Object.keys(METADATA_PRECONDITION_LABEL) as MetadataPrecondition[]).map((m) => (
                    <option key={m} value={m}>
                      {METADATA_PRECONDITION_LABEL[m]}
                    </option>
                  ))}
                </Select>
              </Field>
              {(form.precondition ?? '').trim() && (
                <div className="grid gap-2 sm:grid-cols-2">
                  <SwitchRow title="Büyük/küçük harf duyarsız" description="Ön koşul deseni için" checked={form.ignore_case} onChange={(v) => set('ignore_case', v)} />
                  <SwitchRow title="Yorumları yok say" description="Ön koşul yorumlarda aranmaz" checked={form.ignore_comments} onChange={(v) => set('ignore_comments', v)} />
                </div>
              )}
            </div>
          </div>
        )}

        {form.kind === 'builtin' && (
          <div className="flex flex-col gap-3 rounded-xl border border-builtin/25 bg-builtin-soft/50 p-4">
            <div className="flex items-start gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-builtin/30 bg-builtin-soft text-builtin">
                <Blocks className="size-4" />
              </span>
              <div className="min-w-0">
                <p className="text-[13px] font-semibold text-fg">{builtinLabel(form.builtin_check)}</p>
                <p className="font-mono text-[11px] text-fg-subtle">{form.builtin_check ?? '—'}</p>
                {form.builtin_check && BUILTIN_CHECK_DETAIL[form.builtin_check as BuiltinCheck] && (
                  <p className="mt-1.5 text-[12px] leading-[18px] text-fg-muted">{BUILTIN_CHECK_DETAIL[form.builtin_check as BuiltinCheck]}</p>
                )}
              </div>
            </div>
            <p className="flex items-start gap-1.5 text-[11.5px] text-fg-subtle">
              <Lock className="mt-px size-3 shrink-0" />
              Kontrol mantığı sistemde tanımlıdır ve değiştirilemez. Ad, önem, açıklama/öneri, kapsam, durum ve gruplar düzenlenebilir.
            </p>
          </div>
        )}
        <ChangedFields keys={['kind', 'builtin_check', 'pattern', 'match_mode', 'target', 'ignore_case', 'ignore_comments', 'llm_prompt', 'requires_metadata', 'precondition', 'metadata_precondition']} changes={changes} />
      </EditorSection>

      {/* 3 — Kapsam */}
      <EditorSection n={3} aside={<ChangedBadge keys={['object_types', 'databases', 'name_pattern']} changes={changes} />} title="Nerede uygulanır (Kapsam)" hint="Kural yalnızca bu filtrelerin hepsine uyan nesnelerde çalışır. Boş bırakılan filtre “tümü” demektir.">
        <Field label="Nesne tipleri" hint={form.object_types.length ? undefined : 'Hiçbiri seçilmezse tüm tiplere uygulanır.'}>
          <div className="flex flex-wrap gap-1.5">
            {OBJECT_TYPES.map((t) => {
              const on = form.object_types.includes(t);
              return (
                <Chip
                  key={t}
                  active={on}
                  onClick={() => set('object_types', on ? form.object_types.filter((x) => x !== t) : [...form.object_types, t])}
                >
                  {OBJECT_TYPE_LABEL[t]}
                </Chip>
              );
            })}
          </div>
        </Field>
        <Field label="Veritabanları" hint="Yazıp Enter’a basın. Boş = tüm veritabanları (büyük/küçük harf duyarsız).">
          <TagInput
            mono
            icon={<Database className="size-3.5" />}
            value={form.databases ?? []}
            onChange={(v) => set('databases', v)}
            suggestions={dbSuggestions}
            placeholder="Örn. EDWDM"
          />
        </Field>
        <Field label="Ad deseni (regex)" hint={<>“şema.ad” üzerinde aranır, büyük/küçük harf duyarsız. Örn. <code className="font-mono">^[^.]+\.v</code> → adı “v” ile başlayan nesneler.</>}>
          <Input mono value={form.name_pattern ?? ''} onChange={(e) => set('name_pattern', e.target.value)} placeholder={'^[^.]+\\.v'} />
        </Field>
        <RegexNote warning={warnings.name_pattern} />
        <div className="flex items-start gap-2 rounded-lg border border-line bg-surface-2/50 px-3 py-2.5 text-[12.5px] text-fg">
          <Crosshair className="mt-0.5 size-3.5 shrink-0 text-accent" />
          <span>{scopeSummary(form)}</span>
        </div>
        <ChangedFields keys={['object_types', 'databases', 'name_pattern']} changes={changes} />
      </EditorSection>

      {/* 4 — Açıklama */}
      <EditorSection n={4} aside={<ChangedBadge keys={['description', 'recommendation']} changes={changes} />} title="Açıklama" hint="Bulgu raporunda kullanıcıya gösterilir: neden önemli, nasıl düzeltilir.">
        <Field label="Açıklama" hint="Bulgu mesajı olarak gösterilir.">
          <Textarea rows={3} value={form.description} onChange={(e) => set('description', e.target.value)} />
        </Field>
        <Field label="Öneri" hint="Nasıl düzeltilir?">
          <Textarea rows={2} value={form.recommendation} onChange={(e) => set('recommendation', e.target.value)} />
        </Field>
        <ChangedFields keys={['description', 'recommendation']} changes={changes} />
      </EditorSection>
    </>
  );
}

/** Required-field errors of a rule form (null = ok). */
export function ruleFormErrors(form: RuleInput) {
  return {
    code: !form.code.trim()
      ? 'Kod zorunludur'
      : !RULE_CODE_PATTERN.test(form.code.trim())
        ? 'Büyük harfle başlamalı; yalnızca A–Z, 0–9, _ ve - (2–32 karakter)'
        : null,
    name: !form.name.trim() ? 'Ad zorunludur' : null,
    pattern: form.kind === 'regex' && !form.pattern?.trim() ? 'Regex kuralı için desen zorunludur' : null,
    llm_prompt: form.kind === 'llm' && !form.llm_prompt?.trim() ? 'LLM kuralı için talimat zorunludur' : null,
  };
}

function ChangedBadge({keys, changes}: {keys: (keyof RuleInput)[]; changes?: FieldChanges}) {
  const n = changes ? keys.filter((k) => k in changes).length : 0;
  if (!n) return null;
  return (
    <span className="inline-flex h-5 shrink-0 items-center rounded-md bg-warn-soft px-1.5 text-[11px] font-semibold text-warn ring-1 ring-warn/30 ring-inset">
      {n} alan değişti
    </span>
  );
}

function ChangedFields({keys, changes}: {keys: (keyof RuleInput)[]; changes?: FieldChanges}) {
  const list = changes ? keys.filter((k) => k in changes) : [];
  if (!list.length) return null;
  return (
    <div className="rounded-lg border border-warn/35 bg-warn-soft/60 px-3 py-2.5">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-warn">Önceki değerler</p>
      <dl className="mt-1.5 flex flex-col gap-1.5">
        {list.map((k) => (
          <div key={k} className="grid gap-x-3 text-[12px] sm:grid-cols-[140px_minmax(0,1fr)]">
            <dt className="font-medium text-fg">{RULE_FIELD_LABEL[k] ?? k}</dt>
            <dd className="min-w-0 font-mono text-[11.5px] break-words whitespace-pre-wrap text-fg-muted line-through decoration-fg-subtle/60">
              {changes![k] || '—'}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function RuleEditor({open, rule, onClose}: {open: boolean; rule: Rule | null; onClose: () => void}) {
  const [form, setForm] = useState<RuleInput>(() => (rule ? ruleToInput(rule) : emptyRule()));
  const [touched, setTouched] = useState(false);
  const set = <K extends keyof RuleInput>(key: K, value: RuleInput[K]) => setForm((f) => ({...f, [key]: value}));
  const client = useQueryClient();
  const feedback = useFeedback();
  const lockedBuiltin = !!rule && rule.kind === 'builtin';

  const invalid = Object.values(ruleFormErrors(form)).some(Boolean);

  const save = useMutation({
    mutationFn: () => (rule ? api.rules.update(rule.id, toRulePayload(form)) : api.rules.create(toRulePayload(form))),
    onSuccess: () => {
      client.invalidateQueries({queryKey: qk.rules});
      client.invalidateQueries({queryKey: qk.groups});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success(rule ? 'Kural güncellendi' : 'Kural oluşturuldu', `${form.code} · ${form.name}`);
      onClose();
    },
  });

  const submit = () => {
    setTouched(true);
    if (!invalid) save.mutate();
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width="max-w-[1200px]"
      title={rule ? `Kuralı düzenle · ${rule.code}` : 'Yeni kural'}
      description="Kuralı tanımlayın, nasıl kontrol edileceğini ve nerede uygulanacağını seçin; sağdaki panelde örnek SQL üzerinde deneyin."
      footer={
        <>
          {save.error && (
            <span className="mr-auto flex min-w-0 items-start gap-1.5 text-xs text-bad" title={errorMessage(save.error)}>
              <TriangleAlert className="mt-px size-3.5 shrink-0" />
              <span className="line-clamp-3">Kaydedilemedi: {errorMessage(save.error)}</span>
            </span>
          )}
          <Button variant="ghost" onClick={onClose}>
            Vazgeç
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={submit}>
            {rule ? 'Değişiklikleri kaydet' : 'Kuralı oluştur'}
          </Button>
        </>
      }
    >
      <div className="grid lg:h-full lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <form
          className="flex flex-col gap-5 p-5 lg:overflow-y-auto"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <RuleFormFields form={form} set={set} touched={touched} lockedBuiltin={lockedBuiltin} onNavigate={onClose} />

          {/* 5 — İstisnalar (only for saved rules) */}
          {rule && (
            <EditorSection
              n={5}
              title="İstisnalar"
              hint="Belirli nesnelerde veya belirli ifadeleri içeren bulgular bundan sonraki analizlerde raporlanmaz."
            >
              <RuleExceptions rule={rule} />
            </EditorSection>
          )}
          <button type="submit" className="hidden" />
        </form>

        <RuleTester
          form={form}
          saved={rule ? ruleToInput(rule) : null}
          onSaveSample={(sample) => setForm((f) => ({...f, ...sample}))}
        />
      </div>
    </Drawer>
  );
}

function splitName(full: string): {schema: string; name: string} {
  const i = full.indexOf('.');
  return i < 0 ? {schema: 'dbo', name: full} : {schema: full.slice(0, i), name: full.slice(i + 1)};
}

type RuleSample = Pick<RuleInput, 'sample_sql' | 'sample_object_name' | 'sample_object_type' | 'sample_database'>;

/** Tester inputs for a rule's stored sample, falling back to the built-in sample procedure. */
export function sampleOf(r: RuleSample | null | undefined) {
  return {
    sql: r?.sample_sql || SAMPLE_PROCEDURE,
    objectName: r?.sample_object_name || 'dbo.usp_LoadFactSales',
    objectType: (r?.sample_object_type || 'PROCEDURE') as ObjectType,
    database: r?.sample_database || '',
  };
}

const sampleKey = (r: RuleSample | null | undefined) => JSON.stringify(sampleOf(r));

function RuleTester({form, saved, onSaveSample}: {form: RuleInput; saved: RuleInput | null; onSaveSample: (s: RuleSample) => void}) {
  const [initial] = useState(() => sampleOf(form));
  const [sql, setSql] = useState(initial.sql);
  const [objectName, setObjectName] = useState(initial.objectName);
  const [objectType, setObjectType] = useState<ObjectType>(initial.objectType);
  const [database, setDatabase] = useState(initial.database);
  const [result, setResult] = useState<{data: RuleTestResult; sql: string; signature: string} | null>(null);
  // The stored sample is not part of the rule logic: changing it must not mark results stale.
  const ruleSig = JSON.stringify({...form, sample_sql: null, sample_object_name: null, sample_object_type: null, sample_database: null});
  const signature = JSON.stringify([ruleSig, sql, objectName, objectType, database]);
  const current = {sql, objectName, objectType, database};
  const sampleDirty = sampleKey(form) !== sampleKey(saved);
  const inputsDiffer = JSON.stringify(current) !== sampleKey(form);
  const restore = () => {
    const s = sampleOf(saved);
    setSql(s.sql);
    setObjectName(s.objectName);
    setObjectType(s.objectType);
    setDatabase(s.database);
  };
  const saveSample = () =>
    onSaveSample({
      sample_sql: sql,
      sample_object_name: objectName.trim() || null,
      sample_object_type: objectType,
      sample_database: database.trim() || null,
    });

  const test = useMutation({
    mutationFn: () =>
      api.rules.test({
        rule: toRulePayload(form),
        sql,
        object_name: objectName || undefined,
        object_type: objectType,
        database: database.trim() || undefined,
      }),
    onSuccess: (data) => setResult({data, sql, signature}),
  });

  const marks = useMemo(
    () =>
      result
        ? buildLineMarks((result.data.findings ?? []).map((f) => ({line: f.line, severity: form.severity, message: f.message})))
        : undefined,
    [result, form.severity],
  );
  const stale = result && result.signature !== signature;
  const canTest = form.kind === 'regex' ? !!form.pattern?.trim() : form.kind === 'llm' ? !!form.llm_prompt?.trim() : true;
  const inScope = ruleApplies(form, {type: objectType, database: database.trim() || undefined, ...splitName(objectName)});
  const findings = result?.data.findings ?? [];
  const note = result && isInfoNote(result.data.error) ? result.data.error : null;
  const hardError = result && result.data.error && !note ? result.data.error : null;

  return (
    <div className="flex min-h-0 flex-col border-t border-line bg-canvas/60 lg:border-t-0 lg:border-l">
      <div className="flex items-center justify-between gap-2 border-b border-line px-5 py-3">
        <div className="flex items-center gap-2">
          <FlaskConical className="size-4 text-accent" />
          <h3 className="text-[13px] font-semibold text-fg">Canlı test</h3>
          <span className="hidden items-center gap-1 text-[11px] text-fg-subtle sm:flex">
            <Kbd>Ctrl</Kbd>
            <Kbd>↵</Kbd>
          </span>
        </div>
        <Button
          size="sm"
          variant="primary"
          loading={test.isPending}
          disabled={!canTest || !sql.trim()}
          icon={<Play className="size-3 fill-current" />}
          onClick={() => test.mutate()}
        >
          Test et
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 p-5 lg:overflow-y-auto">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_150px_140px]">
          <Field label="Nesne adı (şema.ad)">
            <Input mono inputSize="sm" value={objectName} onChange={(e) => setObjectName(e.target.value)} />
          </Field>
          <Field label="Nesne tipi">
            <Select value={objectType} onChange={(e) => setObjectType(e.target.value as ObjectType)}>
              {OBJECT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {OBJECT_TYPE_LABEL[t]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Veritabanı">
            <Input mono inputSize="sm" value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="isteğe bağlı" />
          </Field>
        </div>
        {!inScope && (
          <p className="flex items-start gap-1.5 text-[11.5px] text-warn">
            <Info className="mt-px size-3 shrink-0" />
            Bu test nesnesi kuralın kapsamı dışında; gerçek analizde bu kural bu nesneye uygulanmaz.
          </p>
        )}
        <Field
          label="Örnek SQL"
          aside={
            <span className="flex items-center gap-3">
              {sampleDirty && (
                <Tooltip content="Örnek forma kopyalandı; kural kaydedilince saklanır.">
                  <span className="inline-flex h-5 items-center rounded-md bg-warn-soft px-1.5 text-[11px] font-medium text-warn ring-1 ring-warn/30 ring-inset">örnek değişti</span>
                </Tooltip>
              )}
              <Tooltip content={saved?.sample_sql ? 'Kuralın kayıtlı örneğine dön' : 'Varsayılan örnek prosedüre dön'}>
                <button type="button" className="text-[11.5px] text-fg-subtle hover:text-fg" onClick={restore}>
                  Örneği geri yükle
                </button>
              </Tooltip>
              <Tooltip content="SQL, nesne adı, tip ve veritabanını kuralın örneği olarak kaydeder (kural kaydedilince).">
                <button
                  type="button"
                  disabled={!inputsDiffer || !sql.trim()}
                  className="text-[11.5px] font-medium text-accent hover:underline disabled:text-fg-subtle disabled:no-underline disabled:opacity-60"
                  onClick={saveSample}
                >
                  Örnek olarak kaydet
                </button>
              </Tooltip>
            </span>
          }
        >
          <Textarea
            mono
            rows={10}
            wrap="off"
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && canTest) {
                e.preventDefault();
                test.mutate();
              }
            }}
            className="bg-surface"
          />
        </Field>

        {test.error && <Alert tone="bad" title="Test çalıştırılamadı">{errorMessage(test.error)}</Alert>}
        {result && (
          <div className={cn('flex flex-col gap-3 transition-opacity', stale && 'opacity-60')}>
            {stale && <p className="text-[11.5px] text-warn">Kural veya örnek değişti — sonuçları güncellemek için yeniden test edin.</p>}
            {hardError ? (
              <Alert tone="bad" title="Kural hatası">
                <span className="font-mono text-[12px]">{hardError}</span>
              </Alert>
            ) : (
              <>
                {note && (
                  <Alert tone="info" title="Not">
                    {note}
                  </Alert>
                )}
                {findings.length === 0 ? (
                  <Alert tone="ok" title="Bulgu yok">
                    Bu örnekte kural tetiklenmedi.
                  </Alert>
                ) : (
                  <Alert tone="warn" title={`${findings.length} bulgu`}>
                    Vurgulanan satırlarda kural tetiklendi.
                  </Alert>
                )}
                <div className="overflow-hidden rounded-lg border border-line">
                  <SqlViewer source={result.sql} marks={marks} maxHeight="320px" />
                </div>
                {findings.length > 0 && (
                  <ul className="flex flex-col divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
                    {findings.map((f, i) => (
                      <li key={i} className="flex items-start gap-3 px-3 py-2">
                        <span className="mt-0.5 shrink-0 rounded bg-surface-3 px-1.5 font-mono text-[11px] text-fg-muted tnum">
                          {f.line ? `L${f.line}` : '—'}
                        </span>
                        <div className="min-w-0">
                          <p className="truncate font-mono text-[11.5px] text-fg">{f.snippet || '—'}</p>
                          <p className="mt-0.5 text-xs text-fg-subtle">{f.message}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        )}
        {!result && !test.error && (
          <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line-strong px-4 py-6 text-center text-xs text-fg-subtle">
            {canTest ? (
              <>
                <CircleCheck className="size-4" />
                Kuralı örnek SQL üzerinde denemek için “Test et”e basın.
                {(form.kind === 'builtin' || form.requires_metadata) && (
                  <span className="max-w-sm text-[11.5px]">Bu kural katalog metadatası kullanır; testte metadata boş kabul edilir, tam sonuç için analiz çalıştırın.</span>
                )}
              </>
            ) : (
              <>
                <TriangleAlert className="size-4" />
                Test için önce {form.kind === 'regex' ? 'bir desen' : 'LLM talimatı'} girin.
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
