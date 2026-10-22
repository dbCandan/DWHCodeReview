import {apiFetch, apiRequest} from '@/lib/apiClient';
import {readEventStream} from '@/lib/eventStream';
import type {
  DeletedRuns,
  FalsePositiveState,
  ObjectSelection,
  ReviewRunDetail,
  ReviewRunPage,
  ReviewStreamEvent,
  RunCancelled,
} from '@/types/sqlReview';

export type ReviewEventHandler = (event: ReviewStreamEvent) => void;
export type ExportFormat = 'csv' | 'sql';

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

function isReviewEvent(value: unknown): value is ReviewStreamEvent {
  return (
    value !== null &&
    typeof value === 'object' &&
    typeof (value as {phase?: unknown}).phase === 'string'
  );
}

/**
 * POST the review request and hand every live progress event to `onEvent`. Errors before the
 * stream opens are ordinary error envelopes and reject as `ApiError`. The promise resolves when
 * the server closes the stream; aborting `signal` (the stop button) rejects with `AbortError` and
 * closes the connection, which stops the run on the server.
 */
async function stream(path: string, body: unknown, signal: AbortSignal, onEvent: ReviewEventHandler) {
  const response = await apiFetch(path, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: {Accept: 'text/event-stream'},
    signal,
  });
  if (response.body === null) return;
  for await (const data of readEventStream(response.body)) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(data);
    } catch {
      continue;
    }
    if (isReviewEvent(parsed)) onEvent(parsed);
  }
}

function filenameFrom(response: Response, fallback: string): string {
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return match?.[1] ?? fallback;
}

/** Object and script reviews with live progress, stored history and server-side exports. */
export const ReviewService = {
  /**
   * `ruleCodes` empty runs every rule; the screens expand a chosen group into its rules
   * (rule-group-selection Requirement 4, Decision 6).
   */
  streamObjectReview(
    selections: ObjectSelection[],
    signal: AbortSignal,
    onEvent: ReviewEventHandler,
    ruleCodes: string[] = [],
  ) {
    return stream('/object-reviews', {selections, rule_codes: ruleCodes}, signal, onEvent);
  },
  streamScriptReview(
    sql: string,
    label: string,
    signal: AbortSignal,
    onEvent: ReviewEventHandler,
    ruleCodes: string[] = [],
  ) {
    return stream('/script-reviews', {sql, label: label || null, rule_codes: ruleCodes}, signal, onEvent);
  },
  runs(scope: 'mine' | 'all', page: number, pageSize: number, signal?: AbortSignal): Promise<ReviewRunPage> {
    return apiRequest<ReviewRunPage>(`/review-runs?scope=${scope}&page=${page}&page_size=${pageSize}`, {signal});
  },
  /**
   * One page of the stored objects of a run with their results; `withSql` adds each object's
   * reviewed SQL for the code view (review-history-export Requirement 13).
   */
  run(runId: string, page: number, pageSize: number, signal?: AbortSignal, withSql = false): Promise<ReviewRunDetail> {
    const sql = withSql ? '&with_sql=true' : '';
    return apiRequest<ReviewRunDetail>(
      `/review-runs/${encodeURIComponent(runId)}?page=${page}&page_size=${pageSize}${sql}`,
      {signal},
    );
  },
  /** "Analizi durdur" by request (object-review Requirement 15, Decision 9). */
  cancelRun(runId: string): Promise<RunCancelled> {
    return apiRequest<RunCancelled>(`/review-runs/${encodeURIComponent(runId)}/cancel`, {method: 'POST'});
  },
  deleteRun(runId: string): Promise<void> {
    return apiRequest<void>(`/review-runs/${encodeURIComponent(runId)}`, {method: 'DELETE'});
  },
  deleteOwnRuns(): Promise<DeletedRuns> {
    return apiRequest<DeletedRuns>('/review-runs?scope=mine', {method: 'DELETE'});
  },
  markFinding(runId: string, findingId: string, falsePositive: boolean): Promise<FalsePositiveState> {
    return apiRequest<FalsePositiveState>(
      `/review-runs/${encodeURIComponent(runId)}/findings/${encodeURIComponent(findingId)}/false-positive`,
      {method: 'PUT', body: JSON.stringify({false_positive: falsePositive})},
    );
  },
  markRuleResult(runId: string, ruleResultId: string, falsePositive: boolean): Promise<FalsePositiveState> {
    return apiRequest<FalsePositiveState>(
      `/review-runs/${encodeURIComponent(runId)}/rule-results/${encodeURIComponent(ruleResultId)}/false-positive`,
      {method: 'PUT', body: JSON.stringify({false_positive: falsePositive})},
    );
  },
  /** Download a server-generated export with the session header; no token goes into a URL. */
  async exportRun(runId: string, format: ExportFormat): Promise<DownloadedFile> {
    const response = await apiFetch(`/review-runs/${encodeURIComponent(runId)}/exports/${format}`);
    const fallback = format === 'csv' ? 'sql-review.csv' : 'sql-review-source.sql';
    return {blob: await response.blob(), filename: filenameFrom(response, fallback)};
  },
};
