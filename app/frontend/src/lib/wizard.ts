import type {DbObject, ObjectQuery, ObjectType, Rule, RuleGroup} from '@/types';
import {formatDate, OBJECT_TYPE_LABEL} from './format';
import {estimateCheckSplit, type RuleScope} from './rules';

/** One "Listele → Havuza ekle" round, stored with the analysis for display. */
export interface PoolQueryLog {
  databases: string[];
  schemas: string[];
  types: ObjectType[];
  created_from: string | null;
  created_to: string | null;
  modified_from: string | null;
  modified_to: string | null;
  search: string | null;
  matched: number;
  added: number;
}

export interface FilterForm {
  schemas: string[];
  types: ObjectType[];
  created_from: string;
  created_to: string;
  modified_from: string;
  modified_to: string;
  search: string;
}

export const EMPTY_FILTER: FilterForm = {
  schemas: [],
  types: [],
  created_from: '',
  created_to: '',
  modified_from: '',
  modified_to: '',
  search: '',
};

export function buildObjectQuery(databases: string[], f: FilterForm): ObjectQuery {
  return {
    databases,
    schemas: f.schemas,
    types: f.types,
    created_from: f.created_from || null,
    created_to: f.created_to || null,
    modified_from: f.modified_from || null,
    modified_to: f.modified_to || null,
    search: f.search.trim() || null,
  };
}

function range(from: string | null | undefined, to: string | null | undefined): string | null {
  if (!from && !to) return null;
  if (from && to) return `${formatDate(from)} – ${formatDate(to)}`;
  if (from) return `${formatDate(from)} sonrası`;
  return `${formatDate(to!)} öncesi`;
}

/** Human-readable chips for one object query. */
export function describeQuery(q: Partial<ObjectQuery>): string[] {
  const parts: string[] = [];
  if (q.schemas?.length) parts.push(`Şema: ${q.schemas.join(', ')}`);
  if (q.types?.length) parts.push(`Tip: ${q.types.map((t) => OBJECT_TYPE_LABEL[t] ?? t).join(', ')}`);
  const created = range(q.created_from, q.created_to);
  if (created) parts.push(`Oluşturma: ${created}`);
  const modified = range(q.modified_from, q.modified_to);
  if (modified) parts.push(`Değişiklik: ${modified}`);
  if (q.search) parts.push(`Ad içerir: “${q.search}”`);
  if (!parts.length) parts.push('Filtresiz (tüm nesneler)');
  return parts;
}

/** Enabled rules selected directly or through any selected group. */
export function effectiveRules(rules: Rule[], groups: RuleGroup[], groupIds: number[], ruleIds: number[]): Rule[] {
  const ids = new Set(ruleIds);
  for (const g of groups) if (groupIds.includes(g.id)) for (const id of g.rule_ids) ids.add(id);
  return rules.filter((r) => r.enabled && ids.has(r.id));
}

/** Checks that will actually run: object_types AND databases AND name_pattern must match (empty = all). */
export function estimateChecks(objects: ObjLike[], rules: RuleScope[]): number {
  return estimateCheckSplit(
    objects,
    rules.map((r) => ({...r, kind: 'regex' as const})),
  ).total;
}

type ObjLike = Pick<DbObject, 'type'> & Partial<Pick<DbObject, 'database' | 'schema' | 'name'>>;
