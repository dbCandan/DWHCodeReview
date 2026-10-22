import {describe, expect, it} from 'vitest';
import {lineMarks, referencedLines} from './codeLines';
import type {Finding, RuleResult} from '@/types/sqlReview';

function finding(overrides: Partial<Finding>): Finding {
  return {
    id: 'f',
    rule_id: 'Kural01',
    severity: 'MEDIUM',
    description: '',
    line_reference: '',
    code_snippet: '',
    false_positive: false,
    ...overrides,
  };
}

function rule(overrides: Partial<RuleResult>): RuleResult {
  return {
    id: 'r',
    rule_id: 'Kural02',
    status: 'FAIL',
    severity: 'LOW',
    tier: 'normal',
    description: '',
    line_reference: '',
    code_snippet: '',
    decision_basis: null,
    false_positive: false,
    ...overrides,
  };
}

describe('line references of findings', () => {
  it('reads single lines, ranges, lists and the model form', () => {
    expect(referencedLines('Satır 12')).toEqual([12]);
    expect(referencedLines('Satır 3–5')).toEqual([3, 4, 5]);
    expect(referencedLines('Satır 9, 2, 9')).toEqual([2, 9]);
    expect(referencedLines('L007-L008')).toEqual([7, 8]);
    expect(referencedLines('Nesnenin tamamı')).toEqual([]);
    expect(referencedLines('Satır 1–5000')).toEqual([]);
  });

  it('keeps the highest severity of a line and skips false positives', () => {
    const marks = lineMarks(
      [
        finding({rule_id: 'Kural01', severity: 'LOW', line_reference: 'Satır 4'}),
        finding({id: 'g', rule_id: 'Kural03', severity: 'HIGH', line_reference: 'Satır 4–5'}),
        finding({id: 'h', rule_id: 'Kural04', severity: 'HIGH', line_reference: 'Satır 9', false_positive: true}),
      ],
      [rule({line_reference: 'Satır 7'}), rule({rule_id: 'Kural01', line_reference: 'Satır 8'})],
    );
    expect(marks.get(4)).toEqual({severity: 'HIGH', rules: ['Kural01', 'Kural03']});
    expect(marks.get(5)?.severity).toBe('HIGH');
    expect(marks.has(9)).toBe(false);
    // A failed rule without findings marks its own lines; one with findings does not.
    expect(marks.get(7)).toEqual({severity: 'LOW', rules: ['Kural02']});
    expect(marks.has(8)).toBe(false);
  });
});
