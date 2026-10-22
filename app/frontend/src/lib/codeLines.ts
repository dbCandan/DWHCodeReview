import type {Finding, RuleResult} from '@/types/sqlReview';

type Severity = Finding['severity'];

/** Lines one reference may point at; a longer range is a whole-object remark, not a line. */
const MAX_RANGE = 400;
const RANK: Record<Severity, number> = {LOW: 1, MEDIUM: 2, HIGH: 3};

/**
 * The line numbers of a line reference as the backend writes it: "Satır 12", "Satır 12–15",
 * "Satır 3, 7, 9" or the model's "L012"/"L012–L015". Anything else points at no line.
 */
export function referencedLines(value: string | null | undefined): number[] {
  if (!value) return [];
  const lines = new Set<number>();
  for (const part of value.replace(/^\s*Satır\s*/i, '').split(',')) {
    const range = part.trim().match(/^L?0*(\d+)\s*[–-]\s*L?0*(\d+)$/i);
    const single = part.trim().match(/^L?0*(\d+)$/i);
    if (range) {
      const low = Number(range[1]);
      const high = Number(range[2]);
      if (high >= low && high - low <= MAX_RANGE) for (let line = low; line <= high; line += 1) lines.add(line);
    } else if (single) {
      lines.add(Number(single[1]));
    }
  }
  return [...lines].filter((line) => line > 0).sort((a, b) => a - b);
}

export interface LineMark {
  severity: Severity;
  /** Rule codes that point at the line. */
  rules: string[];
}

/**
 * What each line of the reviewed text is flagged for: the findings and the failed rule results
 * without findings, minus those marked as false positives. A line keeps its highest severity.
 */
export function lineMarks(findings: Finding[], rules: RuleResult[]): Map<number, LineMark> {
  const marks = new Map<number, LineMark>();
  const add = (reference: string, severity: Severity, rule: string) => {
    for (const line of referencedLines(reference)) {
      const mark = marks.get(line);
      if (mark === undefined) marks.set(line, {severity, rules: [rule]});
      else {
        if (RANK[severity] > RANK[mark.severity]) mark.severity = severity;
        if (!mark.rules.includes(rule)) mark.rules.push(rule);
      }
    }
  };
  for (const finding of findings) if (!finding.false_positive) add(finding.line_reference, finding.severity, finding.rule_id);
  const withFindings = new Set(findings.map((finding) => finding.rule_id));
  for (const rule of rules) {
    if (rule.status !== 'FAIL' || rule.false_positive || withFindings.has(rule.rule_id)) continue;
    add(rule.line_reference ?? '', rule.severity ?? 'MEDIUM', rule.rule_id);
  }
  return marks;
}
