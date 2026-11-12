import {describe, expect, it} from 'vitest';
import {mergePool, objectKey, removeFromPool, sortObjects} from './pool';
import {highlightSql} from './sql';
import {countBySeverity, normalizeCounts, sumCounts, topSeverity, totalCount} from './severity';
import {buildLineMarks, groupFindings} from './findings';
import {effectiveRules, estimateChecks} from './wizard';
import {estimateCheckSplit, formatLlmEstimate, isInfoNote, regexWarning, scopeShort, scopeSummary} from './rules';
import {extractDetail} from './api';
import {fold, formatDuration, matchesSearch} from './format';
import type {DbObject, Finding, Rule, RuleGroup} from '@/types';

const obj = (database: string, schema: string, name: string, type: DbObject['type'] = 'PROCEDURE'): DbObject => ({
  database,
  schema,
  name,
  type,
  create_date: '2024-01-01T00:00:00Z',
  modify_date: '2024-06-01T00:00:00Z',
});

describe('pool', () => {
  it('dedupes by db.schema.name case-insensitively', () => {
    const pool = [obj('DWH', 'dbo', 'usp_A')];
    const r = mergePool(pool, [obj('dwh', 'DBO', 'USP_A'), obj('DWH', 'dbo', 'usp_B'), obj('DWH', 'dbo', 'usp_B')]);
    expect(r.added).toBe(1);
    expect(r.skipped).toBe(2);
    expect(r.pool.map((o) => o.name)).toEqual(['usp_A', 'usp_B']);
  });

  it('removes by key and sorts', () => {
    const pool = [obj('DWH', 'dbo', 'b'), obj('DWH', 'dbo', 'a'), obj('DWH', 'stg', 'c')];
    expect(removeFromPool(pool, [objectKey(pool[0])]).map((o) => o.name)).toEqual(['a', 'c']);
    expect(sortObjects(pool, 'name', 'asc').map((o) => o.name)).toEqual(['a', 'b', 'c']);
    expect(sortObjects(pool, 'schema', 'desc')[0].schema).toBe('stg');
  });
});

describe('sql highlighter', () => {
  it('classifies keywords, strings, comments, variables and numbers', () => {
    const [line] = highlightSql("SELECT @x = 1, N'abc' -- note");
    const types = line.map((t) => `${t.type}:${t.value.trim()}`).filter((s) => !s.endsWith(':'));
    expect(types).toContain('kw:SELECT');
    expect(types).toContain('var:@x');
    expect(types).toContain('num:1');
    expect(types).toContain("str:N'abc'");
    expect(types).toContain('com:-- note');
  });

  it('carries block comments and strings across lines', () => {
    const lines = highlightSql("/* start\nstill comment */ SELECT 'a\nb' FROM t");
    expect(lines[0].every((t) => t.type === 'com')).toBe(true);
    expect(lines[1][0]).toEqual({type: 'com', value: 'still comment */'});
    expect(lines[2][0]).toEqual({type: 'str', value: "b'"});
    expect(lines[2].some((t) => t.type === 'kw' && t.value === 'FROM')).toBe(true);
  });

  it('handles escaped quotes', () => {
    const [line] = highlightSql("SET @s = 'it''s'");
    expect(line.find((t) => t.type === 'str')?.value).toBe("'it''s'");
  });
});

describe('severity aggregation', () => {
  it('counts, sums and finds the top severity', () => {
    const counts = countBySeverity([{severity: 'high'}, {severity: 'high'}, {severity: 'info'}]);
    expect(counts).toEqual({critical: 0, high: 2, medium: 0, low: 0, info: 1});
    expect(totalCount(counts)).toBe(3);
    expect(topSeverity(counts)).toBe('high');
    expect(sumCounts([counts, {critical: 1}])).toMatchObject({critical: 1, high: 2, info: 1});
    expect(normalizeCounts(undefined)).toEqual({critical: 0, high: 0, medium: 0, low: 0, info: 0});
    expect(topSeverity(null)).toBeNull();
  });
});

const finding = (id: number, rule: string, severity: Finding['severity'], line: number | null, object_id = 1): Finding => ({
  id,
  object_id,
  object_label: `DWH.dbo.o${object_id}`,
  rule_code: rule,
  rule_name: rule,
  severity,
  kind: 'regex',
  line,
  snippet: '',
  message: 'm',
  recommendation: '',
});

describe('findings', () => {
  it('builds line marks with the highest severity per line', () => {
    const marks = buildLineMarks([
      {line: 3, severity: 'low', message: 'a'},
      {line: 3, severity: 'critical', message: 'b'},
      {line: null, severity: 'high', message: 'c'},
    ]);
    expect(marks.size).toBe(1);
    expect(marks.get(3)?.severity).toBe('critical');
    expect(marks.get(3)?.notes).toHaveLength(2);
  });

  it('groups by rule ordered by severity', () => {
    const groups = groupFindings([finding(1, 'B', 'low', 1), finding(2, 'A', 'high', 2), finding(3, 'B', 'low', 3)], 'rule');
    expect(groups.map((g) => g.key)).toEqual(['A', 'B']);
    expect(groups[1].items).toHaveLength(2);
  });
});

describe('wizard helpers', () => {
  const rule = (id: number, enabled = true, object_types: Rule['object_types'] = []): Rule =>
    ({id, enabled, object_types, kind: 'regex', severity: 'medium', code: `R${id}`}) as Rule;
  it('takes the union of groups and rules, enabled only', () => {
    const rules = [rule(1), rule(2), rule(3, false), rule(4)];
    const groups = [{id: 10, rule_ids: [1, 3]} as RuleGroup];
    expect(effectiveRules(rules, groups, [10], [1, 4]).map((r) => r.id)).toEqual([1, 4]);
  });
  it('estimates checks respecting object types', () => {
    const objects = [obj('a', 'b', 'c', 'VIEW'), obj('a', 'b', 'd', 'PROCEDURE')];
    expect(estimateChecks(objects, [rule(1), rule(2, true, ['VIEW'])])).toBe(3);
  });
});

describe('misc', () => {
  it('extracts API error detail', () => {
    expect(extractDetail({detail: 'Kural bulunamadı'}, 404)).toBe('Kural bulunamadı');
    expect(extractDetail({detail: [{msg: 'a'}, {msg: 'b'}]}, 422)).toBe('a · b');
    expect(extractDetail(undefined, 502)).toMatch(/ulaşılamadı/);
  });
  it('folds Turkish text for search', () => {
    expect(fold('İŞLEM Iğdır')).toBe('islem igdir');
    expect(matchesSearch('islem', 'Günlük İşlem')).toBe(true);
  });
  it('formats durations', () => {
    expect(formatDuration(450)).toBe('450 ms');
    expect(formatDuration(2500)).toBe('2,5 sn');
    expect(formatDuration(125000)).toBe('2 dk 5 sn');
  });
});

describe('rule helpers', () => {
  it('builds the scope summary sentence', () => {
    expect(scopeSummary({})).toBe('Tüm veritabanlarındaki tüm nesnelere uygulanır.');
    expect(scopeSummary({object_types: ['VIEW'], databases: ['EDWDM'], name_pattern: String.raw`^[^.]+\.v`})).toBe(
      String.raw`EDWDM veritabanındaki, adı “^[^.]+\.v” desenine uyan VIEW nesnelerine uygulanır.`,
    );
    expect(scopeSummary({object_types: ['PROCEDURE', 'VIEW'], databases: ['EDW', 'EDWDM', 'EDWSTG']})).toBe(
      'EDW, EDWDM ve EDWSTG veritabanlarındaki PROCEDURE ve VIEW nesnelerine uygulanır.',
    );
    expect(scopeShort({object_types: ['VIEW'], databases: ['EDWDM'], name_pattern: 'x'})).toBe('VIEW · EDWDM · ad deseni');
    expect(scopeShort({object_types: null, databases: undefined})).toBe('Tümü');
  });

  it('splits checks into instant and LLM respecting the full scope', () => {
    const objects = [obj('EDWDM', 'TRX', 'vSales', 'VIEW'), obj('EDWDM', 'TRX', 'vSalesMasked', 'VIEW'), obj('EDW', 'dbo', 'spLoad')];
    const est = estimateCheckSplit(objects, [
      {kind: 'regex', object_types: []},
      {kind: 'builtin', object_types: ['VIEW'], databases: ['edwdm'], name_pattern: '(?:Masked)$'},
      {kind: 'llm', object_types: ['VIEW'], databases: ['EDWDM'], name_pattern: String.raw`^[^.]+\.v(?!.*Masked$)`},
      {kind: 'llm', object_types: ['PROCEDURE']},
    ]);
    expect(est).toEqual({instant: 4, llm: 2, total: 6, llmMaxMs: 2 * 45 * 1000});
    expect(formatLlmEstimate(est.llmMaxMs)).toBe('en fazla ~1 dk 30 sn');
    expect(estimateChecks(objects, [{databases: ['EDW']}])).toBe(1);
  });

  it('warns (without blocking) on regexes JS cannot compile', () => {
    expect(regexWarning(String.raw`(?i)\bSELECT\s+\*`)).toBeNull();
    expect(regexWarning('(?P<x>a)(?P=x)')).toBeNull();
    expect(regexWarning('')).toBeNull();
    expect(regexWarning('(unclosed')).toMatch(/sunucu doğrular/);
    expect(isInfoNote('Bu kural katalog metadatası gerektirir; tam sonuç için analiz çalıştırın.')).toBe(true);
    expect(isInfoNote('Geçersiz regex')).toBe(false);
  });
});
