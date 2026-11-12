import type {
  ObjectQueryFilter,
  Rule,
  RuleGroup,
  RuleSelection,
  ScheduledAnalysisInput,
  ScheduledRun,
  ScheduleSpec,
} from '@/types';
import type {FilterForm, PoolQueryLog} from './wizard';

export const WEEKDAYS: {value: number; short: string; long: string}[] = [
  {value: 1, short: 'Pzt', long: 'Pazartesi'},
  {value: 2, short: 'Sal', long: 'Salı'},
  {value: 3, short: 'Çar', long: 'Çarşamba'},
  {value: 4, short: 'Per', long: 'Perşembe'},
  {value: 5, short: 'Cum', long: 'Cuma'},
  {value: 6, short: 'Cmt', long: 'Cumartesi'},
  {value: 7, short: 'Paz', long: 'Pazar'},
];

export const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;

// ---------------------------------------------------------------------------------------------
// Defaults + schedule text
// ---------------------------------------------------------------------------------------------

export function emptySchedule(): ScheduledAnalysisInput {
  return {
    name: '',
    description: '',
    enabled: true,
    connection_id: 0,
    scope: {databases: [], queries: []},
    rule_selection: {mode: 'all_enabled', group_ids: [], rule_ids: []},
    schedule: {kind: 'daily', time: '02:00', weekdays: [1, 2, 3, 4, 5], month_day: 1, interval_hours: 6},
    incremental: true,
    first_run_full: true,
  };
}

/** Turkish ordinal-ish suffix used in "Her ayın 1'i", "2'si", "3'ü", "6'sı", "9'u", "10'u" … */
export function dayOfMonthSuffix(n: number): string {
  const ones = n % 10;
  const tens = Math.floor(n / 10) % 10;
  if (ones === 0) return ({1: "'u", 2: "'si", 3: "'u"} as Record<number, string>)[tens] ?? "'ı";
  return ({1: "'i", 2: "'si", 3: "'ü", 4: "'ü", 5: "'i", 6: "'sı", 7: "'si", 8: "'i", 9: "'u"} as Record<number, string>)[ones];
}

/** Client-side mirror of the backend's schedule_text (used for live preview while editing). */
export function scheduleText(s: ScheduleSpec): string {
  switch (s.kind) {
    case 'daily':
      return `Her gün ${s.time}`;
    case 'weekly': {
      const days = [...new Set(s.weekdays)].filter((d) => d >= 1 && d <= 7).sort((a, b) => a - b);
      if (days.length === 7) return `Her gün ${s.time}`;
      if (days.join() === '1,2,3,4,5') return `Hafta içi her gün ${s.time}`;
      if (days.join() === '6,7') return `Hafta sonu ${s.time}`;
      return `${days.map((d) => WEEKDAYS[d - 1].short).join(', ')} ${s.time}`;
    }
    case 'monthly':
      return `Her ayın ${s.month_day}${dayOfMonthSuffix(s.month_day)} ${s.time}`;
    case 'interval':
      return s.interval_hours === 1 ? 'Her saat' : `Her ${s.interval_hours} saatte bir`;
  }
}

// ---------------------------------------------------------------------------------------------
// Next runs (local time) — fallback when the preview endpoint is unavailable
// ---------------------------------------------------------------------------------------------

function atTime(d: Date, time: string): Date {
  const [h, m] = time.split(':').map(Number);
  const x = new Date(d);
  x.setHours(h, m, 0, 0);
  return x;
}

const isoDay = (d: Date) => ((d.getDay() + 6) % 7) + 1; // 1 = Monday … 7 = Sunday

/** Next `count` run times strictly after `from` (local time). Interval schedules count from `from`. */
export function computeNextRuns(s: ScheduleSpec, from: Date, count = 3): Date[] {
  const out: Date[] = [];
  if (s.kind === 'interval') {
    const h = Math.min(168, Math.max(1, s.interval_hours || 1));
    for (let i = 1; i <= count; i++) out.push(new Date(from.getTime() + i * h * 3600_000));
    return out;
  }
  if (!TIME_PATTERN.test(s.time)) return out;
  if (s.kind === 'weekly' && !s.weekdays.length) return out;
  const day = new Date(from);
  day.setHours(0, 0, 0, 0);
  for (let i = 0; i < 400 && out.length < count; i++) {
    const d = new Date(day);
    d.setDate(day.getDate() + i);
    let ok = true;
    if (s.kind === 'weekly') ok = s.weekdays.includes(isoDay(d));
    if (s.kind === 'monthly') {
      const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
      ok = d.getDate() === Math.min(s.month_day, last);
    }
    if (!ok) continue;
    const t = atTime(d, s.time);
    if (t > from) out.push(t);
  }
  return out;
}

const timeFmt = new Intl.DateTimeFormat('tr-TR', {hour: '2-digit', minute: '2-digit'});
const dayFmt = new Intl.DateTimeFormat('tr-TR', {day: 'numeric', month: 'short'});

/** "bugün 02:00", "yarın 02:00", "Cum 06:30" (within a week) or "14 Kas Cum 03:00". */
export function formatRunTime(value: string | Date | null | undefined, now: Date = new Date()): string {
  if (!value) return '—';
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const days = Math.floor((d.getTime() - start.getTime()) / 86_400_000);
  const t = timeFmt.format(d);
  const wd = WEEKDAYS[isoDay(d) - 1].short;
  if (days === 0) return `bugün ${t}`;
  if (days === 1) return `yarın ${t}`;
  if (days === -1) return `dün ${t}`;
  if (days > 1 && days < 7) return `${wd} ${t}`;
  return `${dayFmt.format(d)} ${wd} ${t}`;
}

// ---------------------------------------------------------------------------------------------
// Scope queries
// ---------------------------------------------------------------------------------------------

export function filterFromForm(f: FilterForm): ObjectQueryFilter {
  return {
    schemas: [...f.schemas],
    types: [...f.types],
    created_from: f.created_from || null,
    created_to: f.created_to || null,
    modified_from: f.modified_from || null,
    modified_to: f.modified_to || null,
    search: f.search.trim() || null,
  };
}

export function filterFromLog(q: PoolQueryLog): ObjectQueryFilter {
  return {
    schemas: q.schemas ?? [],
    types: q.types ?? [],
    created_from: q.created_from,
    created_to: q.created_to,
    modified_from: q.modified_from,
    modified_to: q.modified_to,
    search: q.search,
  };
}

/** Stable identity of a query (for de-duplication). */
export function filterKey(q: ObjectQueryFilter): string {
  return JSON.stringify([
    [...(q.schemas ?? [])].map((s) => s.toLowerCase()).sort(),
    [...(q.types ?? [])].sort(),
    q.created_from || null,
    q.created_to || null,
    q.modified_from || null,
    q.modified_to || null,
    (q.search ?? '').trim().toLowerCase() || null,
  ]);
}

export function addFilter(list: ObjectQueryFilter[], q: ObjectQueryFilter): ObjectQueryFilter[] {
  const k = filterKey(q);
  return list.some((x) => filterKey(x) === k) ? list : [...list, q];
}

// ---------------------------------------------------------------------------------------------
// Rule selection
// ---------------------------------------------------------------------------------------------

/** Groups whose every enabled rule is in `ruleIds` (and that have at least one enabled rule). */
export function fullyCoveredGroups(rules: Pick<Rule, 'id' | 'enabled'>[], groups: Pick<RuleGroup, 'id' | 'rule_ids'>[], ruleIds: number[]): number[] {
  const on = new Set(ruleIds);
  const enabled = new Set(rules.filter((r) => r.enabled).map((r) => r.id));
  return groups
    .filter((g) => {
      const members = g.rule_ids.filter((id) => enabled.has(id));
      return members.length > 0 && members.every((id) => on.has(id));
    })
    .map((g) => g.id);
}

/** Enabled rule ids a selection resolves to right now. */
export function ruleIdsForSelection(sel: RuleSelection, rules: Pick<Rule, 'id' | 'enabled'>[], groups: Pick<RuleGroup, 'id' | 'rule_ids'>[]): number[] {
  const enabled = rules.filter((r) => r.enabled).map((r) => r.id);
  if (sel.mode === 'all_enabled') return enabled;
  const on = new Set(enabled);
  if (sel.mode === 'groups') {
    const ids = new Set<number>();
    for (const g of groups) if (sel.group_ids.includes(g.id)) for (const id of g.rule_ids) if (on.has(id)) ids.add(id);
    return [...ids];
  }
  return sel.rule_ids.filter((id) => on.has(id));
}

/** Rule ids selected in the picker that are not covered by any fully selected group. */
export function uncoveredRuleIds(groups: Pick<RuleGroup, 'id' | 'rule_ids'>[], coveredGroupIds: number[], ruleIds: number[]): number[] {
  const covered = new Set(groups.filter((g) => coveredGroupIds.includes(g.id)).flatMap((g) => g.rule_ids));
  return ruleIds.filter((id) => !covered.has(id));
}

/** Best-fitting selection for a wizard pick: all enabled → all_enabled; exactly a union of whole groups → groups; else rules. */
export function selectionFromRuleIds(
  rules: Pick<Rule, 'id' | 'enabled'>[],
  groups: Pick<RuleGroup, 'id' | 'rule_ids'>[],
  ruleIds: number[],
): RuleSelection {
  const enabled = rules.filter((r) => r.enabled).map((r) => r.id);
  const on = new Set(ruleIds.filter((id) => enabled.includes(id)));
  if (enabled.length > 0 && enabled.every((id) => on.has(id))) return {mode: 'all_enabled', group_ids: [], rule_ids: []};
  const covered = fullyCoveredGroups(rules, groups, [...on]);
  if (covered.length && uncoveredRuleIds(groups, covered, [...on]).length === 0) return {mode: 'groups', group_ids: covered, rule_ids: []};
  return {mode: 'rules', group_ids: [], rule_ids: [...on]};
}

export function ruleSelectionSummary(sel: RuleSelection): string {
  if (sel.mode === 'all_enabled') return 'Tüm etkin kurallar';
  if (sel.mode === 'groups') return `${sel.group_ids.length} grup`;
  return `${sel.rule_ids.length} kural`;
}

// ---------------------------------------------------------------------------------------------
// Validation + wizard prefill
// ---------------------------------------------------------------------------------------------

export interface ScheduleErrors {
  name?: string;
  connection?: string;
  databases?: string;
  time?: string;
  weekdays?: string;
  month_day?: string;
  interval?: string;
  rules?: string;
}

export function validateSchedule(input: ScheduledAnalysisInput): ScheduleErrors {
  const e: ScheduleErrors = {};
  if (!input.name.trim()) e.name = 'Ad zorunludur.';
  if (!input.connection_id) e.connection = 'Bir bağlantı seçin.';
  if (!input.scope.databases.length) e.databases = 'En az bir veritabanı seçin.';
  const s = input.schedule;
  if (s.kind !== 'interval' && !TIME_PATTERN.test(s.time)) e.time = 'Saat SS:DD biçiminde olmalı (örn. 02:00).';
  if (s.kind === 'weekly' && !s.weekdays.length) e.weekdays = 'En az bir gün seçin.';
  if (s.kind === 'monthly' && !(s.month_day >= 1 && s.month_day <= 31)) e.month_day = 'Ayın günü 1–31 arasında olmalı.';
  if (s.kind === 'interval' && !(Number.isInteger(s.interval_hours) && s.interval_hours >= 1 && s.interval_hours <= 168))
    e.interval = 'Aralık 1–168 saat olmalı.';
  const r = input.rule_selection;
  if (r.mode === 'groups' && !r.group_ids.length) e.rules = 'En az bir grubu tamamen seçin.';
  if (r.mode === 'rules' && !r.rule_ids.length) e.rules = 'En az bir kural seçin.';
  return e;
}

export interface WizardPrefill {
  connectionId: number | null;
  databases: string[];
  queries: PoolQueryLog[];
  ruleIds: number[];
  rules: Pick<Rule, 'id' | 'enabled'>[];
  groups: Pick<RuleGroup, 'id' | 'rule_ids'>[];
  name?: string;
}

/** New Analysis state → schedule input (pool queries become scope queries; rule pick → best selection mode). */
export function scheduleFromWizard(w: WizardPrefill): ScheduledAnalysisInput {
  const base = emptySchedule();
  let queries: ObjectQueryFilter[] = [];
  for (const q of w.queries.filter((x) => x.added > 0)) queries = addFilter(queries, filterFromLog(q));
  // A query with no filters at all means "everything" — the whole scope; keep the list empty then.
  if (queries.some((q) => filterKey(q) === filterKey({schemas: [], types: []}))) queries = [];
  return {
    ...base,
    name: w.name?.trim() ?? '',
    connection_id: w.connectionId ?? 0,
    scope: {databases: [...w.databases], queries},
    rule_selection: selectionFromRuleIds(w.rules, w.groups, w.ruleIds),
  };
}

export function runDurationMs(run: Pick<ScheduledRun, 'started_at' | 'finished_at'>): number | null {
  if (!run.finished_at) return null;
  const ms = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

export const RUN_TRIGGER_LABEL: Record<ScheduledRun['trigger'], string> = {
  schedule: 'Zamanlama',
  manual: 'Elle',
  catch_up: 'Telafi',
};

export const RUN_STATUS_LABEL: Record<ScheduledRun['status'], string> = {
  running: 'Çalışıyor',
  completed: 'Tamamlandı',
  skipped: 'Atlandı',
  failed: 'Başarısız',
};
