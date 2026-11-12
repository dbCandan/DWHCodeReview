import type {
  AssistantExample,
  AssistantRequest,
  AssistantSession,
  AssistantStage,
  ObjectType,
  Rule,
  RuleInput,
  RuleKind,
  Severity,
} from '@/types';
import {SEVERITY_LABEL} from './severity';
import {builtinLabel, METADATA_PRECONDITION_LABEL, RULE_KIND_LABEL} from './rules';

// ---------------------------------------------------------------------------------------------
// Field labels + diff (extend proposals)
// ---------------------------------------------------------------------------------------------

export const RULE_FIELD_LABEL: Partial<Record<keyof RuleInput, string>> = {
  code: 'Kod',
  name: 'Ad',
  severity: 'Önem',
  enabled: 'Durum',
  group_ids: 'Gruplar',
  kind: 'Tür',
  builtin_check: 'Yerleşik kontrol',
  pattern: 'Desen',
  match_mode: 'Eşleşme modu',
  target: 'Hedef',
  ignore_case: 'Büyük/küçük harf',
  ignore_comments: 'Yorumları yok say',
  llm_prompt: 'LLM talimatı',
  requires_metadata: 'Katalog metadatası',
  precondition: 'Ön koşul deseni',
  metadata_precondition: 'Katalog ön koşulu',
  object_types: 'Nesne tipleri',
  databases: 'Veritabanları',
  name_pattern: 'Ad deseni',
  description: 'Açıklama',
  recommendation: 'Öneri',
};

/** Field → previous value (display text). Only changed fields are present. */
export type FieldChanges = Partial<Record<keyof RuleInput, string>>;

type Comparable = string | number | boolean | null;

function normalize(key: keyof RuleInput, value: unknown): Comparable | string {
  if (value === undefined || value === null) return null;
  if (Array.isArray(value)) {
    const items = value.map((v) => (key === 'databases' ? String(v).trim().toUpperCase() : String(v)));
    return [...new Set(items)].sort().join('|') || null;
  }
  if (typeof value === 'string') return value.trim() || null;
  return value as Comparable;
}

export function formatFieldValue(key: keyof RuleInput, value: unknown, groupNames?: Map<number, string>): string {
  if (value === undefined || value === null || value === '') return '—';
  if (Array.isArray(value)) {
    if (!value.length) return key === 'databases' || key === 'object_types' ? 'Tümü' : '—';
    if (key === 'group_ids') return value.map((id) => groupNames?.get(Number(id)) ?? `#${id}`).join(', ');
    return value.join(', ');
  }
  if (typeof value === 'boolean') {
    if (key === 'enabled') return value ? 'Etkin' : 'Devre dışı';
    return value ? 'Evet' : 'Hayır';
  }
  if (key === 'severity') return SEVERITY_LABEL[value as Severity] ?? String(value);
  if (key === 'kind') return RULE_KIND_LABEL[value as RuleKind] ?? String(value);
  if (key === 'builtin_check') return builtinLabel(String(value));
  if (key === 'metadata_precondition') return METADATA_PRECONDITION_LABEL[value as keyof typeof METADATA_PRECONDITION_LABEL] ?? String(value);
  if (key === 'match_mode') return value === 'absent' ? 'Bulunmazsa bulgu' : 'Eşleşirse bulgu';
  if (key === 'target') return value === 'name' ? 'Nesne adı' : 'Tanım (SQL)';
  return String(value);
}

/** Fields whose value differs between the proposal and the original rule (extend). */
export function diffProposal(
  proposal: RuleInput | null | undefined,
  original: Rule | RuleInput | null | undefined,
  groupNames?: Map<number, string>,
): FieldChanges {
  const out: FieldChanges = {};
  if (!proposal || !original) return out;
  for (const key of Object.keys(RULE_FIELD_LABEL) as (keyof RuleInput)[]) {
    const before = (original as Record<string, unknown>)[key];
    const after = (proposal as unknown as Record<string, unknown>)[key];
    if (normalize(key, before) !== normalize(key, after)) out[key] = formatFieldValue(key, before, groupNames);
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// Stages / steps
// ---------------------------------------------------------------------------------------------

export type TimelineKey = 'matching' | 'drafting' | 'validating' | 'noise' | 'done';
export const TIMELINE: {key: TimelineKey; label: string}[] = [
  {key: 'matching', label: 'Eşleştirme'},
  {key: 'drafting', label: 'Taslak'},
  {key: 'validating', label: 'Doğrulama'},
  {key: 'noise', label: 'Gürültü testi'},
  {key: 'done', label: 'Hazır'},
];

export const STAGE_LABEL: Record<AssistantStage, string> = {
  matching: 'Eşleştirme',
  drafting: 'Taslak',
  validating: 'Doğrulama',
  refining: 'Düzeltme',
  noise: 'Gürültü testi',
  done: 'Hazır',
};

/** refining is shown on the validation step (validating ↔ refining loop). */
export function stageTimelineIndex(stage: AssistantStage): number {
  const key: TimelineKey = stage === 'refining' ? 'validating' : stage;
  return TIMELINE.findIndex((t) => t.key === key);
}

export type StepState = 'done' | 'active' | 'pending' | 'failed' | 'skipped';

export function timelineStates(session: Pick<AssistantSession, 'stage' | 'status' | 'request' | 'noise'>): StepState[] {
  const current = stageTimelineIndex(session.stage);
  const noiseSkipped = !session.request?.noise || session.noise?.status === 'skipped';
  return TIMELINE.map((t, i) => {
    if (t.key === 'noise' && noiseSkipped && (i < current || session.status !== 'running')) return 'skipped';
    if (session.status === 'ready' || session.status === 'saved') return 'done';
    if (i < current) return 'done';
    if (i === current) {
      if (session.status === 'failed') return 'failed';
      if (session.status === 'cancelled') return 'failed';
      return 'active';
    }
    return 'pending';
  });
}

/** Wizard step for a session: 0 definition · 1 running · 2 proposal & approval. */
export function wizardStep(session: Pick<AssistantSession, 'status' | 'proposal'> | null | undefined): 0 | 1 | 2 {
  if (!session) return 0;
  if (session.status === 'ready' || session.status === 'saved') return 2;
  return 1;
}

export const ASSISTANT_STATUS_LABEL: Record<AssistantSession['status'], string> = {
  running: 'Çalışıyor',
  ready: 'Onay bekliyor',
  failed: 'Başarısız',
  saved: 'Kaydedildi',
  cancelled: 'İptal edildi',
};

// ---------------------------------------------------------------------------------------------
// Definition form
// ---------------------------------------------------------------------------------------------

export interface ExampleDraft {
  sql: string;
  note: string;
}

export interface AssistantForm {
  description: string;
  positives: ExampleDraft[];
  negatives: ExampleDraft[];
  preferred_kind: RuleKind | '';
  severity_hint: Severity | '';
  noiseEnabled: boolean;
  connection_id: number | null;
  databases: string[];
  object_types: ObjectType[];
  sample_size: number;
}

export const SAMPLE_SIZES = [25, 50, 100, 200];
export const MAX_EXAMPLES = 10;
export const DESCRIPTION_MIN = 10;
export const DESCRIPTION_MAX = 4000;

export const emptyExample = (): ExampleDraft => ({sql: '', note: ''});

export function emptyAssistantForm(): AssistantForm {
  return {
    description: '',
    positives: [emptyExample()],
    negatives: [],
    preferred_kind: '',
    severity_hint: '',
    noiseEnabled: true,
    connection_id: null,
    databases: [],
    object_types: [],
    sample_size: 50,
  };
}

export interface AssistantFormErrors {
  description?: string;
  positives?: string;
  negatives?: string;
  noise?: string;
}

const filled = (list: ExampleDraft[]) => list.filter((e) => e.sql.trim());

export function validateAssistantForm(f: AssistantForm): AssistantFormErrors {
  const e: AssistantFormErrors = {};
  const d = f.description.trim();
  if (d.length < DESCRIPTION_MIN) e.description = `Açıklama en az ${DESCRIPTION_MIN} karakter olmalı.`;
  else if (d.length > DESCRIPTION_MAX) e.description = `Açıklama en fazla ${DESCRIPTION_MAX} karakter olabilir.`;
  const pos = filled(f.positives);
  if (pos.length < 1) e.positives = 'En az bir yakalanması gereken örnek girin.';
  else if (pos.length > MAX_EXAMPLES) e.positives = `En fazla ${MAX_EXAMPLES} örnek eklenebilir.`;
  if (filled(f.negatives).length > MAX_EXAMPLES) e.negatives = `En fazla ${MAX_EXAMPLES} örnek eklenebilir.`;
  if (f.noiseEnabled) {
    if (f.connection_id === null) e.noise = 'Gürültü testi için bir bağlantı seçin (veya testi kapatın).';
    else if (!f.databases.length) e.noise = 'Gürültü testi için en az bir veritabanı seçin.';
    else if (f.sample_size < 10 || f.sample_size > 200) e.noise = 'Örneklem 10–200 arasında olmalı.';
  }
  return e;
}

const toExample = (e: ExampleDraft): AssistantExample => ({sql: e.sql.replace(/\s+$/, ''), note: e.note.trim() || null});

export function buildAssistantRequest(f: AssistantForm): AssistantRequest {
  return {
    description: f.description.trim(),
    positive_examples: filled(f.positives).map(toExample),
    negative_examples: filled(f.negatives).map(toExample),
    preferred_kind: f.preferred_kind || null,
    severity_hint: f.severity_hint || null,
    noise:
      f.noiseEnabled && f.connection_id !== null
        ? {connection_id: f.connection_id, databases: f.databases, object_types: f.object_types, sample_size: f.sample_size}
        : null,
  };
}

/** Form state rebuilt from a past session's request ("Yeni oturum olarak düzenle"). */
export function formFromRequest(r: AssistantRequest | null | undefined): AssistantForm {
  const base = emptyAssistantForm();
  if (!r) return base;
  const ex = (list: AssistantExample[] | undefined) => (list ?? []).map((e) => ({sql: e.sql ?? '', note: e.note ?? ''}));
  return {
    ...base,
    description: r.description ?? '',
    positives: ex(r.positive_examples).length ? ex(r.positive_examples) : [emptyExample()],
    negatives: ex(r.negative_examples),
    preferred_kind: r.preferred_kind === 'builtin' ? '' : (r.preferred_kind ?? ''), // "Yerleşik" is not a user choice
    severity_hint: r.severity_hint ?? '',
    noiseEnabled: !!r.noise,
    connection_id: r.noise?.connection_id ?? null,
    databases: r.noise?.databases ?? [],
    object_types: r.noise?.object_types ?? [],
    sample_size: r.noise?.sample_size ?? 50,
  };
}

/** "+12" / "−3" / "±0" — change in findings between old and new rule on the noise sample. */
export function noiseDelta(findings: number, old: number | null | undefined): string | null {
  if (old === null || old === undefined) return null;
  const d = findings - old;
  return d > 0 ? `+${d}` : d < 0 ? `−${Math.abs(d)}` : '±0';
}
