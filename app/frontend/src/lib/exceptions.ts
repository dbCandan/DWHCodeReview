import type {RuleException, RuleExceptionInput} from '@/types';

/** Error text of the backend 422 for an exception without any scope (kept identical). */
export const EMPTY_EXCEPTION_MESSAGE =
  'İstisna en az bir nesne alanı veya ifade deseni içermeli; kuralı tamamen kapatmak için kuralı pasifleştirin.';
export const MAX_REASON_LENGTH = 500;

export interface ExceptionScope {
  database?: string | null;
  schema?: string | null;
  object_name?: string | null;
}

const clean = (v: string | null | undefined) => (v ?? '').trim();

export function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Suggests a short, whitespace-tolerant regex from a finding snippet: the first identifiers with the punctuation
 * between them, e.g. "OPTION (MIN_GRANT_PERCENT = 5, MAX_GRANT_PERCENT = 20)" → "OPTION\s*\(\s*MIN_GRANT_PERCENT".
 */
export function suggestSnippetPattern(snippet: string | null | undefined): string {
  const text = clean(snippet).replace(/\s+/g, ' ');
  if (!text) return '';
  const tokens = text.match(/[A-Za-z_@#$À-ɏ][\w@#$À-ɏ]*|\d+|\S/g) ?? [];
  const picked: string[] = [];
  let words = 0;
  for (const t of tokens) {
    picked.push(t);
    if (/^[A-Za-z_@#$À-ɏ]/.test(t)) {
      words++;
      // Two identifiers are usually enough; a very short pair (e.g. "A.B") takes a third one.
      if ((words >= 2 && picked.join('').length >= 10) || words >= 3) break;
    }
    if (picked.length >= 8) break;
  }
  let out = '';
  picked.forEach((t, i) => {
    if (i > 0) {
      const prevWord = /\w$/.test(picked[i - 1]);
      const curWord = /^\w/.test(t);
      out += prevWord && curWord ? '\\s+' : '\\s*';
    }
    out += escapeRegex(t);
  });
  return out;
}

/** "EDWDM.dbo.vSales" — missing parts as "*"; "Tüm nesneler" when nothing is set. */
export function exceptionScopeLabel(scope: ExceptionScope): string {
  const db = clean(scope.database);
  const schema = clean(scope.schema);
  const name = clean(scope.object_name);
  if (!db && !schema && !name) return 'Tüm nesneler';
  return `${db || '*'}.${schema || '*'}.${name || '*'}`;
}

/** Turkish preview sentence for the exception dialog. */
export function exceptionPreview(ruleCode: string, scope: ExceptionScope, pattern: string | null | undefined): string {
  const label = exceptionScopeLabel(scope);
  const p = clean(pattern);
  const where = label === 'Tüm nesneler' ? 'tüm nesnelerde' : `${label} nesnesinde`;
  const what = p ? `“${p}” içeren bulgular` : 'tüm bulgular';
  return `${ruleCode} kuralı için ${where} ${what} bundan sonraki analizlerde raporlanmayacak.`;
}

/** Client-side mirror of the backend validation; returns the first problem or null. */
export function validateException(input: RuleExceptionInput): string | null {
  const any = [input.database, input.schema, input.object_name, input.snippet_pattern].some((v) => clean(v));
  if (!any) return EMPTY_EXCEPTION_MESSAGE;
  if (!clean(input.reason)) return 'İstisna nedeni zorunludur.';
  if (clean(input.reason).length > MAX_REASON_LENGTH) return `İstisna nedeni en fazla ${MAX_REASON_LENGTH} karakter olabilir.`;
  return null;
}

/** Empty strings → null, everything trimmed. */
export function toExceptionPayload(input: RuleExceptionInput): RuleExceptionInput {
  const n = (v: string | null | undefined) => clean(v) || null;
  return {
    database: n(input.database),
    schema: n(input.schema),
    object_name: n(input.object_name),
    snippet_pattern: n(input.snippet_pattern),
    reason: clean(input.reason),
  };
}

export const sortExceptions = (list: RuleException[]) => [...list].sort((a, b) => b.id - a.id);
