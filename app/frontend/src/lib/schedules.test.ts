import {describe, expect, it} from 'vitest';
import {
  addFilter,
  computeNextRuns,
  dayOfMonthSuffix,
  emptySchedule,
  filterFromForm,
  formatRunTime,
  fullyCoveredGroups,
  ruleIdsForSelection,
  scheduleFromWizard,
  scheduleText,
  selectionFromRuleIds,
  uncoveredRuleIds,
  validateSchedule,
} from './schedules';
import {describeQuery, EMPTY_FILTER, type PoolQueryLog} from './wizard';
import type {ScheduleSpec} from '@/types';

const spec = (over: Partial<ScheduleSpec>): ScheduleSpec => ({kind: 'daily', time: '02:00', weekdays: [], month_day: 1, interval_hours: 6, ...over});

describe('schedule text', () => {
  it('matches the backend wording', () => {
    expect(scheduleText(spec({}))).toBe('Her gün 02:00');
    expect(scheduleText(spec({kind: 'weekly', time: '06:30', weekdays: [5, 1, 3]}))).toBe('Pzt, Çar, Cum 06:30');
    expect(scheduleText(spec({kind: 'weekly', weekdays: [1, 2, 3, 4, 5]}))).toBe('Hafta içi her gün 02:00');
    expect(scheduleText(spec({kind: 'weekly', weekdays: [1, 2, 3, 4, 5, 6, 7]}))).toBe('Her gün 02:00');
    expect(scheduleText(spec({kind: 'monthly', time: '03:00', month_day: 1}))).toBe("Her ayın 1'i 03:00");
    expect(scheduleText(spec({kind: 'interval', interval_hours: 6}))).toBe('Her 6 saatte bir');
  });
  it('picks Turkish day suffixes', () => {
    expect([1, 2, 3, 6, 9, 10, 15, 20, 30, 31].map((n) => `${n}${dayOfMonthSuffix(n)}`)).toEqual([
      "1'i", "2'si", "3'ü", "6'sı", "9'u", "10'u", "15'i", "20'si", "30'u", "31'i",
    ]);
  });
});

describe('next runs (local time)', () => {
  const from = new Date(2026, 10, 12, 15, 0); // Thu 12 Nov 2026 15:00
  it('daily: tomorrow when today has passed', () => {
    const r = computeNextRuns(spec({time: '02:00'}), from, 3);
    expect(r.map((d) => [d.getDate(), d.getHours()])).toEqual([[13, 2], [14, 2], [15, 2]]);
    expect(computeNextRuns(spec({time: '18:30'}), from, 1)[0].getDate()).toBe(12);
  });
  it('weekly: only selected weekdays', () => {
    const r = computeNextRuns(spec({kind: 'weekly', weekdays: [1, 5], time: '06:00'}), from, 3);
    expect(r.map((d) => d.getDay())).toEqual([5, 1, 5]); // Fri, Mon, Fri
  });
  it('monthly: clamps to the last day of short months', () => {
    const r = computeNextRuns(spec({kind: 'monthly', month_day: 31, time: '03:00'}), from, 3);
    expect(r.map((d) => `${d.getMonth() + 1}/${d.getDate()}`)).toEqual(['11/30', '12/31', '1/31']);
  });
  it('interval: counts from now; invalid input yields nothing', () => {
    expect(computeNextRuns(spec({kind: 'interval', interval_hours: 6}), from, 2).map((d) => d.getHours())).toEqual([21, 3]);
    expect(computeNextRuns(spec({kind: 'weekly', weekdays: []}), from)).toEqual([]);
    expect(computeNextRuns(spec({time: '25:00'}), from)).toEqual([]);
  });
  it('formats run times relative to now', () => {
    expect(formatRunTime(new Date(2026, 10, 12, 18, 30), from)).toBe('bugün 18:30');
    expect(formatRunTime(new Date(2026, 10, 13, 2, 0), from)).toBe('yarın 02:00');
    expect(formatRunTime(new Date(2026, 10, 16, 6, 0), from)).toBe('Pzt 06:00');
    expect(formatRunTime(null, from)).toBe('—');
    expect(formatRunTime(new Date(2026, 11, 1, 3, 0), from)).toMatch(/Ara Sal 03:00$/);
  });
});

describe('scope queries', () => {
  it('builds a filter from the form, de-duplicates and describes it', () => {
    const q = filterFromForm({...EMPTY_FILTER, schemas: ['EDWDM.TRX'], types: ['VIEW'], search: ' vSales '});
    expect(q).toEqual({schemas: ['EDWDM.TRX'], types: ['VIEW'], created_from: null, created_to: null, modified_from: null, modified_to: null, search: 'vSales'});
    const list = addFilter(addFilter([], q), {...q, schemas: ['edwdm.trx']});
    expect(list).toHaveLength(1);
    expect(describeQuery(q)).toEqual(['Şema: EDWDM.TRX', 'Tip: View', 'Ad içerir: “vSales”']);
    expect(describeQuery({schemas: [], types: []})).toEqual(['Filtresiz (tüm nesneler)']);
  });
});

describe('rule selection', () => {
  const rules = [1, 2, 3, 4, 5].map((id) => ({id, enabled: id !== 5}));
  const groups = [
    {id: 10, rule_ids: [1, 2]},
    {id: 20, rule_ids: [3, 5]}, // 5 is disabled → only 3 counts
  ];
  it('finds fully covered groups and leftovers', () => {
    expect(fullyCoveredGroups(rules, groups, [1, 2, 3])).toEqual([10, 20]);
    expect(fullyCoveredGroups(rules, groups, [1, 3])).toEqual([20]);
    expect(uncoveredRuleIds(groups, [20], [1, 3])).toEqual([1]);
  });
  it('maps a wizard pick to the best mode and back', () => {
    expect(selectionFromRuleIds(rules, groups, [1, 2, 3, 4]).mode).toBe('all_enabled');
    expect(selectionFromRuleIds(rules, groups, [1, 2, 3])).toEqual({mode: 'groups', group_ids: [10, 20], rule_ids: []});
    expect(selectionFromRuleIds(rules, groups, [1, 4])).toEqual({mode: 'rules', group_ids: [], rule_ids: [1, 4]});
    expect(ruleIdsForSelection({mode: 'groups', group_ids: [20], rule_ids: []}, rules, groups)).toEqual([3]);
    expect(ruleIdsForSelection({mode: 'rules', group_ids: [], rule_ids: [4, 5]}, rules, groups)).toEqual([4]);
    expect(ruleIdsForSelection({mode: 'all_enabled', group_ids: [], rule_ids: []}, rules, groups)).toEqual([1, 2, 3, 4]);
  });
});

describe('wizard → schedule prefill and validation', () => {
  const log = (over: Partial<PoolQueryLog>): PoolQueryLog => ({
    databases: ['EDWDM'], schemas: [], types: [], created_from: null, created_to: null, modified_from: null, modified_to: null, search: null, matched: 10, added: 10, ...over,
  });
  it('turns pool queries into scope queries (skipping no-op queries)', () => {
    const s = scheduleFromWizard({
      connectionId: 1,
      databases: ['EDWDM'],
      queries: [log({types: ['VIEW']}), log({types: ['VIEW']}), log({search: 'x', added: 0})],
      ruleIds: [1],
      rules: [{id: 1, enabled: true}, {id: 2, enabled: true}],
      groups: [],
      name: ' Gece ',
    });
    expect(s.name).toBe('Gece');
    expect(s.connection_id).toBe(1);
    expect(s.scope.queries).toHaveLength(1);
    expect(s.scope.queries[0].types).toEqual(['VIEW']);
    expect(s.rule_selection).toEqual({mode: 'rules', group_ids: [], rule_ids: [1]});
    expect(s.incremental).toBe(true);
    const all = scheduleFromWizard({connectionId: 1, databases: ['A'], queries: [log({}), log({types: ['VIEW']})], ruleIds: [], rules: [], groups: []});
    expect(all.scope.queries).toEqual([]); // an unfiltered query = everything
  });
  it('validates required fields', () => {
    const e = validateSchedule(emptySchedule());
    expect(Object.keys(e).sort()).toEqual(['connection', 'databases', 'name']);
    const ok = {...emptySchedule(), name: 'x', connection_id: 1, scope: {databases: ['A'], queries: []}};
    expect(validateSchedule(ok)).toEqual({});
    expect(validateSchedule({...ok, schedule: spec({kind: 'weekly', weekdays: []})}).weekdays).toBeTruthy();
    expect(validateSchedule({...ok, schedule: spec({kind: 'interval', interval_hours: 200})}).interval).toMatch(/1–168/);
    expect(validateSchedule({...ok, schedule: spec({time: '2:00'})}).time).toBeTruthy();
    expect(validateSchedule({...ok, rule_selection: {mode: 'groups', group_ids: [], rule_ids: []}}).rules).toBeTruthy();
  });
});
