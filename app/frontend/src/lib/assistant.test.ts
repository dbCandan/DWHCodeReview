import {describe, expect, it} from 'vitest';
import {
  buildAssistantRequest,
  diffProposal,
  emptyAssistantForm,
  formFromRequest,
  noiseDelta,
  stageTimelineIndex,
  timelineStates,
  validateAssistantForm,
  wizardStep,
} from './assistant';
import type {AssistantSession, Rule, RuleInput} from '@/types';

const base: RuleInput = {
  code: 'DWH-HINT-01',
  name: 'Sorgu ipucu',
  description: 'd',
  recommendation: 'r',
  severity: 'medium',
  kind: 'regex',
  pattern: String.raw`OPTION\s*\(`,
  match_mode: 'match',
  target: 'definition',
  ignore_case: true,
  ignore_comments: true,
  llm_prompt: null,
  object_types: ['PROCEDURE', 'VIEW'],
  enabled: true,
  group_ids: [1, 2],
  builtin_check: null,
  precondition: null,
  metadata_precondition: null,
  requires_metadata: false,
  databases: ['EDWDM'],
  name_pattern: null,
};

describe('assistant: proposal diff', () => {
  it('reports only changed fields with the previous value', () => {
    const original = {...base, id: 7, created_at: '', updated_at: '', exception_count: 0} as Rule;
    const proposal: RuleInput = {
      ...base,
      pattern: String.raw`OPTION\s*\((RECOMPILE|MAXDOP)`,
      severity: 'high',
      object_types: ['VIEW', 'PROCEDURE'], // same set, different order → unchanged
      databases: ['edwdm'], // case-insensitive → unchanged
      group_ids: [2, 1, 3],
      precondition: '', // '' ≈ null → unchanged
    };
    const changes = diffProposal(proposal, original, new Map([[1, 'Performans'], [2, 'Standart']]));
    expect(Object.keys(changes).sort()).toEqual(['group_ids', 'pattern', 'severity']);
    expect(changes.severity).toBe('Orta');
    expect(changes.group_ids).toBe('Performans, Standart');
    expect(changes.pattern).toBe(String.raw`OPTION\s*\(`);
  });
  it('is empty without an original', () => {
    expect(diffProposal(base, null)).toEqual({});
  });
});

describe('assistant: stages', () => {
  const s = (over: Partial<AssistantSession>) =>
    ({stage: 'matching', status: 'running', request: {description: 'x', positive_examples: [], noise: null}, noise: null, proposal: null, ...over}) as AssistantSession;
  it('maps refining onto the validation step', () => {
    expect(stageTimelineIndex('matching')).toBe(0);
    expect(stageTimelineIndex('refining')).toBe(stageTimelineIndex('validating'));
    expect(stageTimelineIndex('done')).toBe(4);
  });
  it('derives timeline states', () => {
    expect(timelineStates(s({stage: 'drafting'}))).toEqual(['done', 'active', 'pending', 'pending', 'pending']);
    expect(timelineStates(s({stage: 'done', status: 'ready'}))).toEqual(['done', 'done', 'done', 'skipped', 'done']);
    const withNoise = s({stage: 'validating', status: 'failed', request: {description: 'x', positive_examples: [], noise: {connection_id: 1, databases: ['A'], sample_size: 50}}});
    expect(timelineStates(withNoise)).toEqual(['done', 'done', 'failed', 'pending', 'pending']);
  });
  it('maps a session to the wizard step', () => {
    expect(wizardStep(null)).toBe(0);
    expect(wizardStep(s({status: 'running'}))).toBe(1);
    expect(wizardStep(s({status: 'failed'}))).toBe(1);
    expect(wizardStep(s({status: 'ready'}))).toBe(2);
    expect(wizardStep(s({status: 'saved'}))).toBe(2);
  });
});

describe('assistant: definition form', () => {
  it('validates description, examples and noise settings', () => {
    const f = emptyAssistantForm();
    const e = validateAssistantForm(f);
    expect(e.description).toMatch(/en az 10/);
    expect(e.positives).toMatch(/en az bir/i);
    expect(e.noise).toMatch(/bağlantı/);
    const ok = {...f, description: 'OPTION (RECOMPILE) kullanılmamalı', positives: [{sql: 'SELECT 1 OPTION (RECOMPILE)', note: ''}], noiseEnabled: false};
    expect(validateAssistantForm(ok)).toEqual({});
    const tooMany = {...ok, negatives: Array.from({length: 11}, () => ({sql: 'x', note: ''}))};
    expect(validateAssistantForm(tooMany).negatives).toMatch(/10/);
    expect(validateAssistantForm({...ok, noiseEnabled: true, connection_id: 1, databases: []}).noise).toMatch(/veritabanı/);
  });
  it('builds the request (drops empty examples) and round-trips it', () => {
    const f = {
      ...emptyAssistantForm(),
      description: '  OPTION (RECOMPILE) kullanılmamalı ',
      positives: [{sql: 'SELECT 1 OPTION (RECOMPILE)  ', note: ' hint '}, {sql: '   ', note: 'boş'}],
      negatives: [{sql: '-- OPTION (RECOMPILE)', note: ''}],
      severity_hint: 'high' as const,
      connection_id: 1,
      databases: ['EDWDM'],
    };
    const r = buildAssistantRequest(f);
    expect(r.description).toBe('OPTION (RECOMPILE) kullanılmamalı');
    expect(r.positive_examples).toEqual([{sql: 'SELECT 1 OPTION (RECOMPILE)', note: 'hint'}]);
    expect(r.negative_examples).toEqual([{sql: '-- OPTION (RECOMPILE)', note: null}]);
    expect(r.preferred_kind).toBeNull();
    expect(r.noise).toEqual({connection_id: 1, databases: ['EDWDM'], object_types: [], sample_size: 50});
    expect(buildAssistantRequest({...f, noiseEnabled: false}).noise).toBeNull();
    const back = formFromRequest(r);
    expect(back.positives).toHaveLength(1);
    expect(back.noiseEnabled).toBe(true);
    expect(back.severity_hint).toBe('high');
  });
  it('formats the noise delta', () => {
    expect(noiseDelta(12, 5)).toBe('+7');
    expect(noiseDelta(3, 5)).toBe('−2');
    expect(noiseDelta(5, 5)).toBe('±0');
    expect(noiseDelta(5, null)).toBeNull();
  });
});
