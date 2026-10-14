import {formatDateTime} from '@/lib/format';
import type {RuleGroupItem, RuleItem, RuleSetVersionSummary} from '@/types/sqlReview';

export type Tier = 'critical' | 'normal';
export const RULE_TEXT_LIMIT = 8000;
/** rule-management Requirement 2: a one-sentence summary on one line. */
export const RULE_SUMMARY_LIMIT = 200;
export const PREVIEW_CHARS = 100;
/** rule-group-selection Requirement 1: group names and the number of groups. */
export const RULE_GROUP_NAME_LIMIT = 80;
export const RULE_GROUPS_LIMIT = 50;

export interface RuleDraft {
  critical: RuleItem[];
  normal: RuleItem[];
  /** Named rule groups; a rule may belong to several (rule-group-selection Decision 1). */
  groups: RuleGroupItem[];
}

export function ruleNumber(id: string): number | null {
  const match = /^Kural(\d+)$/.exec(id.trim());
  return match ? Number(match[1]) : null;
}

/** `Kural01` … `Kural99`, then `Kural100` …, as the backend formats identifiers. */
export function formatRuleId(value: number): string {
  return value < 100 ? `Kural${String(value).padStart(2, '0')}` : `Kural${value}`;
}

export function previewText(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return '—';
  return trimmed.length <= PREVIEW_CHARS ? trimmed : `${trimmed.slice(0, PREVIEW_CHARS).trim()}…`;
}

export function ruleMatchesSearch(rule: Pick<RuleItem, 'id' | 'text' | 'summary'>, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase('tr-TR');
  if (!needle) return true;
  return [rule.id, rule.text, rule.summary ?? ''].some((value) => value.toLocaleLowerCase('tr-TR').includes(needle));
}

/**
 * The one sentence everyone but the super admin sees (rule-management Requirement 12, Decision 5):
 * the given summary, otherwise the first sentence of the text — of its "AÇIKLAMA:" section when it
 * has one — up to the first `.`, `!` or `?` followed by a space or the end, or else its first line,
 * at most 200 characters.
 */
export function displaySummary(rule: Pick<RuleItem, 'text' | 'summary'>): string {
  const summary = (rule.summary ?? '').trim();
  if (summary) return summary;
  // The imported rules read "KURAL ADI: … AÇIKLAMA: …"; the explanation is the meaningful part.
  const full = rule.text.trim();
  const explanation = /(?:^|\n)\s*(?:AÇIKLAMA|Açıklama)\s*:\s*/.exec(full);
  const text = explanation ? full.slice(explanation.index + explanation[0].length).trim() : full;
  const sentence = /^[\s\S]*?[.!?](?=\s|$)/.exec(text)?.[0] ?? text;
  const line = sentence.split(/\r?\n/)[0].trim();
  return line.length <= RULE_SUMMARY_LIMIT ? line : `${line.slice(0, RULE_SUMMARY_LIMIT - 1).trimEnd()}…`;
}

/** The problem of a summary the server would reject, or null; an empty one is "not given". */
export function summaryProblem(summary: string): string | null {
  const trimmed = summary.trim();
  if (/[\r\n]/.test(trimmed)) return 'Kural özeti tek satır olmalıdır.';
  if (trimmed.length > RULE_SUMMARY_LIMIT) return `Kural özeti en çok ${RULE_SUMMARY_LIMIT} karakter olabilir.`;
  return null;
}

export function moveRule(list: RuleItem[], index: number, delta: -1 | 1): RuleItem[] {
  const target = index + delta;
  if (target < 0 || target >= list.length) return list;
  const next = [...list];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** The rule's group identifiers in the order of ``groups``, as the server stores them. */
export function orderedGroupIds(ids: readonly string[] | undefined, groups: RuleGroupItem[]): string[] {
  const wanted = new Set(ids ?? []);
  return groups.filter((group) => wanted.has(group.id)).map((group) => group.id);
}

export function normalizedDraft(draft: RuleDraft): RuleDraft {
  const clean = (rule: RuleItem): RuleItem => ({
    id: rule.id,
    text: rule.text,
    summary: rule.summary ?? '',
    requires_metadata: Boolean(rule.requires_metadata),
    rule_group_ids: orderedGroupIds(rule.rule_group_ids, draft.groups),
  });
  return {
    critical: draft.critical.map(clean),
    normal: draft.normal.map(clean),
    groups: draft.groups.map((group) => ({id: group.id, name: group.name, description: group.description ?? ''})),
  };
}

export function draftsEqual(left: RuleDraft, right: RuleDraft): boolean {
  return JSON.stringify(normalizedDraft(left)) === JSON.stringify(normalizedDraft(right));
}

export function publisherName(version: Pick<RuleSetVersionSummary, 'published_by_name' | 'source'>): string {
  if (version.source === 'ice-aktarim') return 'içe aktarım';
  return version.published_by_name ?? 'bilinmiyor';
}

/** "Son yayın: sürüm N · tarih · yayımlayan" (rule-management Requirement 10). */
export function latestVersionLine(version: RuleSetVersionSummary | null): string {
  if (version === null) return 'Henüz yayımlanmış sürüm yok';
  return `Son yayın: sürüm ${version.number} · ${formatDateTime(version.published_at)} · ${publisherName(version)}`;
}

/** A client-generated identifier lets one save create a group and assign rules to it. */
export function newGroupId(): string {
  return crypto.randomUUID();
}

/** Turkish-aware folding for group name uniqueness, as the server checks it (I/ı, İ/i). */
export function foldGroupName(name: string): string {
  return name.trim().toLocaleLowerCase('tr-TR');
}

/** The first problem of the group definitions that the server would reject, or null. */
export function groupProblem(groups: RuleGroupItem[]): string | null {
  if (groups.length > RULE_GROUPS_LIMIT) return `En çok ${RULE_GROUPS_LIMIT} kural grubu tanımlanabilir.`;
  const seen = new Set<string>();
  for (const group of groups) {
    const name = group.name.trim();
    if (!name) return 'Kural grubu adı boş olamaz.';
    if (name.length > RULE_GROUP_NAME_LIMIT) return `Kural grubu adı en çok ${RULE_GROUP_NAME_LIMIT} karakter olabilir.`;
    const folded = foldGroupName(name);
    if (seen.has(folded)) return 'Aynı adla iki kural grubu tanımlanamaz.';
    seen.add(folded);
  }
  return null;
}

/** How many rules of the given lists belong to each group; a rule counts in each of its groups. */
export function groupRuleCounts(...lists: RuleItem[][]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const rule of lists.flat()) {
    for (const id of rule.rule_group_ids ?? []) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return counts;
}

/** The rules with any assignment to ``groupId`` removed; used when a group is deleted. */
export function withoutGroup(rules: RuleItem[], groupId: string): RuleItem[] {
  return rules.map((rule) =>
    rule.rule_group_ids?.includes(groupId)
      ? {...rule, rule_group_ids: rule.rule_group_ids.filter((id) => id !== groupId)}
      : rule,
  );
}

/** The rule with ``groupId`` added or removed; other memberships stay (Decision 1). */
export function withGroupMembership(rule: RuleItem, groupId: string, member: boolean): RuleItem {
  const others = (rule.rule_group_ids ?? []).filter((id) => id !== groupId);
  return {...rule, rule_group_ids: member ? [...others, groupId] : others};
}

/** Names of the rule's groups in group order; unknown identifiers are skipped. */
export function groupNamesOf(rule: RuleItem, groups: RuleGroupItem[]): string[] {
  const wanted = new Set(rule.rule_group_ids ?? []);
  return groups.filter((group) => wanted.has(group.id)).map((group) => group.name.trim() || 'Adsız grup');
}
