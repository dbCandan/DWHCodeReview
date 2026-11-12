import type {ObjectRunStatus, ObjectType, RunStatus} from '@/types';

const LOCALE = 'tr-TR';

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

const dateFmt = new Intl.DateTimeFormat(LOCALE, {day: '2-digit', month: 'short', year: 'numeric'});
const dateTimeFmt = new Intl.DateTimeFormat(LOCALE, {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});
const timeFmt = new Intl.DateTimeFormat(LOCALE, {hour: '2-digit', minute: '2-digit', second: '2-digit'});
const numberFmt = new Intl.NumberFormat(LOCALE);
const relFmt = new Intl.RelativeTimeFormat(LOCALE, {numeric: 'auto'});

export function formatDate(value: string | null | undefined): string {
  const date = toDate(value);
  return date ? dateFmt.format(date) : '—';
}

export function formatDateTime(value: string | null | undefined): string {
  const date = toDate(value);
  return date ? dateTimeFmt.format(date) : '—';
}

export function formatTime(value: string | null | undefined): string {
  const date = toDate(value);
  return date ? timeFmt.format(date) : '—';
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? '—' : numberFmt.format(value);
}

export function formatPercent(part: number, whole: number): string {
  if (!whole) return '%0';
  return `%${Math.round((part / whole) * 100)}`;
}

/** "3 gün önce", "dün", "2 ay önce" … */
export function relativeTime(value: string | null | undefined, now: Date = new Date()): string {
  const date = toDate(value);
  if (!date) return '';
  const seconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return 'az önce';
  const table: [Intl.RelativeTimeFormatUnit, number][] = [
    ['minute', 60],
    ['hour', 3600],
    ['day', 86400],
    ['week', 604800],
    ['month', 2629800],
    ['year', 31557600],
  ];
  let unit: Intl.RelativeTimeFormatUnit = 'minute';
  let size = 60;
  for (const [u, s] of table) {
    if (abs >= s) {
      unit = u;
      size = s;
    }
  }
  return relFmt.format(Math.round(seconds / size), unit);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(totalSeconds < 10 ? 1 : 0).replace('.', ',')} sn`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  if (minutes < 60) return `${minutes} dk ${seconds} sn`;
  const hours = Math.floor(minutes / 60);
  return `${hours} sa ${minutes % 60} dk`;
}

export const OBJECT_TYPES: ObjectType[] = ['PROCEDURE', 'VIEW', 'FUNCTION_SCALAR', 'FUNCTION_INLINE', 'FUNCTION_TABLE'];

export const OBJECT_TYPE_LABEL: Record<ObjectType, string> = {
  PROCEDURE: 'Prosedür',
  VIEW: 'View',
  FUNCTION_SCALAR: 'Skaler fonksiyon',
  FUNCTION_INLINE: 'Satır içi TVF',
  FUNCTION_TABLE: 'Tablo fonksiyonu',
};

export const OBJECT_TYPE_SHORT: Record<ObjectType, string> = {
  PROCEDURE: 'SP',
  VIEW: 'VW',
  FUNCTION_SCALAR: 'FN',
  FUNCTION_INLINE: 'IF',
  FUNCTION_TABLE: 'TF',
};

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  queued: 'Sırada',
  running: 'Çalışıyor',
  completed: 'Tamamlandı',
  failed: 'Başarısız',
  cancelled: 'İptal edildi',
};

export const OBJECT_STATUS_LABEL: Record<ObjectRunStatus, string> = {
  pending: 'Bekliyor',
  running: 'İşleniyor',
  done: 'Tamamlandı',
  error: 'Hata',
};

export function isActiveStatus(status: RunStatus | undefined | null): boolean {
  return status === 'queued' || status === 'running';
}

/** Turkish-aware, accent-tolerant folding for client-side search. */
export function fold(value: string): string {
  return value
    .replace(/İ/g, 'i')
    .replace(/I/g, 'ı')
    .toLocaleLowerCase(LOCALE)
    .replace(/ı/g, 'i')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '');
}

export function matchesSearch(needle: string, ...haystack: (string | null | undefined)[]): boolean {
  const n = fold(needle.trim());
  if (!n) return true;
  return fold(haystack.filter(Boolean).join(' ')).includes(n);
}
