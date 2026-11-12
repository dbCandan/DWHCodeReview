import {useState} from 'react';
import {useMutation, useQueryClient} from '@tanstack/react-query';
import {Info, ShieldOff} from 'lucide-react';
import {api, errorMessage} from '@/lib/api';
import {qk} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {exceptionPreview, MAX_REASON_LENGTH, suggestSnippetPattern, toExceptionPayload, validateException} from '@/lib/exceptions';
import {regexWarning} from '@/lib/rules';
import type {RuleExceptionInput} from '@/types';
import {Dialog} from '@/components/ui/Overlay';
import {Button} from '@/components/ui/Button';
import {Field, Input, Textarea} from '@/components/ui/Input';
import {Checkbox} from '@/components/ui/Switch';
import {Alert} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';

export interface ExceptionTarget {
  rule: {id: number | null; code: string; name: string};
  /** Object of the finding; when absent the object fields are typed manually. */
  object?: {database: string; schema: string; name: string} | null;
  snippet?: string | null;
}

function ScopeOption({checked, onSelect, title, detail}: {checked: boolean; onSelect: () => void; title: string; detail?: string}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      onClick={onSelect}
      className={cn(
        'flex w-full items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors',
        checked ? 'border-accent bg-accent-soft' : 'border-line-control/60 bg-surface-2/40 hover:border-fg-subtle hover:bg-surface-2',
      )}
    >
      <span
        className={cn(
          'mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border',
          checked ? 'border-accent-solid bg-accent-solid' : 'border-line-control bg-surface',
        )}
      >
        {checked && <span className="size-1.5 rounded-full bg-white" />}
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-fg">{title}</span>
        {detail && <span className="block truncate font-mono text-[11.5px] text-fg-muted">{detail}</span>}
      </span>
    </button>
  );
}

/** Mount with a `key` per target so the form state starts fresh. */
export function ExceptionDialog({target, onClose}: {target: ExceptionTarget | null; onClose: () => void}) {
  const obj = target?.object ?? null;
  const [scope, setScope] = useState<'object' | 'all'>('object');
  const [manual, setManual] = useState({database: '', schema: '', object_name: ''});
  const suggested = suggestSnippetPattern(target?.snippet);
  const [usePattern, setUsePattern] = useState(!!suggested);
  const [pattern, setPattern] = useState(suggested);
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const client = useQueryClient();
  const feedback = useFeedback();

  const input: RuleExceptionInput = {
    ...(obj
      ? scope === 'object'
        ? {database: obj.database, schema: obj.schema, object_name: obj.name}
        : {}
      : manual),
    snippet_pattern: usePattern ? pattern : null,
    reason,
  };
  const problem = validateException(input);
  const patternWarning = usePattern ? regexWarning(pattern) : null;
  const ruleId = target?.rule.id ?? null;

  const save = useMutation({
    mutationFn: () => api.exceptions.create(ruleId!, toExceptionPayload(input)),
    onSuccess: (created) => {
      client.invalidateQueries({queryKey: qk.exceptions(created.rule_id ?? ruleId!)});
      client.invalidateQueries({queryKey: qk.rules});
      feedback.success('İstisna tanımlandı', 'Bundan sonraki analizlerde uygulanır; mevcut analizin sonuçları değişmez.');
      onClose();
    },
    onError: (e) => feedback.error('İstisna kaydedilemedi', e),
  });

  const submit = () => {
    setTouched(true);
    if (!problem && ruleId !== null) save.mutate();
  };

  return (
    <Dialog
      open={target !== null}
      onClose={onClose}
      size="lg"
      icon={<ShieldOff className="size-4 text-accent" />}
      title="İstisna tanımla"
      description="Eşleşen bulgular sonraki analizlerde kaydedilmez, yalnızca “istisna nedeniyle gizlendi” olarak sayılır."
      footer={
        <>
          {save.error && <span className="mr-auto line-clamp-2 text-xs text-bad">{errorMessage(save.error)}</span>}
          <Button variant="ghost" onClick={onClose}>
            Vazgeç
          </Button>
          <Button variant="primary" loading={save.isPending} disabled={ruleId === null} onClick={submit}>
            İstisnayı kaydet
          </Button>
        </>
      }
    >
      {target && (
        <div className="flex flex-col gap-4">
          <Field label="Kural">
            <div className="flex h-8 items-center gap-2 rounded-lg border border-line-strong bg-surface-2/60 px-2.5 text-[13px]">
              <span className="font-mono text-[12px] font-semibold text-fg">{target.rule.code}</span>
              <span className="truncate text-fg-muted">{target.rule.name}</span>
            </div>
          </Field>
          {ruleId === null && (
            <Alert tone="warn" title="Kural artık mevcut değil">
              Bu bulgunun kuralı silinmiş; istisna tanımlanamaz.
            </Alert>
          )}

          {obj ? (
            <Field label="Kapsam">
              <div role="radiogroup" className="grid gap-2 sm:grid-cols-2">
                <ScopeOption
                  checked={scope === 'object'}
                  onSelect={() => setScope('object')}
                  title="Yalnızca bu nesne"
                  detail={`${obj.database}.${obj.schema}.${obj.name}`}
                />
                <ScopeOption checked={scope === 'all'} onSelect={() => {
                    setScope('all');
                    setUsePattern(true);
                  }} title="Tüm nesneler" detail="Aşağıdaki ifade deseni zorunlu olur" />
              </div>
            </Field>
          ) : (
            <Field label="Nesne" hint="Boş bırakılan alan “hepsi” demektir. Nesne adı şemasız yazılır.">
              <div className="grid gap-2 sm:grid-cols-3">
                <Input mono placeholder="Veritabanı" value={manual.database} onChange={(e) => setManual({...manual, database: e.target.value})} />
                <Input mono placeholder="Şema" value={manual.schema} onChange={(e) => setManual({...manual, schema: e.target.value})} />
                <Input mono placeholder="Nesne adı" value={manual.object_name} onChange={(e) => setManual({...manual, object_name: e.target.value})} />
              </div>
            </Field>
          )}

          <div className="flex flex-col gap-2 rounded-lg border border-line-strong bg-surface-2/40 p-3">
            <label className="flex cursor-pointer items-center gap-2.5 text-[13px] font-medium text-fg">
              <Checkbox checked={usePattern} onChange={setUsePattern} label="İfade desenini kullan" />
              Yalnızca şu ifadeyi içeren bulgular
            </label>
            <Input
              mono
              value={pattern}
              disabled={!usePattern}
              onChange={(e) => setPattern(e.target.value)}
              placeholder={'OPTION\\s*\\(\\s*MIN_GRANT_PERCENT'}
              aria-label="İfade deseni (regex)"
            />
            <p className="text-[11.5px] text-fg-subtle">
              Regex; bulgunun kod parçası ve mesajında büyük/küçük harf duyarsız aranır.
              {suggested ? ' Bulgudaki koddan önerildi; gerekirse düzenleyin.' : ''}
            </p>
            {patternWarning && <p className="text-[11.5px] text-warn">{patternWarning}</p>}
          </div>

          <Field
            label="Gerekçe"
            required
            error={touched && !reason.trim() ? 'İstisna nedeni zorunludur.' : undefined}
            aside={<span className="text-[11px] text-fg-subtle tnum">{reason.length} / {MAX_REASON_LENGTH}</span>}
          >
            <Textarea
              data-autofocus
              rows={2}
              maxLength={MAX_REASON_LENGTH}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Örn. Bu prosedürde bellek sınırı bilinçli olarak ayarlanıyor (DBA onayı)."
              aria-invalid={touched && !reason.trim()}
            />
          </Field>

          <div className="flex items-start gap-2 rounded-lg border border-accent/30 bg-accent-soft px-3 py-2.5 text-[12.5px] text-fg">
            <Info className="mt-0.5 size-3.5 shrink-0 text-accent" />
            <span>{exceptionPreview(target.rule.code, input, input.snippet_pattern)}</span>
          </div>
          {touched && problem && problem !== 'İstisna nedeni zorunludur.' && (
            <Alert tone="warn" title="İstisna kaydedilemez">
              {problem}
            </Alert>
          )}
        </div>
      )}
    </Dialog>
  );
}
