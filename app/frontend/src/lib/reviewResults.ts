import type {Tone as BadgeTone} from '@/lib/utils';
import type {Finding, ObjectResult, RuleResult} from '@/types/sqlReview';

export type RuleStatus = RuleResult['status'];
export type Severity = NonNullable<RuleResult['severity']>;

export interface FalsePositiveTarget {
  kind: 'finding' | 'rule';
  id: string;
}

const STATUS_LABELS: Record<RuleStatus, string> = {
  PASS: 'Uyumlu',
  FAIL: 'İhlal var',
  NOT_APPLICABLE: 'Kapsam dışı',
  UNKNOWN: 'Değerlendirilemedi',
};

const SEVERITY_LABELS: Record<Severity, string> = {HIGH: 'Yüksek', MEDIUM: 'Orta', LOW: 'Düşük'};

export function statusLabel(status: RuleStatus): string {
  return STATUS_LABELS[status];
}

export function severityLabel(severity: Severity): string {
  return SEVERITY_LABELS[severity];
}

export function tierLabel(tier: RuleResult['tier']): string {
  return tier === 'critical' ? 'Kritik' : 'Normal';
}

/** NOT_APPLICABLE is shown with the compliant group, as in the source application. */
export function isCompliant(status: RuleStatus): boolean {
  return status === 'PASS' || status === 'NOT_APPLICABLE';
}

export function statusTone(status: RuleStatus): BadgeTone {
  if (isCompliant(status)) return 'success';
  return status === 'FAIL' ? 'danger' : 'warning';
}

export function severityTone(severity: Severity): BadgeTone {
  if (severity === 'HIGH') return 'danger';
  return severity === 'MEDIUM' ? 'warning' : 'info';
}

export function objectTitle(result: Pick<ObjectResult, 'database' | 'schema' | 'name'>): string {
  const name = `${result.schema}.${result.name}`;
  return result.database ? `${result.database} · ${name}` : name;
}

export interface ResultSummary {
  compliant: number;
  failed: number;
  unknown: number;
  total: number;
}

export function summarize(result: Pick<ObjectResult, 'rule_results'>): ResultSummary {
  const summary: ResultSummary = {compliant: 0, failed: 0, unknown: 0, total: result.rule_results.length};
  for (const rule of result.rule_results) {
    if (isCompliant(rule.status)) summary.compliant += 1;
    else if (rule.status === 'FAIL') summary.failed += 1;
    else summary.unknown += 1;
  }
  return summary;
}

export function findingsForRule(result: Pick<ObjectResult, 'findings'>, ruleId: string): Finding[] {
  return result.findings.filter((finding) => finding.rule_id === ruleId);
}

/** Findings whose rule has no rule result (kept visible rather than dropped). */
export function orphanFindings(result: Pick<ObjectResult, 'findings' | 'rule_results'>): Finding[] {
  const ruleIds = new Set(result.rule_results.map((rule) => rule.rule_id));
  return result.findings.filter((finding) => !ruleIds.has(finding.rule_id));
}

/** The group filter value of rules without a named group (rule-group-selection Requirement 6). */
export const UNGROUPED = '__grupsuz__';

export interface ResultFilter {
  text: string;
  status: RuleStatus | 'ALL';
  severity: Severity | 'ALL';
  /** A group name, ``UNGROUPED`` or 'ALL'. */
  group: string;
}

export const NO_FILTER: ResultFilter = {text: '', status: 'ALL', severity: 'ALL', group: 'ALL'};

/** Group names of the results in first-appearance order; empty when no rule is grouped. */
export function resultGroupNames(results: ObjectResult[]): string[] {
  const names = new Set<string>();
  for (const result of results) for (const rule of result.rule_results) for (const name of rule.rule_group_names ?? []) names.add(name);
  return [...names];
}

export function ruleMatches(rule: RuleResult, findings: Finding[], filter: ResultFilter): boolean {
  const groups = rule.rule_group_names ?? [];
  if (filter.group === UNGROUPED && groups.length > 0) return false;
  if (filter.group !== 'ALL' && filter.group !== UNGROUPED && !groups.includes(filter.group)) return false;
  if (filter.status !== 'ALL' && rule.status !== filter.status) return false;
  if (filter.severity !== 'ALL' && (rule.status !== 'FAIL' || rule.severity !== filter.severity)) return false;
  const text = filter.text.trim().toLocaleLowerCase('tr-TR');
  if (!text) return true;
  const haystack = [
    rule.rule_id,
    rule.description,
    rule.decision_basis ?? '',
    rule.line_reference,
    rule.code_snippet,
    ...findings.flatMap((finding) => [finding.description, finding.line_reference, finding.code_snippet]),
  ]
    .join(' ')
    .toLocaleLowerCase('tr-TR');
  return haystack.includes(text);
}

/** A failed rule result is marked directly only when it has no findings (history Requirement 4). */
export function ruleIsMarkable(rule: RuleResult, findings: Finding[]): boolean {
  return rule.status === 'FAIL' && findings.length === 0;
}

export function applyFalsePositive<T extends ObjectResult>(
  results: T[],
  target: FalsePositiveTarget,
  value: boolean,
): T[] {
  return results.map((result) =>
    target.kind === 'finding'
      ? {
          ...result,
          findings: result.findings.map((finding) =>
            finding.id === target.id ? {...finding, false_positive: value} : finding,
          ),
        }
      : {
          ...result,
          rule_results: result.rule_results.map((rule) =>
            rule.id === target.id ? {...rule, false_positive: value} : rule,
          ),
        },
  );
}

/**
 * The server stores reviewed SQL only for completed runs and only for objects whose definition
 * was read, so a run without such an object has no SQL export (history Requirement 10).
 */
export function hasStoredSql(completed: boolean, results: Pick<ObjectResult, 'error_code'>[]): boolean {
  return completed && results.some((result) => result.error_code === null);
}
