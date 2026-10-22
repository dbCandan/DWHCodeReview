import type {
  ObjectSelection,
  SchedulePeriod,
  ScheduledReviewDetail,
  ScheduledReviewWrite,
  ScheduledRunItem,
} from '@/types/sqlReview';

/** Limits mirrored from the backend (sql-review scheduled-review-email Requirement 1, 2, 5). */
export const SCHEDULE_NAME_LIMIT = 120;
export const RECIPIENTS_LIMIT = 20;
export const MONTH_DAY_LIMIT = 28;
export const TIMEZONES = ['Europe/Istanbul', 'UTC', 'Europe/London', 'Europe/Berlin'];
export const WEEKDAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar'];

export type Frequency = SchedulePeriod['frequency'];

export interface ScheduleForm {
  name: string;
  mode: 'filter' | 'list';
  database: string;
  query: string;
  typeCode: string;
  fromDate: string;
  items: ObjectSelection[];
  ruleGroupIds: string[];
  frequency: Frequency;
  time: string;
  timezone: string;
  weekday: number;
  dayOfMonth: number;
  recipients: string;
}

export type FormProblems = Partial<Record<'name' | 'selection' | 'time' | 'recipients', string>>;

export function emptyForm(): ScheduleForm {
  return {
    name: '',
    mode: 'filter',
    database: '',
    query: '',
    typeCode: '',
    fromDate: '',
    items: [],
    ruleGroupIds: [],
    frequency: 'daily',
    time: '07:00',
    timezone: 'Europe/Istanbul',
    weekday: 0,
    dayOfMonth: 1,
    recipients: '',
  };
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

export function formOf(detail: ScheduledReviewDetail): ScheduleForm {
  const {selection, period} = detail;
  return {
    name: detail.name,
    mode: selection.mode ?? 'filter',
    database: selection.filter?.database ?? '',
    query: selection.filter?.query ?? '',
    typeCode: selection.filter?.type_code ?? '',
    fromDate: selection.filter?.from_date ?? '',
    items: selection.items ?? [],
    ruleGroupIds: detail.rule_groups.map((group) => group.id),
    frequency: period.frequency,
    time: `${pad(period.hour)}:${pad(period.minute)}`,
    timezone: period.timezone ?? 'Europe/Istanbul',
    weekday: period.weekday ?? 0,
    dayOfMonth: period.day_of_month ?? 1,
    recipients: detail.recipients.join('\n'),
  };
}

/** Addresses separated by new lines, commas, semicolons or spaces, without empty entries. */
export function parseRecipients(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((address) => address.trim())
    .filter(Boolean);
}

const ADDRESS = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** What the form can tell before sending; the server checks the allowed domains. */
export function formProblems(form: ScheduleForm): FormProblems {
  const problems: FormProblems = {};
  const name = form.name.trim();
  if (!name || name.length > SCHEDULE_NAME_LIMIT) problems.name = `Ad 1-${SCHEDULE_NAME_LIMIT} karakter olmalıdır.`;
  if (form.mode === 'filter' && !form.database) problems.selection = 'Bir veritabanı seçin.';
  if (form.mode === 'list' && form.items.length === 0) problems.selection = 'Listeden en az bir nesne seçin.';
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(form.time)) problems.time = 'Saat SS:DD biçiminde olmalıdır.';
  const recipients = parseRecipients(form.recipients);
  if (recipients.length === 0) problems.recipients = 'En az bir alıcı girin.';
  else if (recipients.length > RECIPIENTS_LIMIT) problems.recipients = `En çok ${RECIPIENTS_LIMIT} alıcı girilebilir.`;
  else if (!recipients.every((address) => ADDRESS.test(address)))
    problems.recipients = 'Alıcı e-posta adreslerinden biri geçersiz.';
  return problems;
}

export function toWrite(form: ScheduleForm): ScheduledReviewWrite {
  const [hour, minute] = form.time.split(':').map(Number);
  return {
    name: form.name.trim(),
    selection:
      form.mode === 'filter'
        ? {
            mode: 'filter',
            filter: {
              database: form.database,
              query: form.query.trim() || null,
              type_code: form.typeCode || null,
              from_date: form.fromDate || null,
            },
            items: [],
          }
        : {mode: 'list', filter: null, items: form.items},
    rule_group_ids: form.ruleGroupIds,
    period: {
      frequency: form.frequency,
      hour,
      minute,
      timezone: form.timezone,
      weekday: form.frequency === 'weekly' ? form.weekday : null,
      day_of_month: form.frequency === 'monthly' ? form.dayOfMonth : null,
    },
    recipients: parseRecipients(form.recipients),
  };
}

export function periodLabel(period: SchedulePeriod): string {
  const time = `${pad(period.hour)}:${pad(period.minute)}`;
  const zone = period.timezone ?? 'Europe/Istanbul';
  if (period.frequency === 'weekly') return `Her ${WEEKDAYS[period.weekday ?? 0].toLocaleLowerCase('tr')} ${time} (${zone})`;
  if (period.frequency === 'monthly') return `Her ayın ${period.day_of_month}. günü ${time} (${zone})`;
  return `Her gün ${time} (${zone})`;
}

export const STATE_LABELS: Record<ScheduledRunItem['state'], string> = {
  queued: 'Sırada',
  running: 'Sürüyor',
  completed: 'Tamamlandı',
  failed: 'Hata',
  cancelled: 'Durduruldu',
  interrupted: 'Yarıda kesildi',
  missed: 'Kaçırıldı',
  skipped: 'Atlandı',
};

export const TRIGGER_LABELS: Record<ScheduledRunItem['trigger'], string> = {
  scheduled: 'Periyot',
  manual: 'Elle tetiklendi',
  missed: 'Kaçırıldı',
};

export const SKIP_REASON_LABELS: Record<NonNullable<ScheduledRunItem['skip_reason']>, string> = {
  previous_running: 'önceki koşum sürüyor',
  no_published_rule_set: 'yayımlanmış kural yok',
  no_objects: 'seçimle eşleşen nesne yok',
};

export const EMAIL_LABELS: Record<NonNullable<ScheduledRunItem['email_status']>, string> = {
  pending: 'Gönderilecek',
  sent: 'Gönderildi',
  failed: 'E-posta gönderilemedi',
  not_configured: 'E-posta yapılandırılmadı',
};

export function stateText(run: Pick<ScheduledRunItem, 'state' | 'skip_reason'>): string {
  const label = STATE_LABELS[run.state];
  return run.skip_reason ? `${label} (${SKIP_REASON_LABELS[run.skip_reason]})` : label;
}

/** What a failed summary or test e-mail means for the operations team (Requirement 10). */
export const SMTP_FAILURE_TEXT: Record<string, string> = {
  smtp_unreachable:
    'SMTP sunucusuna bağlanılamadı. Sunucu adresini ve portunu, ağ çıkış iznini (egress) kontrol edin.',
  smtp_tls_failed:
    'TLS kurulamadı: sunucu STARTTLS sunmuyor ya da sertifikası kurum CA ile doğrulanamadı.',
  smtp_auth_failed: 'SMTP kullanıcı adı veya parolası reddedildi.',
  smtp_rejected: 'SMTP sunucusu göndereni veya alıcıyı reddetti.',
  smtp_address_not_allowed: 'SMTP sunucu adresi kurum içi (özel) bir adrese çözülmüyor.',
  smtp_failed: 'SMTP sunucusu beklenmeyen bir hata döndürdü.',
};

export function smtpFailureText(code: string | null | undefined): string {
  return (code && SMTP_FAILURE_TEXT[code]) || 'E-posta gönderilemedi.';
}
