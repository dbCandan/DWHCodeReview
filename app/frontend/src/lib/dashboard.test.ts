import {describe, expect, it} from 'vitest';
import {niceTicks, shortModelName, trendAnalyses} from './dashboard';
import type {AnalysisSummary} from '@/types';

const a = (id: number, status: AnalysisSummary['status'], finished: string | null) =>
  ({id, status, created_at: finished ?? '2026-01-01T00:00:00Z', finished_at: finished}) as AnalysisSummary;

describe('dashboard helpers', () => {
  it('keeps the last n completed analyses, oldest first', () => {
    const list = [a(3, 'completed', '2026-11-03T00:00:00Z'), a(4, 'running', null), a(1, 'completed', '2026-11-01T00:00:00Z'), a(2, 'failed', '2026-11-02T00:00:00Z'), a(5, 'completed', '2026-11-05T00:00:00Z')];
    expect(trendAnalyses(list, 2).map((x) => x.id)).toEqual([3, 5]);
    expect(trendAnalyses(null)).toEqual([]);
  });
  it('builds nice axis ticks', () => {
    expect(niceTicks(0)).toEqual([0, 1]);
    expect(niceTicks(9)).toEqual([0, 2.5, 5, 7.5, 10]);
    expect(niceTicks(6793)).toEqual([0, 2000, 4000, 6000, 8000]);
    expect(niceTicks(100)).toEqual([0, 25, 50, 75, 100]);
  });
  it('shortens model names', () => {
    expect(shortModelName('google/gemma-4-31b')).toBe('gemma-4-31b');
    expect(shortModelName('gpt-4o-mini')).toBe('gpt-4o-mini');
    expect(shortModelName('')).toBe('—');
  });
});

import {logTicks} from '@/components/dashboard/FindingTrend';

describe('logTicks', () => {
  it('covers the maximum with powers of ten', () => {
    expect(logTicks(1)).toEqual([0, 1]);
    expect(logTicks(9)).toEqual([0, 1, 10]);
    expect(logTicks(5983)).toEqual([0, 1, 10, 100, 1000, 10000]);
  });
});
