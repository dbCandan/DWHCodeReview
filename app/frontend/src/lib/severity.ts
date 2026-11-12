import type {Severity, SeverityCounts} from '@/types';

export const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low', 'info'];

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: 'Kritik',
  high: 'Yüksek',
  medium: 'Orta',
  low: 'Düşük',
  info: 'Bilgi',
};

export const SEVERITY_RANK: Record<Severity, number> = {critical: 5, high: 4, medium: 3, low: 2, info: 1};

/** CSS variable of each severity color; usable in SVG fills and inline styles. */
export const SEVERITY_VAR: Record<Severity, string> = {
  critical: 'var(--color-sev-critical)',
  high: 'var(--color-sev-high)',
  medium: 'var(--color-sev-medium)',
  low: 'var(--color-sev-low)',
  info: 'var(--color-sev-info)',
};

/** Text-safe variant of each severity color (meets contrast on surfaces). */
export const SEVERITY_FG_VAR: Record<Severity, string> = {
  critical: 'var(--color-sev-critical-fg)',
  high: 'var(--color-sev-high-fg)',
  medium: 'var(--color-sev-medium-fg)',
  low: 'var(--color-sev-low-fg)',
  info: 'var(--color-sev-info-fg)',
};

/** Tailwind class bundles so every severity looks the same everywhere. */
export const SEVERITY_CLASS: Record<Severity, {text: string; bg: string; soft: string; ring: string; border: string}> = {
  critical: {
    text: 'text-sev-critical-fg',
    bg: 'bg-sev-critical',
    soft: 'bg-sev-critical/12',
    ring: 'ring-sev-critical/30',
    border: 'border-sev-critical',
  },
  high: {text: 'text-sev-high-fg', bg: 'bg-sev-high', soft: 'bg-sev-high/12', ring: 'ring-sev-high/30', border: 'border-sev-high'},
  medium: {
    text: 'text-sev-medium-fg',
    bg: 'bg-sev-medium',
    soft: 'bg-sev-medium/12',
    ring: 'ring-sev-medium/30',
    border: 'border-sev-medium',
  },
  low: {text: 'text-sev-low-fg', bg: 'bg-sev-low', soft: 'bg-sev-low/12', ring: 'ring-sev-low/30', border: 'border-sev-low'},
  info: {text: 'text-sev-info-fg', bg: 'bg-sev-info', soft: 'bg-sev-info/12', ring: 'ring-sev-info/30', border: 'border-sev-info'},
};

export function emptyCounts(): SeverityCounts {
  return {critical: 0, high: 0, medium: 0, low: 0, info: 0};
}

/** Normalizes a possibly partial counts object (all five keys present). */
export function normalizeCounts(counts: Partial<SeverityCounts> | null | undefined): SeverityCounts {
  const result = emptyCounts();
  if (counts) for (const s of SEVERITIES) result[s] = Number(counts[s] ?? 0) || 0;
  return result;
}

/** Counts items by their `severity` field. */
export function countBySeverity(items: {severity: Severity}[]): SeverityCounts {
  const result = emptyCounts();
  for (const item of items) if (item.severity in result) result[item.severity] += 1;
  return result;
}

/** Adds several severity count objects together. */
export function sumCounts(list: (Partial<SeverityCounts> | null | undefined)[]): SeverityCounts {
  const result = emptyCounts();
  for (const counts of list) {
    const n = normalizeCounts(counts);
    for (const s of SEVERITIES) result[s] += n[s];
  }
  return result;
}

export function totalCount(counts: Partial<SeverityCounts> | null | undefined): number {
  const n = normalizeCounts(counts);
  return SEVERITIES.reduce((sum, s) => sum + n[s], 0);
}

/** Highest severity that has at least one item, or null. */
export function topSeverity(counts: Partial<SeverityCounts> | null | undefined): Severity | null {
  const n = normalizeCounts(counts);
  return SEVERITIES.find((s) => n[s] > 0) ?? null;
}

export function compareSeverity(a: Severity, b: Severity): number {
  return SEVERITY_RANK[b] - SEVERITY_RANK[a];
}
