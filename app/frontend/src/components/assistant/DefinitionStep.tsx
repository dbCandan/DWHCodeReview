import {useEffect, useMemo, useState} from 'react';
import {Link} from 'react-router';
import {useQuery} from '@tanstack/react-query';
import {ChevronDown, CircleCheck, CircleX, FlaskConical, Play, Plus, Settings2, Sparkles, Trash2} from 'lucide-react';
import {api} from '@/lib/api';
import {qk, useConnections, useLlmSettings} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {OBJECT_TYPE_LABEL, OBJECT_TYPES} from '@/lib/format';
import {SEVERITIES, SEVERITY_LABEL} from '@/lib/severity';
import {
  DESCRIPTION_MAX,
  emptyExample,
  MAX_EXAMPLES,
  SAMPLE_SIZES,
  validateAssistantForm,
  type AssistantForm,
  type ExampleDraft,
} from '@/lib/assistant';
import type {RuleKind, Severity} from '@/types';
import {Card, CardHeader} from '@/components/ui/Card';
import {Button} from '@/components/ui/Button';
import {Field, Input, Textarea} from '@/components/ui/Input';
import {MultiSelect, Select} from '@/components/ui/Select';
import {Chip, Segmented} from '@/components/ui/Tabs';
import {Switch} from '@/components/ui/Switch';
import {Alert} from '@/components/ui/Feedback';

/** Monospace SQL textarea with a line-number gutter; grows with its content. */
export function SqlInput({value, onChange, placeholder, invalid}: {value: string; onChange: (v: string) => void; placeholder?: string; invalid?: boolean}) {
  const lines = Math.max(4, value.split('\n').length);
  return (
    <div
      className={cn(
        'flex overflow-hidden rounded-lg border bg-surface-2/60 transition-[border-color,box-shadow] focus-within:border-accent focus-within:ring-3 focus-within:ring-accent/25',
        invalid ? 'border-bad' : 'border-line-control hover:border-fg-subtle',
      )}
    >
      <div aria-hidden className="shrink-0 border-r border-line bg-surface-2 px-2 py-2 text-right font-mono text-[11px] leading-[1.6] text-fg-subtle select-none tnum">
        {Array.from({length: lines}, (_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        wrap="off"
        rows={lines}
        className="min-w-0 flex-1 resize-none overflow-x-auto overflow-y-hidden bg-transparent px-2.5 py-2 font-mono text-[12px] leading-[1.6] text-fg outline-none placeholder:text-fg-subtle"
      />
    </div>
  );
}

function ExampleList({
  tone,
  title,
  hint,
  items,
  onChange,
  error,
  required,
  placeholder,
}: {
  tone: 'positive' | 'negative';
  title: string;
  hint: string;
  items: ExampleDraft[];
  onChange: (items: ExampleDraft[]) => void;
  error?: string;
  required?: boolean;
  placeholder: string;
}) {
  const update = (i: number, patch: Partial<ExampleDraft>) => onChange(items.map((e, j) => (j === i ? {...e, ...patch} : e)));
  const Icon = tone === 'positive' ? CircleCheck : CircleX;
  return (
    <Card>
      <CardHeader
        icon={<Icon className={cn('size-4', tone === 'positive' ? 'text-ok' : 'text-fg-muted')} />}
        title={
          <>
            {title} {required && <span className="text-bad">*</span>}
            <span className="ml-1.5 font-normal text-fg-subtle tnum">
              {items.length} / {MAX_EXAMPLES}
            </span>
          </>
        }
        description={hint}
        actions={
          <Button size="sm" icon={<Plus className="size-3.5" />} disabled={items.length >= MAX_EXAMPLES} onClick={() => onChange([...items, emptyExample()])}>
            Örnek ekle
          </Button>
        }
      />
      <div className="flex flex-col gap-4 p-4">
        {items.length === 0 && <p className="text-[12.5px] text-fg-subtle">İsteğe bağlı. Kuralın yanlışlıkla yakalamaması gereken kodları ekleyin; LLM bunlarla deseni daraltır.</p>}
        {items.map((e, i) => (
          <div key={i} className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <span
                className={cn(
                  'inline-flex h-5 items-center rounded-md px-1.5 text-[11px] font-semibold ring-1 ring-inset',
                  tone === 'positive' ? 'bg-ok-soft text-ok ring-ok/30' : 'bg-surface-3 text-fg-muted ring-line-strong',
                )}
              >
                {tone === 'positive' ? 'Yakalanmalı' : 'Yakalanmamalı'} · Örnek {i + 1}
              </span>
              {(items.length > 1 || !required) && (
                <Button variant="ghost" size="xs" iconOnly aria-label={`Örnek ${i + 1} sil`} className="hover:text-bad" onClick={() => onChange(items.filter((_, j) => j !== i))}>
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </div>
            <SqlInput value={e.sql} onChange={(sql) => update(i, {sql})} placeholder={placeholder} invalid={!!error && required && i === 0 && !e.sql.trim()} />
            <Input inputSize="sm" value={e.note} onChange={(ev) => update(i, {note: ev.target.value})} placeholder="Not (isteğe bağlı): bu örnekte neyin yakalanması/yakalanmaması gerektiği" />
          </div>
        ))}
        {error && <p className="text-[11.5px] text-bad">{error}</p>}
      </div>
    </Card>
  );
}

const KIND_OPTIONS: {value: RuleKind | ''; label: string}[] = [
  {value: '', label: 'Otomatik'},
  {value: 'regex', label: 'Regex'},
  {value: 'llm', label: 'LLM'},
  // No "Yerleşik" choice: built-in checks are code-level; the assistant may only reuse an existing one on its own.
];

export function DefinitionStep({
  form,
  setForm,
  onStart,
  starting,
  startError,
}: {
  form: AssistantForm;
  setForm: (f: AssistantForm) => void;
  onStart: () => void;
  starting: boolean;
  startError: string | null;
}) {
  const [touched, setTouched] = useState(false);
  const [advanced, setAdvanced] = useState(!!(form.preferred_kind || form.severity_hint));
  const llm = useLlmSettings();
  const connections = useConnections();
  const set = <K extends keyof AssistantForm>(k: K, v: AssistantForm[K]) => setForm({...form, [k]: v});
  const errors = validateAssistantForm(form);
  const invalid = Object.values(errors).some(Boolean);
  const llmOff = llm.data !== undefined && !llm.data.enabled;
  const connectionId = form.connection_id ?? connections.data?.[0]?.id ?? null;
  const dbs = useQuery({
    queryKey: qk.databases(connectionId ?? -1),
    queryFn: () => api.connections.databases(connectionId!),
    enabled: form.noiseEnabled && connectionId !== null,
    retry: false,
  });
  const dbOptions = useMemo(() => (dbs.data ?? []).map((d) => ({value: d, label: d})), [dbs.data]);

  // Default the noise-test connection to the first one once connections are known.
  useEffect(() => {
    if (form.noiseEnabled && form.connection_id === null && connectionId !== null) setForm({...form, connection_id: connectionId});
  }, [form, connectionId, setForm]);

  const start = () => {
    setTouched(true);
    if (!invalid && !llmOff) onStart();
  };

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-4">
        <Card>
          <CardHeader
            icon={<Sparkles className="size-4 text-accent" />}
            title="Ne denetlensin?"
            description="Kuralın amacını kendi cümlelerinizle yazın. LLM mevcut kuralları inceler; uygun bir kural varsa onu genişletmeyi, yoksa yeni kural önerir."
          />
          <div className="p-4">
            <Field
              label="Kural açıklaması"
              required
              error={touched && errors.description}
              aside={<span className="text-[11px] text-fg-subtle tnum">{form.description.length} / {DESCRIPTION_MAX}</span>}
            >
              <Textarea
                data-autofocus
                rows={5}
                maxLength={DESCRIPTION_MAX}
                value={form.description}
                onChange={(e) => set('description', e.target.value)}
                aria-invalid={touched && !!errors.description}
                placeholder={
                  'Örn. Prosedürlerde OPTION (RECOMPILE) ipucu kullanılmamalı; plan önbelleğini etkisiz bırakıyor. ' +
                  'Yalnızca sorgu ipucu olarak kullanımı yakala, yorum satırlarını dikkate alma.'
                }
              />
            </Field>
          </div>
        </Card>

        <ExampleList
          tone="positive"
          required
          title="Yakalanması gereken örnekler"
          hint="Kuralın bulgu üretmesi gereken kısa SQL parçaları (en az 1)."
          items={form.positives}
          onChange={(v) => set('positives', v)}
          error={touched ? errors.positives : undefined}
          placeholder={'SELECT *\nFROM dbo.Sales\nOPTION (RECOMPILE);'}
        />
        <ExampleList
          tone="negative"
          title="Yakalanmaması gereken örnekler"
          hint="Benzer görünen ama ihlal olmayan kodlar (isteğe bağlı)."
          items={form.negatives}
          onChange={(v) => set('negatives', v)}
          error={touched ? errors.negatives : undefined}
          placeholder={'-- OPTION (RECOMPILE) yorum içinde\nSELECT 1;'}
        />

        <Card>
          <button
            type="button"
            onClick={() => setAdvanced(!advanced)}
            aria-expanded={advanced}
            className="flex w-full items-center gap-2.5 px-4 py-3 text-left"
          >
            <Settings2 className="size-4 text-fg-subtle" />
            <span className="flex-1">
              <span className="block text-[13px] font-semibold text-fg">Gelişmiş</span>
              <span className="block text-xs text-fg-subtle">Tür ve önem için ipucu; LLM son kararı yine kendisi verir.</span>
            </span>
            <ChevronDown className={cn('size-4 text-fg-subtle transition-transform', advanced && 'rotate-180')} />
          </button>
          {advanced && (
            <div className="grid gap-4 border-t border-line p-4 sm:grid-cols-2">
              <Field label="Tür tercihi">
                <Segmented size="sm" value={form.preferred_kind} onChange={(v) => set('preferred_kind', v)} options={KIND_OPTIONS} />
              </Field>
              <Field label="Önem ipucu">
                <Select value={form.severity_hint} onChange={(e) => set('severity_hint', e.target.value as Severity | '')}>
                  <option value="">Otomatik</option>
                  {SEVERITIES.map((s) => (
                    <option key={s} value={s}>
                      {SEVERITY_LABEL[s]}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
          )}
        </Card>
      </div>

      <div className="flex flex-col gap-4 xl:sticky xl:top-4">
        <Card>
          <CardHeader
            icon={<FlaskConical className="size-4" />}
            title="Gürültü testi"
            description="Önerilen kural, kaydetmeden önce gerçek veride rastgele nesneler üzerinde denenir."
            actions={<Switch checked={form.noiseEnabled} onChange={(v) => set('noiseEnabled', v)} label="Gürültü testi" />}
          />
          {form.noiseEnabled ? (
            <div className="flex flex-col gap-3 p-4">
              <Field label="Bağlantı">
                <Select
                  value={form.connection_id ?? ''}
                  onChange={(e) => setForm({...form, connection_id: e.target.value ? Number(e.target.value) : null, databases: []})}
                >
                  {(connections.data ?? []).length === 0 && <option value="">Bağlantı yok</option>}
                  {(connections.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Veritabanları" hint={dbs.isError ? 'Veritabanı listesi alınamadı.' : undefined}>
                <MultiSelect
                  options={dbOptions}
                  loading={dbs.isFetching && !dbs.data}
                  value={form.databases}
                  onChange={(v) => set('databases', v)}
                  placeholder="Veritabanı seçin…"
                  searchPlaceholder="Veritabanı ara…"
                  emptyText="Veritabanı bulunamadı"
                />
              </Field>
              <Field label="Nesne tipleri" hint={form.object_types.length ? undefined : 'Seçilmezse önerilen kuralın kapsamı kullanılır.'}>
                <div className="flex flex-wrap gap-1.5">
                  {OBJECT_TYPES.map((t) => {
                    const on = form.object_types.includes(t);
                    return (
                      <Chip key={t} active={on} onClick={() => set('object_types', on ? form.object_types.filter((x) => x !== t) : [...form.object_types, t])}>
                        {OBJECT_TYPE_LABEL[t]}
                      </Chip>
                    );
                  })}
                </div>
              </Field>
              <Field label="Örneklem büyüklüğü (nesne)" hint="LLM kurallarında en fazla 15 nesne modele gönderilir.">
                <Segmented
                  size="sm"
                  className="flex w-full [&>button]:flex-1"
                  value={String(form.sample_size)}
                  onChange={(v) => set('sample_size', Number(v))}
                  options={SAMPLE_SIZES.map((n) => ({value: String(n), label: String(n)}))}
                />
              </Field>
              {touched && errors.noise && <p className="text-[11.5px] text-bad">{errors.noise}</p>}
            </div>
          ) : (
            <p className="p-4 text-[12.5px] text-fg-subtle">Kapalı: öneri yalnızca verdiğiniz örneklerle doğrulanır.</p>
          )}
        </Card>

        <Card className="p-4">
          {llmOff && (
            <Alert
              tone="warn"
              className="mb-3"
              title="LLM ayarları devre dışı"
              action={
                <Link to="/settings" className="text-xs font-medium text-accent hover:underline">
                  Ayarlara git
                </Link>
              }
            >
              Kural asistanı LLM gerektirir.
            </Alert>
          )}
          {startError && (
            <Alert tone="bad" className="mb-3" title="Asistan başlatılamadı">
              {startError}
            </Alert>
          )}
          <Button variant="primary" size="lg" className="w-full" loading={starting} disabled={llmOff} icon={<Play className="size-4 fill-current" />} onClick={start}>
            Asistanı başlat
          </Button>
          <p className="mt-2 text-[11.5px] leading-4 text-fg-subtle">
            Eşleştirme → taslak → örneklerle doğrulama (en fazla 3 tur){form.noiseEnabled ? ' → gürültü testi' : ''}. Hiçbir şey onayınız olmadan kaydedilmez.
          </p>
        </Card>
      </div>
    </div>
  );
}
