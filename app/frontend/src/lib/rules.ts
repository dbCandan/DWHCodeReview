import type {BuiltinCheck, DbObject, MetadataPrecondition, ObjectType, RuleKind} from '@/types';
import {formatDuration} from './format';

export const RULE_KIND_LABEL: Record<RuleKind, string> = {
  regex: 'Regex',
  llm: 'LLM',
  builtin: 'Yerleşik',
};

export const RULE_KIND_HINT: Record<RuleKind, string> = {
  regex: 'Desen eşleşmesi, anında sonuç',
  llm: 'Model kuralı okur ve kodu yorumlar; yavaş',
  builtin: 'Sistemde tanımlı, katalog metadatası kullanan hazır kontrol',
};

export const BUILTIN_CHECK_LABEL: Record<BuiltinCheck, string> = {
  nolock_physical_tables: 'Fiziksel tablolarda NOLOCK zorunluluğu',
  derived_view_consistency: 'Türev view ↔ asıl view uyumu',
  left_then_inner_join: 'LEFT JOIN sonrası INNER JOIN',
  select_list_subquery: 'SELECT listesinde alt sorgu',
  tablock_physical_insert: 'Fiziksel tabloya INSERT WITH (TABLOCK)',
  join_column_type_mismatch: 'Join kolonlarında tip uyumu',
  non_sargable_predicates: 'Join/filtre kolonunda fonksiyon',
  or_in_predicates: 'JOIN/WHERE koşulunda OR',
  scalar_udf_in_query: 'Sorgu içinde scalar fonksiyon',
  window_order_by_type: 'Pencere fonksiyonu ORDER BY tipi',
  date_variable_type_mismatch: 'Tarih değişkeni ↔ alan tip uyumu',
  personnel_flag_view_source: 'Asıl view’da PersonnelFlag kaynağı',
  id_literal_filter: 'Id alanında sabit değer filtresi (katalog)',
  calendar_date_predicate: 'Tarih kolonu dönüşümü → Calendar önerisi',
};

export const BUILTIN_CHECK_DETAIL: Record<BuiltinCheck, string> = {
  nolock_physical_tables:
    'FROM/JOIN ile okunan ve katalogda kullanıcı tablosu (U) olan her referansta WITH (NOLOCK) arar. #temp, @tablo değişkeni, CTE ve UPDATE/DELETE hedefleri hariçtir.',
  derived_view_consistency:
    'Masked / PersonnelExcluded / PersonnelMasked türev view’ını asıl view ile karşılaştırır: asıl view’dan okuma, kolon adı/sırası/tipi ve PersonnelFlag filtresi. NULL ile maskelenen kolonların tip farkı yok sayılır.',
  left_then_inner_join:
    'Her FROM bloğunda join sırasını okur; bir LEFT JOIN’den sonra gelen INNER JOIN’leri raporlar. Alt sorgu ve CTE’ler ayrı blok sayılır.',
  select_list_subquery:
    'SELECT ile FROM arasındaki kolon listesinde (SELECT …) veya EXISTS (SELECT …) alt sorgularını bulur.',
  tablock_physical_insert:
    'Katalogda kullanıcı tablosu (U) olan INSERT hedeflerinde WITH (TABLOCK) arar. #temp ve @tablo değişkenleri hariçtir.',
  join_column_type_mismatch:
    'ON koşulundaki eşitliklerde iki tarafın kolon tipini katalogdan çözer; tip aileleri (int, varchar, nvarchar, date, datetime…) farklıysa raporlar.',
  non_sargable_predicates:
    'ON ve WHERE koşullarında kolonun CAST/CONVERT veya fonksiyon (YEAR, ISNULL, LTRIM…) içine alındığı karşılaştırmaları raporlar.',
  or_in_predicates:
    'JOIN koşullarındaki her OR’u ve WHERE’de farklı kolonları bağlayan OR’ları (@p IS NULL OR … dahil) raporlar.',
  scalar_udf_in_query:
    'Katalogda scalar fonksiyon (FN) olan nesnelerin SELECT/WHERE/JOIN içindeki çağrılarını raporlar; değişkene atamalar hariçtir.',
  window_order_by_type:
    'ROW_NUMBER/RANK/DENSE_RANK/NTILE ORDER BY ifadelerinde sabit veya metin tipli (katalogdan çözülen) alanları raporlar.',
  date_variable_type_mismatch:
    'Tarih parametre/değişkenlerinin tipini (DECLARE ve parametreler) karşılaştırıldığı kolonun katalog tipiyle kıyaslar (date ↔ datetime, date ↔ int …).',
  personnel_flag_view_source:
    'Personnel* türevi olan EDWDM asıl view’larında PersonnelFlag’in varlığını ve kaynağını (EDWDM tablosu ↔ EDWUTIL.DTG LKP tabloları) denetler.',
  id_literal_filter:
    'ON/WHERE içinde …Id kolonlarının sabit değerle karşılaştırılmasını arar. Yalnız katalogda kullanıcı tablosundan gelen ve aynı tabloda <Ad>Nk karşılığı olan vekil anahtarlar raporlanır; view kaynakları ve -98/-99/-1 gibi standart değerler hariçtir.',
  calendar_date_predicate:
    'WHERE/ON içinde CONVERT/CAST/FORMAT/YEAR/MONTH gibi dönüşümlerle sarılmış tarih kolonlarını bulur ve EDW.COR.Calendar ile aralık join’i önerir. DECLARE/SET ve SELECT listesi kapsam dışıdır.',
};

export const METADATA_PRECONDITION_LABEL: Record<MetadataPrecondition, string> = {
  references_scd_table: 'SCD tablo okuyan nesneler',
  references_partitioned_table: 'Partition’lı tablo kullanan nesneler',
};

/** Average wall time of one LLM check (object × rule) used for estimates. */
export const LLM_SECONDS_PER_CHECK = 45;

export function builtinLabel(check: string | null | undefined): string {
  if (!check) return 'Tanımsız kontrol';
  return BUILTIN_CHECK_LABEL[check as BuiltinCheck] ?? check;
}

/** Scope fields with safe defaults: an older backend may not send the v1.1 fields yet. */
export interface RuleScope {
  object_types?: ObjectType[] | null;
  databases?: string[] | null;
  name_pattern?: string | null;
}

const scopeOf = (r: RuleScope) => ({
  types: r.object_types ?? [],
  dbs: (r.databases ?? []).map((d) => d.trim()).filter(Boolean),
  pattern: (r.name_pattern ?? '').trim(),
});

function joinTr(items: string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} ve ${items[items.length - 1]}`;
}

/** One-line Turkish sentence, e.g. "EDWDM veritabanındaki, adı “^[^.]+\.v” desenine uyan VIEW nesnelerine uygulanır." */
export function scopeSummary(rule: RuleScope): string {
  const {types, dbs, pattern} = scopeOf(rule);
  const dbPart = dbs.length === 0 ? 'Tüm veritabanlarındaki' : dbs.length === 1 ? `${dbs[0]} veritabanındaki` : `${joinTr(dbs)} veritabanlarındaki`;
  const typePart = types.length === 0 ? 'tüm nesnelere' : `${joinTr(types)} nesnelerine`;
  const namePart = pattern ? `, adı “${pattern}” desenine uyan` : '';
  return `${dbPart}${namePart} ${typePart} uygulanır.`;
}

/** Compact scope label for tables, e.g. "VIEW · EDWDM · ad deseni"; "Tümü" when unrestricted. */
export function scopeShort(rule: RuleScope): string {
  const {types, dbs, pattern} = scopeOf(rule);
  const parts: string[] = [];
  if (types.length) parts.push(types.length > 2 ? `${types.length} tip` : types.join(', '));
  if (dbs.length) parts.push(dbs.length > 2 ? `${dbs.length} DB` : dbs.join(', '));
  if (pattern) parts.push('ad deseni');
  return parts.length ? parts.join(' · ') : 'Tümü';
}

function compileNamePattern(pattern: string): RegExp | null {
  try {
    return new RegExp(toJsRegexSource(pattern), 'i');
  } catch {
    return null;
  }
}

/** Mirrors the backend applicability test: object_types AND databases AND name_pattern ("schema.name"). */
export function ruleApplies(rule: RuleScope, obj: Pick<DbObject, 'type'> & Partial<Pick<DbObject, 'database' | 'schema' | 'name'>>, compiled?: RegExp | null): boolean {
  const {types, dbs, pattern} = scopeOf(rule);
  if (types.length && !types.includes(obj.type)) return false;
  if (dbs.length && obj.database !== undefined && !dbs.some((d) => d.toLowerCase() === obj.database!.toLowerCase())) return false;
  if (pattern && obj.name !== undefined) {
    // An unparseable pattern (JS vs .NET/Python differences) counts as "applies" — the estimate stays an upper bound.
    const re = compiled === undefined ? compileNamePattern(pattern) : compiled;
    if (re && !re.test(`${obj.schema ?? ''}.${obj.name}`)) return false;
  }
  return true;
}

export interface CheckEstimate {
  /** Regex + built-in checks: deterministic, practically instant. */
  instant: number;
  /** LLM checks (upper bound — precondition / metadata precondition may skip many). */
  llm: number;
  total: number;
  /** Upper bound for LLM wall time in milliseconds. */
  llmMaxMs: number;
}

type ObjLike = Pick<DbObject, 'type'> & Partial<Pick<DbObject, 'database' | 'schema' | 'name'>>;

export function estimateCheckSplit(objects: ObjLike[], rules: (RuleScope & {kind: RuleKind})[]): CheckEstimate {
  let instant = 0;
  let llm = 0;
  for (const r of rules) {
    const pattern = (r.name_pattern ?? '').trim();
    const compiled = pattern ? compileNamePattern(pattern) : null;
    let n = 0;
    for (const o of objects) if (ruleApplies(r, o, compiled)) n++;
    if (r.kind === 'llm') llm += n;
    else instant += n;
  }
  return {instant, llm, total: instant + llm, llmMaxMs: llm * LLM_SECONDS_PER_CHECK * 1000};
}

export function formatLlmEstimate(ms: number): string {
  if (ms <= 0) return '—';
  return `en fazla ~${formatDuration(ms)}`;
}

/**
 * Best-effort conversion of Python/.NET regex syntax to JS so the client-side check gives fewer false warnings.
 * The backend stays authoritative.
 */
export function toJsRegexSource(pattern: string): string {
  return pattern
    .replace(/^\(\?[aiLmsux]+\)/, '') // leading inline flags (?i) (?s) …
    .replace(/\(\?P<(\w+)>/g, '(?<$1>')
    .replace(/\(\?P=(\w+)\)/g, '\\k<$1>')
    .replace(/\\A/g, '^')
    .replace(/\\Z/g, '$');
}

/** Returns a warning when the pattern does not compile as a JS regex (never blocks saving). */
export function regexWarning(pattern: string | null | undefined): string | null {
  const p = (pattern ?? '').trim();
  if (!p) return null;
  try {
    new RegExp(toJsRegexSource(p), 'u');
    return null;
  } catch {
    try {
      new RegExp(toJsRegexSource(p));
      return null;
    } catch (e) {
      const msg = e instanceof Error ? e.message.replace(/^Invalid regular expression:\s*/, '') : String(e);
      return `Tarayıcı bu deseni derleyemedi (${msg}). .NET/Python sözdizimi farklı olabilir; kaydederken sunucu doğrular.`;
    }
  }
}

/** Notes the test endpoint returns for catalog-dependent rules are informational, not failures. */
export function isInfoNote(error: string | null | undefined): boolean {
  return !!error && /metadata|katalog|analiz çalıştır/i.test(error);
}
