import {describe, expect, it} from 'vitest';
import {compileRulePattern, MAX_PATTERN_LENGTH, regexWarning} from './rules';

describe('compileRulePattern', () => {
  it('compiles Python-style rule patterns', () => {
    expect(compileRulePattern(String.raw`(?i)^scd\.mrg`, 'i').test('SCD.mrgCONAccount')).toBe(true);
  });

  it('refuses patterns longer than the limit before compiling', () => {
    expect(() => compileRulePattern('a'.repeat(MAX_PATTERN_LENGTH + 1))).toThrow(SyntaxError);
    expect(regexWarning('a'.repeat(MAX_PATTERN_LENGTH + 1))).toContain('aşıyor');
  });
});
