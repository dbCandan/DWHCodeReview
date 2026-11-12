import type {Finding, Severity} from '@/types';
import {SEVERITY_RANK} from './severity';

export interface LineNote {
  severity: Severity;
  code?: string;
  title?: string;
  message: string;
}

export interface LineMark {
  /** Highest severity among the notes on the line. */
  severity: Severity;
  notes: LineNote[];
}

/** Groups notes by 1-based line number; each line keeps its highest severity. Notes without a line are skipped. */
export function buildLineMarks(notes: (LineNote & {line: number | null | undefined})[]): Map<number, LineMark> {
  const marks = new Map<number, LineMark>();
  for (const note of notes) {
    if (!note.line || note.line < 1) continue;
    const {line, ...rest} = note;
    const mark = marks.get(line);
    if (!mark) marks.set(line, {severity: note.severity, notes: [rest]});
    else {
      mark.notes.push(rest);
      if (SEVERITY_RANK[note.severity] > SEVERITY_RANK[mark.severity]) mark.severity = note.severity;
    }
  }
  return marks;
}

export function findingsToMarks(findings: Finding[]): Map<number, LineMark> {
  return buildLineMarks(
    findings.map((f) => ({line: f.line, severity: f.severity, code: f.rule_code, title: f.rule_name, message: f.message})),
  );
}

export type GroupBy = 'none' | 'rule' | 'object';

export interface FindingGroup {
  key: string;
  label: string;
  sublabel?: string;
  severity: Severity;
  items: Finding[];
}

/** Groups findings by rule or object, ordering groups by severity then size. */
export function groupFindings(findings: Finding[], by: Exclude<GroupBy, 'none'>): FindingGroup[] {
  const map = new Map<string, FindingGroup>();
  for (const f of findings) {
    const key = by === 'rule' ? f.rule_code : String(f.object_id);
    let group = map.get(key);
    if (!group) {
      group =
        by === 'rule'
          ? {key, label: f.rule_code, sublabel: f.rule_name, severity: f.severity, items: []}
          : {key, label: f.object_label, severity: f.severity, items: []};
      map.set(key, group);
    }
    group.items.push(f);
    if (SEVERITY_RANK[f.severity] > SEVERITY_RANK[group.severity]) group.severity = f.severity;
  }
  return [...map.values()].sort(
    (a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.items.length - a.items.length || a.label.localeCompare(b.label),
  );
}
