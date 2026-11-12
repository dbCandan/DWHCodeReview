// Mirrors app/API_CONTRACT.md (v1 + v1.1 kural motoru + v1.4 istisnalar). Keep in sync with the backend contract.

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';
export type RuleKind = 'regex' | 'llm' | 'builtin';
/** Built-in, catalog-metadata aware deterministic checks implemented in the backend. */
export type BuiltinCheck =
  | 'nolock_physical_tables'
  | 'derived_view_consistency'
  | 'left_then_inner_join'
  | 'select_list_subquery'
  | 'tablock_physical_insert'
  | 'join_column_type_mismatch'
  | 'non_sargable_predicates'
  | 'or_in_predicates'
  | 'scalar_udf_in_query'
  | 'window_order_by_type'
  | 'date_variable_type_mismatch'
  | 'personnel_flag_view_source'
  | 'id_literal_filter'
  | 'calendar_date_predicate';
/** Catalog-based precondition: when not satisfied the rule is skipped for that object (no LLM call). */
export type MetadataPrecondition = 'references_scd_table' | 'references_partitioned_table';
export type MatchMode = 'match' | 'absent';
export type RuleTarget = 'definition' | 'name';
export type ObjectType = 'PROCEDURE' | 'VIEW' | 'FUNCTION_SCALAR' | 'FUNCTION_INLINE' | 'FUNCTION_TABLE';
export type SeverityCounts = Record<Severity, number>;

export interface Rule {
  id: number;
  code: string;
  name: string;
  description: string;
  recommendation: string;
  severity: Severity;
  kind: RuleKind;
  pattern: string | null;
  match_mode: MatchMode;
  target: RuleTarget;
  ignore_case: boolean;
  ignore_comments: boolean;
  llm_prompt: string | null;
  object_types: ObjectType[];
  enabled: boolean;
  group_ids: number[];
  /** v1.1 — required when kind = "builtin". */
  builtin_check: BuiltinCheck | null;
  /** v1.1 — regex; objects whose definition does not match are not sent to the model. */
  precondition: string | null;
  metadata_precondition: MetadataPrecondition | null;
  /** v1.1 — adds the KATALOG METADATASI block to the LLM prompt. */
  requires_metadata: boolean;
  /** v1.1 — empty = all databases (case-insensitive). */
  databases: string[];
  /** v1.1 — regex searched in "schema.name" (IGNORECASE). */
  name_pattern: string | null;
  /** v1.7 — live-tester sample stored with the rule (all optional; older backends omit them). */
  sample_sql?: string | null;
  sample_object_name?: string | null;
  sample_object_type?: ObjectType | null;
  sample_database?: string | null;
  /** v1.4 — number of exceptions (suppressions) defined for this rule. Read-only. */
  exception_count?: number;
  created_at: string;
  updated_at: string;
}
export type RuleInput = Omit<Rule, 'id' | 'created_at' | 'updated_at' | 'exception_count'>;

/** v1.4 — a suppression: matching findings of the rule are not recorded in later analyses. */
export interface RuleException {
  id: number;
  rule_id: number;
  rule_code: string;
  /** null = any (wildcard); comparisons are case-insensitive. */
  database: string | null;
  schema: string | null;
  object_name: string | null;
  /** Regex searched (IGNORECASE) in the finding's snippet + message. */
  snippet_pattern: string | null;
  reason: string;
  created_at: string;
}
export interface RuleExceptionInput {
  database?: string | null;
  schema?: string | null;
  object_name?: string | null;
  snippet_pattern?: string | null;
  reason: string;
}

export interface RuleGroup {
  id: number;
  name: string;
  description: string;
  color: string;
  rule_ids: number[];
  created_at: string;
  updated_at: string;
}
export interface RuleGroupInput {
  name: string;
  description: string;
  color: string;
  rule_ids: number[];
}

export interface Connection {
  id: number;
  name: string;
  server: string;
  port: number;
  username: string;
  has_password: boolean;
  encrypt: boolean;
  trust_server_certificate: boolean;
  created_at: string;
  updated_at: string;
}
export interface ConnectionInput {
  name: string;
  server: string;
  port: number;
  username: string;
  password?: string | null;
  encrypt: boolean;
  trust_server_certificate: boolean;
}
export interface ConnectionTestResult {
  ok: boolean;
  message: string;
  server_version: string | null;
  database_count: number | null;
}

export interface DbObject {
  database: string;
  schema: string;
  name: string;
  type: ObjectType;
  create_date: string;
  modify_date: string;
}
export interface SchemaInfo {
  database: string;
  schema: string;
  object_count: number;
}
export interface ObjectQuery {
  databases: string[];
  schemas?: string[];
  types?: ObjectType[];
  created_from?: string | null;
  created_to?: string | null;
  modified_from?: string | null;
  modified_to?: string | null;
  search?: string | null;
}
export interface ObjectQueryResult {
  items: DbObject[];
  total: number;
}

export interface LlmSettings {
  enabled: boolean;
  base_url: string;
  model: string;
  has_api_key: boolean;
  temperature: number;
  timeout_seconds: number;
  /** Lines per chunk when a large object is sent to the LLM in parts (v1.5). */
  chunk_lines?: number;
}
export interface LlmSettingsInput {
  enabled: boolean;
  base_url: string;
  model: string;
  api_key?: string | null;
  temperature: number;
  timeout_seconds: number;
  chunk_lines?: number;
}
export interface LlmModelList {
  models: string[];
  error: string | null;
}

export interface LlmTestResult {
  ok: boolean;
  message: string;
  latency_ms: number | null;
}

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface AnalysisSummary {
  id: number;
  name: string;
  connection_id: number | null;
  connection_name: string;
  status: RunStatus;
  object_count: number;
  rule_count: number;
  total_checks: number;
  completed_checks: number;
  finding_count: number;
  /** v1.4 — findings dropped because an exception matched. */
  suppressed_count?: number;
  /** v1.7 — set when the analysis was started by a scheduled analysis. */
  schedule_id?: number | null;
  schedule_name?: string | null;
  schedule_run_id?: number | null;
  severity_counts: SeverityCounts;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export type ObjectRunStatus = 'pending' | 'running' | 'done' | 'error';

export interface AnalysisObject {
  id: number;
  database: string;
  schema: string;
  name: string;
  type: ObjectType;
  create_date: string | null;
  modify_date: string | null;
  status: ObjectRunStatus;
  error: string | null;
  finding_count: number;
  /** v1.4 */
  suppressed_count?: number;
  line_count: number;
}

export interface AnalysisRuleRef {
  id: number | null;
  code: string;
  name: string;
  severity: Severity;
  kind: RuleKind;
}

export interface Finding {
  id: number;
  object_id: number;
  object_label: string;
  rule_code: string;
  rule_name: string;
  severity: Severity;
  kind: RuleKind;
  line: number | null;
  snippet: string;
  message: string;
  recommendation: string;
}

export interface AnalysisDetail extends AnalysisSummary {
  filters: Record<string, unknown>;
  rules: AnalysisRuleRef[];
  objects: AnalysisObject[];
}

export interface AnalysisCreate {
  name?: string;
  connection_id: number;
  objects: Pick<DbObject, 'database' | 'schema' | 'name' | 'type'>[];
  rule_ids?: number[];
  group_ids?: number[];
  filters?: Record<string, unknown>;
}

export interface ObjectSource {
  definition: string | null;
  findings: Finding[];
}

export interface RuleTestRequest {
  rule: RuleInput;
  sql: string;
  object_name?: string;
  object_type?: ObjectType;
  database?: string;
}
export interface RuleTestFinding {
  line: number;
  snippet: string;
  message: string;
}
export interface RuleTestResult {
  findings: RuleTestFinding[];
  error: string | null;
}

export interface TopRule {
  code: string;
  name: string;
  severity: Severity;
  count: number;
}
export interface Dashboard {
  rule_count: number;
  enabled_rule_count: number;
  group_count: number;
  connection_count: number;
  analysis_count: number;
  total_findings: number;
  severity_counts: SeverityCounts;
  recent_analyses: AnalysisSummary[];
  top_rules: TopRule[];
  /** v1.7 — nearest 5 enabled schedules */
  upcoming_schedules?: UpcomingSchedule[];
}

export interface Health {
  status: string;
  version: string;
}

// ---- v1.6 — LLM destekli kural asistanı ----
export type AssistantStatus = 'running' | 'ready' | 'failed' | 'saved' | 'cancelled';
export type AssistantStage = 'matching' | 'drafting' | 'validating' | 'refining' | 'noise' | 'done';

export interface AssistantExample {
  sql: string;
  note?: string | null;
  object_type?: ObjectType | null;
  object_name?: string | null;
  database?: string | null;
}

export interface AssistantNoiseRequest {
  connection_id: number;
  databases: string[];
  object_types?: ObjectType[];
  /** 10–200, default 50 */
  sample_size: number;
}

export interface AssistantRequest {
  /** 10–4000 characters */
  description: string;
  /** 1–10 */
  positive_examples: AssistantExample[];
  /** 0–10 */
  negative_examples?: AssistantExample[];
  preferred_kind?: RuleKind | null;
  severity_hint?: Severity | null;
  noise?: AssistantNoiseRequest | null;
}

export interface AssistantCaseResult {
  kind: 'positive' | 'negative';
  index: number;
  passed: boolean;
  findings: {line: number | null; snippet: string; message: string}[];
  error: string | null;
  /** extend: result of the current (old) rule on the same example */
  old_passed?: boolean | null;
}

export interface AssistantNoise {
  status: 'skipped' | 'running' | 'done' | 'failed';
  sampled: number;
  objects_with_findings: number;
  findings: number;
  old_findings?: number | null;
  examples: {object_label: string; line: number | null; snippet: string; message: string}[];
  llm_calls: number;
  duration_ms: number | null;
  note: string | null;
}

export interface AssistantValidation {
  iterations: number;
  passed: boolean;
  cases: AssistantCaseResult[];
}

export interface AssistantSession {
  id: number;
  status: AssistantStatus;
  stage: AssistantStage;
  log: {at: string; stage: AssistantStage; message: string}[];
  request: AssistantRequest;
  decision: 'extend' | 'new' | null;
  target_rule_id: number | null;
  target_rule_code: string | null;
  rationale: string | null;
  change_summary: string | null;
  builtin_needed: boolean;
  builtin_note: string | null;
  proposal: RuleInput | null;
  original: Rule | null;
  validation: AssistantValidation | null;
  noise: AssistantNoise | null;
  saved_rule_id: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssistantSaveResult {
  rule: Rule;
  session: AssistantSession;
}

// ---- v1.7 — Zamanlanmış analizler ----
export interface ObjectQueryFilter {
  schemas: string[];
  types: ObjectType[];
  created_from?: string | null;
  created_to?: string | null;
  modified_from?: string | null;
  modified_to?: string | null;
  search?: string | null;
}
export type RuleSelectionMode = 'all_enabled' | 'groups' | 'rules';
export interface RuleSelection {
  mode: RuleSelectionMode;
  group_ids: number[];
  rule_ids: number[];
}
export type ScheduleKind = 'daily' | 'weekly' | 'monthly' | 'interval';
export interface ScheduleSpec {
  kind: ScheduleKind;
  /** "HH:MM", local time of the server machine */
  time: string;
  /** 1 = Pzt … 7 = Paz */
  weekdays: number[];
  /** 1–31; months without that day run on the last day */
  month_day: number;
  /** 1–168 */
  interval_hours: number;
}
export type ScheduledRunStatus = 'running' | 'completed' | 'skipped' | 'failed';
export interface ScheduledRun {
  id: number;
  schedule_id: number;
  trigger: 'schedule' | 'manual' | 'catch_up';
  status: ScheduledRunStatus;
  reason: string | null;
  analysis_id: number | null;
  started_at: string;
  finished_at: string | null;
  object_count: number;
  changed_object_count: number;
  finding_count: number;
  new_count: number;
  resolved_count: number;
  unchanged_count: number;
}
export interface ScheduledAnalysis {
  id: number;
  name: string;
  description: string;
  enabled: boolean;
  connection_id: number;
  connection_name: string;
  scope: {databases: string[]; queries: ObjectQueryFilter[]};
  rule_selection: RuleSelection;
  schedule: ScheduleSpec;
  incremental: boolean;
  first_run_full: boolean;
  schedule_text: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run: ScheduledRun | null;
  watermark_at: string | null;
  created_at: string;
  updated_at: string;
}
export type ScheduledAnalysisInput = Omit<
  ScheduledAnalysis,
  'id' | 'connection_name' | 'schedule_text' | 'next_run_at' | 'last_run_at' | 'last_run' | 'watermark_at' | 'created_at' | 'updated_at'
>;
export interface RunDiffFinding {
  object_label: string;
  rule_code: string;
  rule_name: string;
  severity: Severity;
  line: number | null;
  snippet: string;
  message: string;
  finding_id: number | null;
}
export interface RunDiff {
  new: RunDiffFinding[];
  resolved: RunDiffFinding[];
  compared_objects: number;
}
export interface SchedulePreview {
  object_count: number;
  changed_count: number | null;
  rule_count: number;
  llm_rule_count: number;
  estimated_checks: number;
  estimated_llm_checks: number;
  next_runs: string[];
}
export interface UpcomingSchedule {
  id: number;
  name: string;
  next_run_at: string | null;
  schedule_text: string;
}
