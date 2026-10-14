import {describe, expect, it} from 'vitest';
import {RULE_SUMMARY_LIMIT, displaySummary, ruleMatchesSearch, summaryProblem} from './rules';

const rule = (text: string, summary = '') => ({id: 'Kural01', text, summary, requires_metadata: false});

describe('rule summaries (rule-management Requirement 12, Decision 5)', () => {
  it('shows the given summary', () => {
    expect(displaySummary(rule('Uzun metin. İkinci cümle.', '  Kısa özet.  '))).toBe('Kısa özet.');
  });

  it('falls back to the first sentence of the text', () => {
    expect(displaySummary(rule('  NOLOCK kullanılmamalıdır. Çünkü kirli okuma yapar.'))).toBe(
      'NOLOCK kullanılmamalıdır.',
    );
    expect(displaySummary(rule('Soru mu? Evet.'))).toBe('Soru mu?');
    // A dot inside a word or a number does not end the sentence.
    expect(displaySummary(rule('dbo.Tablo kullanımı 1.5 kat yavaştır. Sonra.'))).toBe(
      'dbo.Tablo kullanımı 1.5 kat yavaştır.',
    );
  });

  it('starts at the AÇIKLAMA section of a structured rule text', () => {
    const text = 'KURAL ADI:\nTEMP_TABLE_NOLOCK_USAGE\n\nAÇIKLAMA:\nTemp tablolar NOLOCK ile kullanılamaz.\n\nKURAL MANTIĞI:\nİki koşul.';
    expect(displaySummary(rule(text))).toBe('Temp tablolar NOLOCK ile kullanılamaz.');
    expect(displaySummary(rule('KURAL ADI: X\n\nAçıklama: Kısa. Uzun.'))).toBe('Kısa.');
  });

  it('uses the first line, at most 200 characters, when no sentence ends', () => {
    expect(displaySummary(rule('Başlık satırı\nikinci satır'))).toBe('Başlık satırı');
    const long = displaySummary(rule('x'.repeat(300)));
    expect(long.length).toBe(RULE_SUMMARY_LIMIT);
    expect(long.endsWith('…')).toBe(true);
  });

  it('reports a summary the server would reject', () => {
    expect(summaryProblem('Tek cümle.')).toBeNull();
    expect(summaryProblem('x'.repeat(201))).toBe('Kural özeti en çok 200 karakter olabilir.');
    expect(summaryProblem('iki\nsatır')).toBe('Kural özeti tek satır olmalıdır.');
  });

  it('searches the summary as well', () => {
    expect(ruleMatchesSearch(rule('metin', 'Geçici tablolar'), 'geçici')).toBe(true);
  });
});
