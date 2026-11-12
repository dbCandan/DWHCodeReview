import {describe, expect, it} from 'vitest';
import {
  EMPTY_EXCEPTION_MESSAGE,
  escapeRegex,
  exceptionPreview,
  exceptionScopeLabel,
  suggestSnippetPattern,
  toExceptionPayload,
  validateException,
} from './exceptions';

describe('exception helpers', () => {
  it('suggests an escaped, whitespace-tolerant key part of the snippet', () => {
    const p = suggestSnippetPattern('  OPTION (MIN_GRANT_PERCENT = 5, MAX_GRANT_PERCENT = 20)  ');
    expect(p).toBe(String.raw`OPTION\s*\(\s*MIN_GRANT_PERCENT`);
    const re = new RegExp(p, 'i');
    expect(re.test('option(min_grant_percent=10)')).toBe(true);
    expect(re.test('OPTION (MAXDOP 1)')).toBe(false);
    // Short pairs take a third identifier; dots are escaped.
    expect(suggestSnippetPattern('FROM A.B WITH (NOLOCK)')).toBe(String.raw`FROM\s+A\s*\.\s*B`);
    expect(suggestSnippetPattern('')).toBe('');
    expect(suggestSnippetPattern(null)).toBe('');
  });

  it('escapes regex metacharacters', () => {
    expect(escapeRegex('a.b(c)*[d]$')).toBe(String.raw`a\.b\(c\)\*\[d\]\$`);
  });

  it('describes the scope and builds the preview sentence', () => {
    expect(exceptionScopeLabel({})).toBe('Tüm nesneler');
    expect(exceptionScopeLabel({database: 'EDWDM', schema: 'dbo', object_name: 'spLoad'})).toBe('EDWDM.dbo.spLoad');
    expect(exceptionScopeLabel({database: 'EDWDM', schema: ' ', object_name: null})).toBe('EDWDM.*.*');
    expect(exceptionPreview('DWH-HINT-01', {database: 'EDWDM', schema: 'dbo', object_name: 'spLoad'}, 'OPTION')).toBe(
      'DWH-HINT-01 kuralı için EDWDM.dbo.spLoad nesnesinde “OPTION” içeren bulgular bundan sonraki analizlerde raporlanmayacak.',
    );
    expect(exceptionPreview('R1', {}, 'X')).toBe('R1 kuralı için tüm nesnelerde “X” içeren bulgular bundan sonraki analizlerde raporlanmayacak.');
    expect(exceptionPreview('R1', {object_name: 'v'}, '')).toContain('*.*.v nesnesinde tüm bulgular');
  });

  it('validates like the backend and normalizes the payload', () => {
    expect(validateException({reason: 'x'})).toBe(EMPTY_EXCEPTION_MESSAGE);
    expect(validateException({database: ' ', snippet_pattern: '', reason: 'x'})).toBe(EMPTY_EXCEPTION_MESSAGE);
    expect(validateException({snippet_pattern: 'OPTION', reason: '  '})).toBe('İstisna nedeni zorunludur.');
    expect(validateException({object_name: 'sp', reason: 'a'.repeat(501)})).toMatch(/500/);
    expect(validateException({object_name: 'sp', reason: 'ok'})).toBeNull();
    expect(toExceptionPayload({database: ' EDWDM ', schema: '', reason: ' r '})).toEqual({
      database: 'EDWDM',
      schema: null,
      object_name: null,
      snippet_pattern: null,
      reason: 'r',
    });
  });
});
