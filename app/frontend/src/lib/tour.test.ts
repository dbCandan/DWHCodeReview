import {afterEach, describe, expect, it, vi} from 'vitest';
import {DEMO_FALLBACK, DEMO_SQL, markTourSeen, onOpenTour, openTour, SPOTLIGHT_STEPS, TOUR_SEEN_KEY, tourSeen} from './tour';

describe('tour', () => {
  afterEach(() => localStorage.clear());

  it('is unseen until marked', () => {
    expect(tourSeen()).toBe(false);
    markTourSeen();
    expect(tourSeen()).toBe(true);
    expect(localStorage.getItem(TOUR_SEEN_KEY)).toBe('1');
  });

  it('delivers open requests with their starting phase', () => {
    const handler = vi.fn();
    const off = onOpenTour(handler);
    openTour('demo');
    openTour();
    off();
    openTour('spotlight');
    expect(handler.mock.calls).toEqual([['demo'], ['welcome']]);
  });

  it('has unique steps that each name a page', () => {
    const keys = SPOTLIGHT_STEPS.map((s) => s.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const s of SPOTLIGHT_STEPS) expect(s.route.startsWith('/')).toBe(true);
  });

  it('keeps fallback findings on lines of the sample procedure', () => {
    const lines = DEMO_SQL.split('\n');
    for (const f of DEMO_FALLBACK) {
      expect(f.line).not.toBeNull();
      expect(lines[(f.line ?? 0) - 1]).toContain(f.snippet.trim().split(' ')[0]);
    }
  });
});
