import {describe, expect, it} from 'vitest';
import {
  RECENT_OBJECTS,
  applyEvent,
  completionRatio,
  createProgress,
  orderedObjects,
  tokenLabel,
} from './reviewProgress';
import {objectRunEvents} from '@/test/reviewEvents';
import type {ReviewStreamEvent} from '@/types/sqlReview';

function replay(events: ReviewStreamEvent[], objectsTotal = 1) {
  return events.reduce(applyEvent, createProgress(objectsTotal));
}

describe('live review progress', () => {
  it('merges the event sequence into stages, rule counters and token counts', () => {
    const events = objectRunEvents();
    const progress = replay(events.slice(0, -1));
    // A finished object leaves the in-flight map and becomes the newest recent one.
    expect(orderedObjects(progress)).toEqual([]);
    const [object] = progress.recent;
    expect(progress).toMatchObject({runId: 'run-1', ruleVersion: 2, objectsDone: 1, objectsFailed: 0});
    expect(object).toMatchObject({stage: 'done', rulesTotal: 2, rulesDone: 2, sqlLength: 1200});
    expect(object.ruleOrder).toEqual(['Kural01', 'Kural03']);
    expect(object.rules.Kural01).toMatchObject({stage: 'done', tier: 'critical', completionTokens: 30});
    expect(object.rules.Kural03).toMatchObject({stage: 'failed'});
    expect(completionRatio(progress)).toBe(1);
  });

  it('shows a running rule with streamed counts but no model text', () => {
    const progress = replay(objectRunEvents().slice(0, 7));
    const rule = orderedObjects(progress)[0].rules.Kural01;
    expect(rule).toMatchObject({stage: 'running', completionTokens: 12, totalChars: 48});
    expect(tokenLabel(rule)).toBe('12 belirteç');
    expect(Object.keys(rule)).not.toContain('text');
  });

  it('marks an object error and keeps other objects going', () => {
    const second = {
      kind: 'object' as const,
      database: 'MART',
      object_index: 1,
      objects_total: 2,
      object_label: '[MART] dbo.v (V)',
      schema: 'dbo',
      name: 'v',
      type_code: 'V',
    };
    const progress = replay(
      [
        {phase: 'run_started', run_id: 'run-1', rule_version: 2, objects_total: 2, kind: 'object', all_rules: true},
        ...objectRunEvents().slice(1, 5),
        {...second, phase: 'object_start'},
        {...second, phase: 'object_error', code: 'object_not_found', message: 'Tanım alınamadı (nesne yok veya yetki yok).'},
        {...second, phase: 'object_done'},
      ],
      2,
    );
    expect(orderedObjects(progress).map((object) => object.stage)).toEqual(['rules']);
    expect(progress.recent.map((object) => [object.index, object.stage])).toEqual([[1, 'error']]);
    expect(progress.recent[0].error?.code).toBe('object_not_found');
    expect([progress.objectsDone, progress.objectsFailed]).toEqual([0, 1]);
    expect(completionRatio(progress)).toBeCloseTo(0.5);
  });

  it('keeps only the objects in flight and the last finished ones for a run of thousands', () => {
    const total = 5_000;
    const inFlight = 6;
    let progress = applyEvent(createProgress(total), {
      phase: 'run_started',
      run_id: 'run-1',
      rule_version: 2,
      objects_total: total,
      kind: 'object',
      all_rules: true,
    });
    const fields = (index: number) => ({
      kind: 'object' as const,
      database: 'DWH',
      object_index: index,
      objects_total: total,
      object_label: `[DWH] dbo.p${index} (P)`,
      schema: 'dbo',
      name: `p${index}`,
      type_code: 'P',
    });
    let largest = 0;
    for (let index = 0; index < total; index += 1) {
      progress = applyEvent(progress, {...fields(index), phase: 'object_start'});
      largest = Math.max(largest, Object.keys(progress.objects).length);
      if (index >= inFlight - 1) {
        const leaving = index - (inFlight - 1);
        progress =
          leaving % 10 === 0
            ? applyEvent(progress, {...fields(leaving), phase: 'object_error', code: 'object_not_found', message: 'x'})
            : applyEvent(progress, {...fields(leaving), phase: 'object_done'});
      }
    }
    const finishedCount = total - (inFlight - 1);
    expect(largest).toBe(inFlight);
    expect(Object.keys(progress.objects)).toHaveLength(inFlight - 1);
    expect(progress.recent).toHaveLength(RECENT_OBJECTS);
    expect(progress.recent[0].index).toBe(finishedCount - 1);
    expect(progress.objectsDone + progress.objectsFailed).toBe(finishedCount);
    expect(progress.objectsFailed).toBe(Math.ceil(finishedCount / 10));
    expect(completionRatio(progress)).toBeCloseTo(finishedCount / total);
  });

  it('estimates tokens from characters when the server sends no count', () => {
    expect(
      tokenLabel({ruleId: 'K', tier: null, stage: 'running', completionTokens: null, totalChars: 41, twoPart: false}),
    ).toBe('~11 belirteç');
    expect(
      tokenLabel({ruleId: 'K', tier: null, stage: 'running', completionTokens: null, totalChars: 0, twoPart: false}),
    ).toBe('Yanıt bekleniyor');
  });
});
