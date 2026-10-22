import {apiRequest} from '@/lib/apiClient';
import type {
  LlmCallSummary,
  LlmCallSummaryPage,
  LlmConnectionUpdate,
  LlmConnectionView,
  SqlConnectionChange,
  SqlConnectionTestResult,
  SqlConnectionView,
} from '@/types/sqlReview';

/** SQL Server and LLM connection settings and LLM call summaries (super admin only). */
export const ConnectionService = {
  sql(signal?: AbortSignal): Promise<SqlConnectionView> {
    return apiRequest<SqlConnectionView>('/sql-connection', {signal});
  },
  saveSql(change: SqlConnectionChange): Promise<SqlConnectionView> {
    return apiRequest<SqlConnectionView>('/sql-connection', {method: 'PUT', body: JSON.stringify(change)});
  },
  testSql(change: SqlConnectionChange): Promise<SqlConnectionTestResult> {
    return apiRequest<SqlConnectionTestResult>('/sql-connection/test', {
      method: 'POST',
      body: JSON.stringify(change),
    });
  },
  llm(signal?: AbortSignal): Promise<LlmConnectionView> {
    return apiRequest<LlmConnectionView>('/llm-connection', {signal});
  },
  saveLlm(update: LlmConnectionUpdate): Promise<LlmConnectionView> {
    return apiRequest<LlmConnectionView>('/llm-connection', {method: 'PUT', body: JSON.stringify(update)});
  },
  llmCalls(limit: number, signal?: AbortSignal): Promise<LlmCallSummaryPage> {
    return apiRequest<LlmCallSummaryPage>(`/llm-calls?limit=${limit}`, {signal});
  },
  llmCall(publicId: string, signal?: AbortSignal): Promise<LlmCallSummary> {
    return apiRequest<LlmCallSummary>(`/llm-calls/${encodeURIComponent(publicId)}`, {signal});
  },
};
