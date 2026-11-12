export {clsx as cn} from 'clsx';

export function safeStorageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function safeStorageSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

export const GROUP_COLORS = [
  '#7c8cff',
  '#a78bfa',
  '#f472b6',
  '#fb7185',
  '#fb923c',
  '#fbbf24',
  '#a3e635',
  '#34d399',
  '#2dd4bf',
  '#38bdf8',
  '#94a3b8',
];

export const RULE_CODE_PATTERN = /^[A-Z][A-Z0-9_-]{1,31}$/;

/** "#RRGGBB" + alpha → rgba() string for tinted backgrounds. */
export function hexAlpha(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return `rgba(124, 140, 255, ${alpha})`;
  const v = parseInt(m[1], 16);
  return `rgba(${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}, ${alpha})`;
}

export function isMac(): boolean {
  return typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
}
