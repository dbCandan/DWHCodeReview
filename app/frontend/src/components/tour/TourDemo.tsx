import {useEffect, useMemo, useRef, useState} from 'react';
import {ArrowLeft, ArrowRight, CircleCheck, FlaskConical, Info, Play, RotateCcw, ScanSearch} from 'lucide-react';
import {api} from '@/lib/api';
import {useRules} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {buildLineMarks} from '@/lib/findings';
import {SEVERITIES, SEVERITY_LABEL, SEVERITY_RANK, countBySeverity} from '@/lib/severity';
import {DEMO_FALLBACK, DEMO_OBJECT, DEMO_SQL, type DemoFinding} from '@/lib/tour';
import type {Rule, RuleInput} from '@/types';
import {Button} from '@/components/ui/Button';
import {SeverityBadge, SeverityDot} from '@/components/ui/Badge';
import {ProgressBar} from '@/components/ui/Progress';
import {SqlViewer} from '@/components/analysis/SqlViewer';

type Phase = 'idle' | 'running' | 'done';

/** Milliseconds each rule stays on screen while the demo "runs" (the real calls finish first). */
const RULE_PACE = 110;

function toTestRule(r: Rule): RuleInput {
  const input: Partial<Rule> = {...r};
  delete input.id;
  delete input.created_at;
  delete input.updated_at;
  delete input.exception_count;
  return input as RuleInput;
}

/** Runs every non-LLM rule of the real rule set over the sample procedure via the live tester. */
async function runDemo(rules: Rule[]): Promise<DemoFinding[]> {
  const results = await Promise.all(
    rules.map(async (r) => {
      try {
        const res = await api.rules.test({
          rule: toTestRule(r),
          sql: DEMO_SQL,
          object_name: DEMO_OBJECT.name,
          object_type: DEMO_OBJECT.type,
          database: DEMO_OBJECT.database,
        });
        return res.findings.map((f) => ({code: r.code, name: r.name, severity: r.severity, line: f.line, snippet: f.snippet, message: f.message}));
      } catch {
        return [];
      }
    }),
  );
  return results.flat();
}

const byLine = (a: DemoFinding, b: DemoFinding) =>
  (a.line ?? 1e9) - (b.line ?? 1e9) || SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity];

export function TourDemo({onBack, onNext}: {onBack: () => void; onNext: () => void}) {
  const rules = useRules();
  const demoRules = useMemo(
    () => (rules.data ?? []).filter((r) => r.enabled && r.kind !== 'llm' && !/_COPY$/i.test(r.code)),
    [rules.data],
  );
  const llmCount = (rules.data ?? []).filter((r) => r.enabled && r.kind === 'llm').length;
  const [phase, setPhase] = useState<Phase>('idle');
  const [cursor, setCursor] = useState(0);
  const [all, setAll] = useState<DemoFinding[] | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const [offline, setOffline] = useState(false);
  const runId = useRef(0);

  const order = demoRules;
  const total = Math.max(order.length, 1);

  const start = async () => {
    const id = ++runId.current;
    setPhase('running');
    setCursor(0);
    setFocus(null);
    setAll(null);
    let found: DemoFinding[] = [];
    if (order.length) found = await runDemo(order);
    if (id !== runId.current) return;
    const useFallback = !order.length || found.length === 0;
    setOffline(useFallback);
    setAll((useFallback ? DEMO_FALLBACK : found).slice().sort(byLine));
  };

  // Walk the rule list on screen; findings show up as their rule is "checked".
  useEffect(() => {
    if (phase !== 'running' || all === null) return;
    if (cursor >= total) {
      setPhase('done');
      return;
    }
    const t = window.setTimeout(() => setCursor((c) => c + 1), RULE_PACE);
    return () => window.clearTimeout(t);
  }, [phase, all, cursor, total]);

  const checkedCodes = useMemo(() => new Set(order.slice(0, cursor).map((r) => r.code)), [order, cursor]);
  const visible = useMemo(() => {
    if (!all) return [];
    if (phase === 'done') return all;
    if (offline) return all.slice(0, Math.floor((cursor / total) * all.length));
    return all.filter((f) => checkedCodes.has(f.code));
  }, [all, phase, offline, cursor, total, checkedCodes]);

  const marks = useMemo(
    () => buildLineMarks(visible.map((f) => ({line: f.line, severity: f.severity, code: f.code, title: f.name, message: f.message}))),
    [visible],
  );
  const counts = countBySeverity(visible);
  const current = phase === 'running' && cursor < order.length ? order[cursor] : null;

  const hint =
    phase === 'idle'
      ? 'Örnek bir yükleme prosedürü hazır. Kuralları çalıştırın ve neleri yakaladığını izleyin.'
      : phase === 'running'
        ? 'Kurallar sırayla çalışıyor; bulunan ihlaller koda işleniyor…'
        : 'Bir bulguya tıklayın: kodda ilgili satır vurgulanır.';

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-start gap-3 border-b border-line px-5 py-4">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <FlaskConical className="size-[18px]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-fg">Demo: bir prosedürü denetleyin</h2>
            <span className="rounded-md bg-surface-3 px-1.5 py-0.5 text-[11px] font-medium text-fg-muted">Bağlantı gerekmez</span>
          </div>
          <p className="mt-1 flex items-center gap-1.5 text-[12.5px] text-fg-muted" aria-live="polite">
            <Info className="size-3.5 shrink-0 text-accent" />
            {hint}
          </p>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        {/* code */}
        <div className="flex min-h-0 flex-col border-b border-line lg:border-r lg:border-b-0">
          <div className="flex items-center gap-2 px-4 py-2.5 text-[12px] text-fg-muted">
            <span className="font-mono text-fg">{DEMO_OBJECT.database}.{DEMO_OBJECT.name}</span>
            <span className="rounded bg-surface-3 px-1.5 py-px text-[10.5px] font-semibold tracking-wide text-fg-muted">PROSEDÜR</span>
            <span className="ml-auto tnum">{DEMO_SQL.split('\n').length} satır</span>
          </div>
          <SqlViewer source={DEMO_SQL} marks={marks} focusLine={focus} showNotes={phase === 'done'} className="min-h-0 flex-1 border-t border-line" maxHeight="min(52vh, 460px)" />
        </div>

        {/* rules / findings */}
        <div className="flex min-h-0 flex-col">
          {phase === 'idle' ? (
            <div className="flex flex-1 flex-col justify-center gap-4 p-5">
              <div>
                <div className="text-[13px] font-semibold text-fg">Bu kodda kaç standart ihlali var?</div>
                <p className="mt-1 text-[12.5px] leading-5 text-fg-muted">
                  Kural setindeki <b className="text-fg">{order.length || 'tüm'}</b> regex ve yerleşik kural bu prosedürün üzerinden geçecek. Sonuçlar gerçek kural motorundan gelir.
                </p>
              </div>
              <ul className="grid gap-1.5 text-[12.5px] text-fg-muted">
                {['Temp tablo okumasında NOLOCK', 'Kayıt filtresinde EdwStatus', 'LEFT JOIN sonrası INNER JOIN', 'Filtre kolonunda fonksiyon'].map((t) => (
                  <li key={t} className="flex items-center gap-2">
                    <ScanSearch className="size-3.5 text-fg-subtle" />
                    {t}
                    <span className="text-fg-subtle">…</span>
                  </li>
                ))}
              </ul>
              <Button variant="primary" size="lg" className="self-start" icon={<Play className="size-4 fill-current" />} onClick={start} disabled={rules.isPending} data-autofocus>
                Kuralları çalıştır
              </Button>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="flex flex-col gap-2 border-b border-line px-4 py-3">
                <div className="flex items-center gap-2 text-[12px]">
                  {phase === 'done' ? (
                    <span className="flex items-center gap-1.5 font-semibold text-ok">
                      <CircleCheck className="size-4" /> Analiz tamamlandı
                    </span>
                  ) : (
                    <span className="min-w-0 truncate text-fg-muted">
                      {current ? (
                        <>
                          <span className="font-mono text-fg">{current.code}</span> kontrol ediliyor…
                        </>
                      ) : (
                        'Kurallar hazırlanıyor…'
                      )}
                    </span>
                  )}
                  <span className="ml-auto text-fg-subtle tnum">
                    {Math.min(cursor, order.length)}/{order.length} kural
                  </span>
                </div>
                <ProgressBar value={phase === 'done' ? 1 : cursor} max={phase === 'done' ? 1 : total} active={phase === 'running'} size="sm" />
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
                  <span className="font-semibold text-fg tnum">{visible.length} bulgu</span>
                  {SEVERITIES.filter((s) => counts[s] > 0).map((s) => (
                    <span key={s} className="flex items-center gap-1.5 text-fg-muted">
                      <SeverityDot severity={s} className="size-1.5" />
                      {counts[s]} {SEVERITY_LABEL[s].toLocaleLowerCase('tr')}
                    </span>
                  ))}
                </div>
              </div>
              <ol className="min-h-0 flex-1 overflow-y-auto p-2" style={{maxHeight: 'min(40vh, 360px)'}}>
                {visible.map((f, i) => (
                  <li key={`${f.code}-${f.line}-${i}`} className="animate-fade-in">
                    <button
                      type="button"
                      onClick={() => setFocus(f.line)}
                      className={cn(
                        'flex w-full flex-col gap-1 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-surface-2',
                        focus !== null && focus === f.line && 'bg-accent-soft hover:bg-accent-soft',
                      )}
                    >
                      <span className="flex items-center gap-2">
                        <SeverityBadge severity={f.severity} />
                        <span className="font-mono text-[12px] font-medium text-fg">{f.code}</span>
                        {f.line && <span className="ml-auto text-[11.5px] text-fg-subtle tnum">satır {f.line}</span>}
                      </span>
                      <span className="text-[12.5px] leading-[18px] text-fg-muted">{f.message}</span>
                    </button>
                  </li>
                ))}
                {phase === 'running' && visible.length === 0 && <li className="px-3 py-6 text-center text-[12px] text-fg-subtle">Henüz bulgu yok…</li>}
              </ol>
              {phase === 'done' && (
                <div className="border-t border-line bg-surface-2/50 px-4 py-3 text-[12px] leading-[18px] text-fg-muted">
                  {offline
                    ? 'Kural sunucusuna ulaşılamadığı için örnek sonuçlar gösterildi. '
                    : 'Bu sonuçlar gerçek kural motorundan geldi. '}
                  Gerçek bir analizde katalog metadatası ile NOLOCK eksikliği, tip uyumsuzluğu gibi kontroller de devreye girer
                  {llmCount > 0 && <>; {llmCount} LLM kuralı da anlamsal inceleme yapar</>}.
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-line bg-surface-2/40 px-5 py-3">
        <Button variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={onBack}>
          Geri
        </Button>
        {phase === 'done' && (
          <Button variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={start}>
            Tekrar çalıştır
          </Button>
        )}
        <Button variant={phase === 'done' ? 'primary' : 'secondary'} className="ml-auto" onClick={onNext} data-autofocus={phase === 'done' ? true : undefined}>
          {phase === 'done' ? 'Şimdi uygulamayı gezelim' : 'Demoyu geç, uygulamayı gez'}
          <ArrowRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}
