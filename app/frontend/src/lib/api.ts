import type {
  RunDiff,
  ScheduledAnalysis,
  ScheduledAnalysisInput,
  ScheduledRun,
  SchedulePreview,
  AssistantRequest,
  AssistantSaveResult,
  AssistantSession,
  AnalysisCreate,
  AnalysisDetail,
  AnalysisSummary,
  Connection,
  ConnectionInput,
  ConnectionTestResult,
  Dashboard,
  Finding,
  Health,
  LlmSettings,
  LlmSettingsInput,
  LlmModelList,
  LlmTestResult,
  ObjectQuery,
  ObjectQueryResult,
  ObjectSource,
  Rule,
  RuleGroup,
  RuleException,
  RuleExceptionInput,
  RuleGroupInput,
  RuleInput,
  RuleTestRequest,
  RuleTestResult,
  RunStatus,
  SchemaInfo,
} from '@/types';

export const API_BASE = '/api';

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export const UNREACHABLE_MESSAGE = 'Sunucuya ulaşılamadı. Backend (127.0.0.1:8000) çalışıyor mu?';

/** Turns any error body into a readable message; FastAPI validation lists are flattened. */
export function extractDetail(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as {detail: unknown}).detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as {msg: unknown}).msg) : String(d)))
        .filter(Boolean);
      if (parts.length) return parts.join(' · ');
    }
  }
  if (status >= 500) return UNREACHABLE_MESSAGE;
  return `İstek başarısız oldu (HTTP ${status}).`;
}

function qs(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers:
        body === undefined ? {Accept: 'application/json'} : {Accept: 'application/json', 'Content-Type': 'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(UNREACHABLE_MESSAGE, 0);
  }
  const text = response.status === 204 ? '' : await response.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = undefined;
    }
  }
  if (!response.ok) throw new ApiError(extractDetail(data, response.status), response.status);
  return data as T;
}

const get = <T>(path: string) => request<T>('GET', path);
const post = <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {});
const put = <T>(path: string, body: unknown) => request<T>('PUT', path, body);
const del = (path: string) => request<void>('DELETE', path);

export const api = {
  health: () => get<Health>('/health'),
  dashboard: () => get<Dashboard>('/dashboard'),

  rules: {
    list: (params: {q?: string; severity?: string; kind?: string; group_id?: number} = {}) =>
      get<Rule[]>(`/rules${qs(params)}`),
    get: (id: number) => get<Rule>(`/rules/${id}`),
    create: (input: RuleInput) => post<Rule>('/rules', input),
    update: (id: number, input: RuleInput) => put<Rule>(`/rules/${id}`, input),
    remove: (id: number) => del(`/rules/${id}`),
    duplicate: (id: number) => post<Rule>(`/rules/${id}/duplicate`),
    test: (body: RuleTestRequest) => post<RuleTestResult>('/rules/test', body),
  },

  schedules: {
    list: () => get<ScheduledAnalysis[]>('/scheduled-analyses'),
    get: (id: number) => get<ScheduledAnalysis>(`/scheduled-analyses/${id}`),
    create: (input: ScheduledAnalysisInput) => post<ScheduledAnalysis>('/scheduled-analyses', input),
    update: (id: number, input: ScheduledAnalysisInput) => put<ScheduledAnalysis>(`/scheduled-analyses/${id}`, input),
    remove: (id: number) => del(`/scheduled-analyses/${id}`),
    run: (id: number) => post<ScheduledRun>(`/scheduled-analyses/${id}/run`),
    runs: (id: number, limit = 50) => get<ScheduledRun[]>(`/scheduled-analyses/${id}/runs${qs({limit})}`),
    diff: (runId: number) => get<RunDiff>(`/scheduled-runs/${runId}/diff`),
    preview: (input: ScheduledAnalysisInput) => post<SchedulePreview>('/scheduled-analyses/preview', input),
  },

  assistant: {
    create: (body: AssistantRequest) => post<AssistantSession>('/rule-assistant/sessions', body),
    list: (limit = 20) => get<AssistantSession[]>(`/rule-assistant/sessions${qs({limit})}`),
    get: (id: number) => get<AssistantSession>(`/rule-assistant/sessions/${id}`),
    revalidate: (id: number, proposal: RuleInput, runNoise: boolean) =>
      post<AssistantSession>(`/rule-assistant/sessions/${id}/revalidate`, {proposal, run_noise: runNoise}),
    save: (id: number, proposal: RuleInput) => post<AssistantSaveResult>(`/rule-assistant/sessions/${id}/save`, {proposal}),
    cancel: (id: number) => post<AssistantSession>(`/rule-assistant/sessions/${id}/cancel`),
  },

  exceptions: {
    list: (ruleId?: number) => get<RuleException[]>(`/rule-exceptions${qs({rule_id: ruleId})}`),
    create: (ruleId: number, input: RuleExceptionInput) => post<RuleException>(`/rules/${ruleId}/exceptions`, input),
    remove: (id: number) => del(`/rule-exceptions/${id}`),
  },

  groups: {
    list: () => get<RuleGroup[]>('/rule-groups'),
    create: (input: RuleGroupInput) => post<RuleGroup>('/rule-groups', input),
    update: (id: number, input: RuleGroupInput) => put<RuleGroup>(`/rule-groups/${id}`, input),
    remove: (id: number) => del(`/rule-groups/${id}`),
  },

  connections: {
    list: () => get<Connection[]>('/connections'),
    create: (input: ConnectionInput) => post<Connection>('/connections', input),
    update: (id: number, input: ConnectionInput) => put<Connection>(`/connections/${id}`, input),
    remove: (id: number) => del(`/connections/${id}`),
    test: (input: ConnectionInput & {id?: number}) => post<ConnectionTestResult>('/connections/test', input),
    databases: (id: number) => get<string[]>(`/connections/${id}/databases`),
    schemas: (id: number, databases: string[]) =>
      get<SchemaInfo[]>(`/connections/${id}/schemas${qs({databases: databases.join(',')})}`),
    objects: (id: number, query: ObjectQuery) => post<ObjectQueryResult>(`/connections/${id}/objects`, query),
  },

  llm: {
    get: () => get<LlmSettings>('/settings/llm'),
    update: (input: LlmSettingsInput) => put<LlmSettings>('/settings/llm', input),
    test: (input: LlmSettingsInput) => post<LlmTestResult>('/settings/llm/test', input),
    models: (input: LlmSettingsInput) => post<LlmModelList>('/settings/llm/models', input),
  },

  analyses: {
    list: (status?: RunStatus) => get<AnalysisSummary[]>(`/analyses${qs({status})}`),
    get: (id: number) => get<AnalysisDetail>(`/analyses/${id}`),
    create: (body: AnalysisCreate) => post<AnalysisSummary>('/analyses', body),
    findings: (id: number, params: {severity?: string; rule_code?: string; object_id?: number; q?: string} = {}) =>
      get<Finding[]>(`/analyses/${id}/findings${qs(params)}`),
    source: (id: number, objectId: number) => get<ObjectSource>(`/analyses/${id}/objects/${objectId}/source`),
    cancel: (id: number) => post<AnalysisSummary>(`/analyses/${id}/cancel`),
    remove: (id: number) => del(`/analyses/${id}`),
    reportHtmlUrl: (id: number) => `${API_BASE}/analyses/${id}/report.html`,
    reportCsvUrl: (id: number) => `${API_BASE}/analyses/${id}/report.csv`,
  },
};

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return 'Beklenmeyen bir hata oluştu.';
}
