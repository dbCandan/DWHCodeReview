import {createContext, useContext, useId, useMemo, useState} from 'react';
import {SqlCodeView} from '@/components/review/SqlCodeView';
import {Alert} from '@/components/ui/Alert';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {lineMarks, referencedLines} from '@/lib/codeLines';
import {describeError, messageForCode} from '@/lib/errorMessages';
import {
  NO_FILTER,
  findingsForRule,
  isCompliant,
  objectTitle,
  orphanFindings,
  resultGroupNames,
  ruleIsMarkable,
  ruleMatches,
  severityLabel,
  severityTone,
  statusLabel,
  statusTone,
  summarize,
  tierLabel,
  UNGROUPED,
  type FalsePositiveTarget,
  type ResultFilter,
} from '@/lib/reviewResults';
import {ReviewService} from '@/services/reviews';
import type {Finding, ObjectResult, RuleResult} from '@/types/sqlReview';

/** Set inside an object that shows its SQL: a line reference then jumps to the line. */
const JumpContext = createContext<((line: number) => void) | null>(null);

interface MarkControl {
  enabled: boolean;
  pending: string | null;
  onChange: (target: FalsePositiveTarget, value: boolean) => void;
}

/**
 * Results of a run: every object, every rule result with status, severity, line reference and
 * code snippet, and the findings of failed rules. The run owner marks a finding, or a failed rule
 * result without findings, as a false positive; the mark is saved on the server
 * (review-history-export Requirement 4). Used by the live results window and the history page.
 */
export function ReviewResultsView({
  results,
  runId,
  canMark,
  onMarked,
}: {
  results: ObjectResult[];
  runId: string | null;
  canMark: boolean;
  onMarked: (target: FalsePositiveTarget, value: boolean) => void;
}) {
  const filterId = useId();
  const [filter, setFilter] = useState<ResultFilter>(NO_FILTER);
  const [pending, setPending] = useState<string | null>(null);
  const [markError, setMarkError] = useState<string | null>(null);
  const filtered = filter.text !== '' || filter.status !== 'ALL' || filter.severity !== 'ALL' || filter.group !== 'ALL';
  const groupNames = useMemo(() => resultGroupNames(results), [results]);

  async function mark(target: FalsePositiveTarget, value: boolean) {
    if (runId === null) return;
    setPending(target.id);
    setMarkError(null);
    try {
      const saved =
        target.kind === 'finding'
          ? await ReviewService.markFinding(runId, target.id, value)
          : await ReviewService.markRuleResult(runId, target.id, value);
      onMarked(target, saved.false_positive);
    } catch (error) {
      setMarkError(describeError(error));
    } finally {
      setPending(null);
    }
  }

  const control: MarkControl = {enabled: canMark && runId !== null, pending, onChange: (t, v) => void mark(t, v)};

  if (results.length === 0) return <p className="muted">Bu incelemenin gösterilecek sonucu yok.</p>;

  return (
    <div className="stack">
      <fieldset className="card card-body">
        <legend className="sr-only">Sonuçları süz</legend>
        <div className="row">
          <div className="field grow">
            <label className="field-label" htmlFor={`${filterId}-text`}>
              Metin ara
            </label>
            <input
              id={`${filterId}-text`}
              className="input"
              type="search"
              value={filter.text}
              placeholder="Kural kimliği, açıklama, kod…"
              onChange={(event) => setFilter({...filter, text: event.target.value})}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor={`${filterId}-status`}>
              Kural durumu
            </label>
            <select
              id={`${filterId}-status`}
              className="select"
              value={filter.status}
              onChange={(event) => setFilter({...filter, status: event.target.value as ResultFilter['status']})}
            >
              <option value="ALL">Tüm durumlar</option>
              <option value="PASS">Uyumlu</option>
              <option value="FAIL">İhlal var</option>
              <option value="NOT_APPLICABLE">Kapsam dışı</option>
              <option value="UNKNOWN">Değerlendirilemedi</option>
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor={`${filterId}-severity`}>
              Önem (ihlallerde)
            </label>
            <select
              id={`${filterId}-severity`}
              className="select"
              value={filter.severity}
              onChange={(event) =>
                setFilter({...filter, severity: event.target.value as ResultFilter['severity']})
              }
            >
              <option value="ALL">Tüm önemler</option>
              <option value="HIGH">Yüksek</option>
              <option value="MEDIUM">Orta</option>
              <option value="LOW">Düşük</option>
            </select>
          </div>
          {groupNames.length > 0 && (
            <div className="field">
              <label className="field-label" htmlFor={`${filterId}-group`}>
                Kural grubu
              </label>
              <select
                id={`${filterId}-group`}
                className="select"
                value={filter.group}
                onChange={(event) => setFilter({...filter, group: event.target.value})}
              >
                <option value="ALL">Tüm gruplar</option>
                {groupNames.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
                <option value={UNGROUPED}>Grupsuz kurallar</option>
              </select>
            </div>
          )}
          {filtered && (
            <Button size="sm" variant="ghost" onClick={() => setFilter(NO_FILTER)}>
              Süzgeci sıfırla
            </Button>
          )}
        </div>
      </fieldset>
      {markError && <Alert tone="error">{markError}</Alert>}
      {results.map((result, index) => (
        <ObjectResultCard
          key={`${result.database}|${result.schema}|${result.name}|${index}`}
          result={result}
          filter={filter}
          control={control}
        />
      ))}
    </div>
  );
}

function ObjectResultCard({
  result,
  filter,
  control,
}: {
  result: ObjectResult;
  filter: ResultFilter;
  control: MarkControl;
}) {
  const [open, setOpen] = useState(true);
  const bodyId = useId();
  const summary = useMemo(() => summarize(result), [result]);
  const rules = result.rule_results.filter((rule) =>
    ruleMatches(rule, findingsForRule(result, rule.rule_id), filter),
  );
  const orphans = orphanFindings(result);
  const sql = result.source_sql ?? null;
  const marks = useMemo(() => lineMarks(result.findings, result.rule_results), [result]);
  const [focus, setFocus] = useState<{line: number; seq: number} | null>(null);
  const jump = (line: number) => setFocus((current) => ({line, seq: (current?.seq ?? 0) + 1}));
  const score = summary.total > 0 ? Math.round((summary.compliant / summary.total) * 100) : null;
  const summaryText = result.error_code
    ? 'Hata'
    : `${summary.compliant} uyumlu · ${summary.failed} ihlal${summary.unknown ? ` · ${summary.unknown} değerlendirilemedi` : ''}`;

  return (
    <section className="disclosure" aria-label={objectTitle(result)}>
      <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)}>
        <span className="stack-tight">
          <strong className="mono">{objectTitle(result)}</strong>
          <span className="subtle">{result.object_type}</span>
        </span>
        <span className="row">
          <span className="subtle">{summaryText}</span>
          {score !== null && !result.error_code && <ScoreRing value={score} />}
          <span aria-hidden="true">{open ? '▾' : '▸'}</span>
        </span>
      </button>
      {open && (
        <JumpContext.Provider value={sql ? jump : null}>
        <div id={bodyId} className={sql ? 'disclosure-body result-split' : 'disclosure-body'}>
          <div className="result-rules">
          {result.error_code && (
            <Alert tone="error">{messageForCode(result.error_code) ?? result.error_message ?? 'Nesne incelenemedi.'}</Alert>
          )}
          {result.parse_warning && <Alert tone="warning">{result.parse_warning}</Alert>}
          {result.rule_results.length > 0 && (
            <p className="subtle">Yayımlanmış sürümdeki kurallar ({summary.total}).</p>
          )}
          {result.rule_results.length > 0 && rules.length === 0 && (
            <p className="muted">Bu süzgeçle eşleşen kural sonucu yok.</p>
          )}
          {rules.length > 0 && (
            <ul className="list stack">
              {rules.map((rule) => (
                <RuleResultLine
                  key={rule.id}
                  rule={rule}
                  findings={findingsForRule(result, rule.rule_id)}
                  control={control}
                />
              ))}
            </ul>
          )}
          {orphans.length > 0 && (
            <div className="stack">
              {orphans.map((finding, index) => (
                <FindingBlock key={finding.id} finding={finding} index={index} control={control} />
              ))}
            </div>
          )}
          </div>
          {sql && <SqlCodeView sql={sql} marks={marks} focus={focus} label="İncelenen SQL" />}
        </div>
        </JumpContext.Provider>
      )}
    </section>
  );
}

function RuleResultLine({rule, findings, control}: {rule: RuleResult; findings: Finding[]; control: MarkControl}) {
  const tone = isCompliant(rule.status) ? 'is-pass' : rule.status === 'FAIL' ? 'is-fail' : 'is-unknown';
  const markable = ruleIsMarkable(rule, findings);
  return (
    <li className={`rule-line ${tone}${rule.false_positive ? ' is-muted' : ''}`}>
      <div className="row">
        <Badge tone={statusTone(rule.status)}>{statusLabel(rule.status)}</Badge>
        <Badge tone={rule.tier === 'critical' ? 'danger' : 'info'}>{tierLabel(rule.tier)}</Badge>
        {rule.status === 'FAIL' && rule.severity && (
          <Badge tone={severityTone(rule.severity)}>Önem: {severityLabel(rule.severity)}</Badge>
        )}
        <span className="mono">{rule.rule_id}</span>
        {/* rule-group-selection Requirement 6: every group of the rule in the pinned version. */}
        {(rule.rule_group_names ?? []).map((name) => (
          <Badge key={name} tone="neutral">
            {name}
          </Badge>
        ))}
        {rule.decision_basis && <span className="subtle mono wrap-anywhere">{rule.decision_basis}</span>}
        {findings.length > 0 && <span className="subtle">{findings.length} bulgu</span>}
        {markable && (
          <FalsePositiveToggle
            checked={rule.false_positive}
            label={`${rule.rule_id} kural sonucu yanlış pozitif`}
            target={{kind: 'rule', id: rule.id}}
            control={control}
          />
        )}
      </div>
      {findings.length === 0 && rule.description && <p className="rule-text">{rule.description}</p>}
      {findings.length === 0 && rule.line_reference && <LineReference value={rule.line_reference} />}
      {findings.length === 0 && rule.code_snippet && <pre className="code-block">{rule.code_snippet}</pre>}
      {findings.map((finding, index) => (
        <FindingBlock key={finding.id} finding={finding} index={index} control={control} />
      ))}
    </li>
  );
}

function FindingBlock({finding, index, control}: {finding: Finding; index: number; control: MarkControl}) {
  return (
    <div className={`finding${finding.false_positive ? ' rule-line is-muted' : ''}`}>
      <div className="row">
        <strong>Bulgu {index + 1}</strong>
        <Badge tone={severityTone(finding.severity)}>Önem: {severityLabel(finding.severity)}</Badge>
        <span className="mono subtle">{finding.rule_id}</span>
        <FalsePositiveToggle
          checked={finding.false_positive}
          label={`${finding.rule_id} bulgu ${index + 1} yanlış pozitif`}
          target={{kind: 'finding', id: finding.id}}
          control={control}
        />
      </div>
      {finding.description && <p className="rule-text">{finding.description}</p>}
      {finding.line_reference && <LineReference value={finding.line_reference} />}
      {finding.code_snippet && <pre className="code-block">{finding.code_snippet}</pre>}
    </div>
  );
}

function LineReference({value}: {value: string}) {
  const jump = useContext(JumpContext);
  const first = referencedLines(value)[0];
  return (
    <p className="rule-text">
      <span className="subtle">Konum: </span>
      {jump && first !== undefined ? (
        <button type="button" className="line-ref line-jump" onClick={() => jump(first)} title="Koddaki satıra git">
          {value}
        </button>
      ) : (
        <span className="line-ref">{value}</span>
      )}
    </p>
  );
}

/** The share of compliant rules of an object as a small ring. */
function ScoreRing({value}: {value: number}) {
  const tone = value >= 90 ? 'is-good' : value >= 60 ? 'is-fair' : 'is-poor';
  return (
    <span className={`score-ring ${tone}`} role="img" aria-label={`Uyum %${value}`}>
      <svg viewBox="0 0 36 36" aria-hidden="true">
        <circle className="score-track" cx="18" cy="18" r="15.5" />
        <circle className="score-value" cx="18" cy="18" r="15.5" strokeDasharray={`${value * 0.974} 100`} />
      </svg>
      <span className="score-text tabular">{value}</span>
    </span>
  );
}

function FalsePositiveToggle({
  checked,
  label,
  target,
  control,
}: {
  checked: boolean;
  label: string;
  target: FalsePositiveTarget;
  control: MarkControl;
}) {
  if (!control.enabled) return checked ? <Badge tone="neutral">Yanlış pozitif</Badge> : null;
  return (
    <label className="check push-end">
      <input
        type="checkbox"
        checked={checked}
        aria-label={label}
        disabled={control.pending !== null}
        onChange={(event) => control.onChange(target, event.target.checked)}
      />
      <span aria-hidden="true">Yanlış pozitif</span>
    </label>
  );
}
