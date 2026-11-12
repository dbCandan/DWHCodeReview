import {useMemo, useState} from 'react';
import {Link} from 'react-router';
import {ArrowRight, CircleCheck, CircleX, FlaskConical, GitMerge, RefreshCw, Save, Sparkles, SquarePlus, TriangleAlert, X} from 'lucide-react';
import {useGroups} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {formatDuration, formatNumber} from '@/lib/format';
import {diffProposal, noiseDelta} from '@/lib/assistant';
import type {AssistantCaseResult, AssistantSession, RuleInput} from '@/types';
import {emptyRule, ruleFormErrors, RuleFormFields, toRulePayload} from '@/components/rules/RuleEditor';
import {Card, CardHeader} from '@/components/ui/Card';
import {Button, buttonClass} from '@/components/ui/Button';
import {Checkbox} from '@/components/ui/Switch';
import {Alert} from '@/components/ui/Feedback';
import {Table, THead, Th, Tr, Td} from '@/components/ui/Table';
import {Tooltip} from '@/components/ui/Tooltip';

/** Proposal with every RuleInput field present (the LLM output may omit optional ones). */
export function normalizeProposal(p: RuleInput | null | undefined): RuleInput {
  const base = emptyRule();
  if (!p) return base;
  const out = {...base} as Record<string, unknown>;
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== null) out[k] = v;
  const r = out as unknown as RuleInput;
  return {...r, pattern: r.pattern ?? '', llm_prompt: r.llm_prompt ?? '', precondition: r.precondition ?? '', name_pattern: r.name_pattern ?? ''};
}

function PassPill({passed, label}: {passed: boolean | null | undefined; label?: string}) {
  if (passed === null || passed === undefined) return <span className="text-xs text-fg-subtle">—</span>;
  return (
    <span
      className={cn(
        'inline-flex h-5 items-center gap-1 rounded-md px-1.5 text-[11px] font-semibold ring-1 ring-inset',
        passed ? 'bg-ok-soft text-ok ring-ok/30' : 'bg-bad-soft text-bad ring-bad/30',
      )}
    >
      {passed ? <CircleCheck className="size-3" /> : <CircleX className="size-3" />}
      {label ?? (passed ? 'Geçti' : 'Kaldı')}
    </span>
  );
}

function exampleSql(session: AssistantSession, c: AssistantCaseResult): {sql: string; note: string | null} {
  const list = c.kind === 'positive' ? session.request?.positive_examples : session.request?.negative_examples;
  const e = list?.[c.index];
  return {sql: e?.sql ?? '', note: e?.note ?? null};
}

function ValidationCard({session, stale}: {session: AssistantSession; stale: boolean}) {
  const v = session.validation;
  const extend = session.decision === 'extend';
  return (
    <Card className="overflow-hidden">
      <CardHeader
        icon={v?.passed ? <CircleCheck className="size-4 text-ok" /> : <CircleX className="size-4 text-bad" />}
        title="Örneklerle doğrulama"
        description={
          v
            ? `${v.cases.filter((c) => c.passed).length} / ${v.cases.length} örnek geçti · ${v.iterations} tur${stale ? ' · alanlar değişti, sonuçlar güncel değil' : ''}`
            : 'Doğrulama sonucu yok.'
        }
        actions={v && <PassPill passed={v.passed} label={v.passed ? 'Tümü geçti' : 'Başarısız örnek var'} />}
      />
      {v && v.cases.length > 0 && (
        <div className={cn(stale && 'opacity-60')}>
          <Table>
            <THead>
              <tr>
                <Th className="w-28">Beklenen</Th>
                <Th>Örnek</Th>
                <Th className="w-20">Sonuç</Th>
                <Th className="w-24">Satırlar</Th>
                {extend && <Th className="w-24">Eski kural</Th>}
              </tr>
            </THead>
            <tbody>
              {v.cases.map((c) => {
                const ex = exampleSql(session, c);
                const firstLine = ex.sql.split('\n').find((l) => l.trim()) ?? '';
                return (
                  <Tr key={`${c.kind}-${c.index}`}>
                    <Td>
                      <span className="text-xs font-medium text-fg">{c.kind === 'positive' ? 'Yakalanmalı' : 'Yakalanmamalı'}</span>
                      <span className="block text-[11px] text-fg-subtle">Örnek {c.index + 1}</span>
                    </Td>
                    <Td className="max-w-0">
                      <Tooltip content={<pre className="max-h-60 overflow-hidden font-mono text-[11px] whitespace-pre-wrap">{ex.sql}</pre>}>
                        <code className="block truncate font-mono text-[11.5px] text-fg">{firstLine || '—'}</code>
                      </Tooltip>
                      {ex.note && <span className="block truncate text-[11px] text-fg-subtle">{ex.note}</span>}
                      {c.error && <span className="block truncate text-[11px] text-bad">{c.error}</span>}
                    </Td>
                    <Td>
                      <PassPill passed={c.passed} />
                    </Td>
                    <Td className="max-w-0">
                      {c.findings.length === 0 ? (
                        <span className="text-xs text-fg-subtle">bulgu yok</span>
                      ) : (
                        <Tooltip content={c.findings.map((f) => `${f.line ? `L${f.line}` : '—'}: ${f.message}`).join('\n')}>
                          <span className="block truncate font-mono text-[11.5px] text-fg-muted">
                            {c.findings.map((f) => (f.line ? `L${f.line}` : '—')).join(', ')}
                          </span>
                        </Tooltip>
                      )}
                    </Td>
                    {extend && (
                      <Td>
                        <PassPill passed={c.old_passed} />
                      </Td>
                    )}
                  </Tr>
                );
              })}
            </tbody>
          </Table>
        </div>
      )}
    </Card>
  );
}

function NoiseCard({session, stale}: {session: AssistantSession; stale: boolean}) {
  const n = session.noise;
  if (!n || n.status === 'skipped')
    return (
      <Card className="p-4">
        <p className="flex items-center gap-2 text-[13px] font-semibold text-fg">
          <FlaskConical className="size-4 text-fg-subtle" /> Gürültü testi
        </p>
        <p className="mt-1 text-[12.5px] text-fg-subtle">{n?.note || 'Bu oturumda gürültü testi yapılmadı.'}</p>
      </Card>
    );
  const delta = noiseDelta(n.findings, n.old_findings);
  return (
    <Card className={cn('overflow-hidden', stale && 'opacity-70')}>
      <CardHeader
        icon={<FlaskConical className="size-4" />}
        title="Gürültü testi"
        description={`${formatNumber(n.sampled)} rastgele nesne · ${n.llm_calls} LLM çağrısı · ${formatDuration(n.duration_ms)}`}
        actions={n.status === 'failed' ? <PassPill passed={false} label="Başarısız" /> : undefined}
      />
      <div className="grid grid-cols-3 gap-px border-b border-line bg-line">
        {[
          {label: 'Örneklem', value: formatNumber(n.sampled)},
          {label: 'Bulgulu nesne', value: formatNumber(n.objects_with_findings)},
          {
            label: 'Toplam bulgu',
            value:
              n.old_findings !== null && n.old_findings !== undefined ? (
                <span className="flex items-baseline gap-1.5">
                  <span className="text-fg-muted">{formatNumber(n.old_findings)}</span>
                  <ArrowRight className="size-3.5 self-center text-fg-subtle" />
                  {formatNumber(n.findings)}
                  <span className={cn('text-xs font-semibold', delta?.startsWith('+') ? 'text-warn' : 'text-fg-muted')}>{delta}</span>
                </span>
              ) : (
                formatNumber(n.findings)
              ),
          },
        ].map((s) => (
          <div key={s.label} className="bg-surface px-4 py-3">
            <p className="text-[11px] text-fg-subtle">{s.label}</p>
            <div className="mt-0.5 text-[18px] font-semibold text-fg tnum">{s.value}</div>
          </div>
        ))}
      </div>
      {n.note && <p className="border-b border-line px-4 py-2 text-[12px] text-fg-muted">{n.note}</p>}
      {n.examples.length > 0 ? (
        <ul className="divide-y divide-line">
          {n.examples.map((e, i) => (
            <li key={i} className="flex items-start gap-3 px-4 py-2">
              <span className="mt-0.5 shrink-0 rounded bg-surface-3 px-1.5 font-mono text-[11px] text-fg-muted tnum">{e.line ? `L${e.line}` : '—'}</span>
              <div className="min-w-0">
                <p className="truncate font-mono text-[11.5px] text-fg-muted">{e.object_label}</p>
                <p className="truncate font-mono text-[11.5px] text-fg">{e.snippet || '—'}</p>
                <p className="truncate text-[11.5px] text-fg-subtle">{e.message}</p>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        n.status === 'done' && <p className="px-4 py-3 text-[12.5px] text-ok">Örneklemde hiç bulgu yok — gürültü beklenmiyor.</p>
      )}
    </Card>
  );
}

export function ProposalStep({
  session,
  onRevalidate,
  revalidating,
  onSave,
  saving,
  onDiscard,
}: {
  session: AssistantSession;
  onRevalidate: (proposal: RuleInput, runNoise: boolean) => void;
  revalidating: boolean;
  onSave: (proposal: RuleInput, confirmFailed: boolean) => void;
  saving: boolean;
  onDiscard: () => void;
}) {
  const initial = useMemo(() => normalizeProposal(session.proposal), [session.proposal]);
  const [form, setForm] = useState<RuleInput>(initial);
  const [touched, setTouched] = useState(false);
  const [runNoise, setRunNoise] = useState(!!session.request?.noise);
  const set = <K extends keyof RuleInput>(key: K, value: RuleInput[K]) => setForm((f) => ({...f, [key]: value}));
  const groups = useGroups();
  const groupNames = useMemo(() => new Map((groups.data ?? []).map((g) => [g.id, g.name])), [groups.data]);
  const extend = session.decision === 'extend';
  const saved = session.status === 'saved';
  const changes = useMemo(() => (extend ? diffProposal(form, session.original, groupNames) : undefined), [extend, form, session.original, groupNames]);
  const dirty = JSON.stringify(toRulePayload(form)) !== JSON.stringify(toRulePayload(initial));
  const invalid = Object.values(ruleFormErrors(form)).some(Boolean);
  const validationFailed = !!session.validation && !session.validation.passed;

  const save = () => {
    setTouched(true);
    if (!invalid) onSave(toRulePayload(form), validationFailed || dirty);
  };

  return (
    <div className="flex flex-col gap-4">
      {saved && (
        <Alert
          tone="ok"
          title="Kural kaydedildi"
          action={
            session.saved_rule_id ? (
              <Link to={`/rules?edit=${session.saved_rule_id}`} className={buttonClass('secondary', 'sm')}>
                Kuralı aç <ArrowRight className="size-3.5" />
              </Link>
            ) : undefined
          }
        >
          Bu oturum tamamlandı ve salt okunurdur.
        </Alert>
      )}

      <Card className="relative overflow-hidden">
        <div className={cn('absolute inset-y-0 left-0 w-[3px]', extend ? 'bg-warn' : 'bg-accent')} />
        <div className="flex items-start gap-3 p-4 pl-5">
          <span
            className={cn(
              'flex size-9 shrink-0 items-center justify-center rounded-lg border',
              extend ? 'border-warn/35 bg-warn-soft text-warn' : 'border-accent/35 bg-accent-soft text-accent',
            )}
          >
            {extend ? <GitMerge className="size-4" /> : <SquarePlus className="size-4" />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">LLM kararı</p>
            <h3 className="mt-0.5 text-[15px] font-semibold text-fg">
              {extend ? (
                <>
                  Mevcut kurala dahil edilecek: <span className="font-mono">{session.target_rule_code ?? session.original?.code}</span>
                  {session.original?.name && <span className="font-normal text-fg-muted"> — {session.original.name}</span>}
                </>
              ) : (
                'Yeni kural oluşturulacak'
              )}
            </h3>
            {session.rationale && <p className="mt-1.5 text-[12.5px] leading-5 text-fg-muted">{session.rationale}</p>}
            {extend && session.change_summary && (
              <div className="mt-2.5 rounded-lg border border-line-strong bg-surface-2/50 px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Değişiklik özeti</p>
                <p className="mt-0.5 text-[12.5px] leading-5 whitespace-pre-wrap text-fg">{session.change_summary}</p>
              </div>
            )}
          </div>
        </div>
        {session.builtin_needed && (
          <div className="border-t border-warn/30 bg-warn-soft px-5 py-3">
            <p className="flex items-start gap-2 text-[12.5px] text-fg">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" />
              <span>
                <span className="font-semibold">Bu denetim için yeni bir yerleşik kontrol geliştirilmesi gerekir:</span> {session.builtin_note || '—'}{' '}
                <span className="text-fg-muted">Şimdilik LLM kuralı olarak önerildi.</span>
              </span>
            </p>
          </div>
        )}
      </Card>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
        <Card className="min-w-0">
          <CardHeader
            icon={<Sparkles className="size-4 text-accent" />}
            title="Önerilen kural"
            description={
              extend
                ? `Değişen alanlar işaretlenir; önceki değerler her bölümün altında gösterilir.${changes ? ` ${Object.keys(changes).length} alan değişti.` : ''}`
                : 'LLM’in doldurduğu alanlar; kaydetmeden önce düzenleyebilirsiniz.'
            }
            actions={dirty && !saved ? <span className="text-[11.5px] font-medium text-warn">Düzenlendi · doğrulanmadı</span> : undefined}
          />
          <fieldset disabled={saved} className="flex min-w-0 flex-col gap-5 p-5">
            <RuleFormFields form={form} set={set} touched={touched} lockedBuiltin={initial.kind === 'builtin'} changes={changes} />
          </fieldset>
        </Card>
        <div className="flex min-w-0 flex-col gap-4">
          <ValidationCard session={session} stale={dirty} />
          <NoiseCard session={session} stale={dirty} />
        </div>
      </div>

      {!saved && (
        <div className="glass sticky bottom-0 z-20 -mx-4 -mb-6 border-t border-line lg:-mx-8 lg:-mb-7">
          <div className="flex flex-wrap items-center gap-3 px-4 py-3 lg:px-8">
            <Button variant="ghost" icon={<X className="size-4" />} onClick={onDiscard}>
              Vazgeç
            </Button>
            <div className="ml-auto flex flex-wrap items-center gap-3">
              <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-fg-muted">
                <Checkbox checked={runNoise} onChange={setRunNoise} label="Gürültü testi dahil" disabled={!session.request?.noise} />
                Gürültü testi dahil
              </label>
              <Button
                icon={<RefreshCw className="size-3.5" />}
                loading={revalidating}
                disabled={!dirty || invalid}
                onClick={() => {
                  setTouched(true);
                  if (!invalid) onRevalidate(toRulePayload(form), runNoise && !!session.request?.noise);
                }}
              >
                Yeniden doğrula
              </Button>
              <Button variant="primary" icon={<Save className="size-4" />} loading={saving} onClick={save}>
                Onayla ve kaydet
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
