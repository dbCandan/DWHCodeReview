import {apiRequest} from '@/lib/apiClient';
import type {
  ScheduledReviewDetail,
  ScheduledReviewPage,
  ScheduledReviewSettings,
  ScheduledReviewWrite,
  ScheduledRunPage,
  ScheduledRunQueued,
} from '@/types/sqlReview';

const BASE = '/scheduled-reviews';

function one(id: string): string {
  return `${BASE}/${encodeURIComponent(id)}`;
}

/** Scheduled review definitions, their runs and the setting (sql-review scheduled-review-email). */
export const ScheduledReviewService = {
  list(page: number, pageSize: number, signal?: AbortSignal): Promise<ScheduledReviewPage> {
    return apiRequest<ScheduledReviewPage>(`${BASE}?page=${page}&page_size=${pageSize}`, {signal});
  },
  get(id: string, signal?: AbortSignal): Promise<ScheduledReviewDetail> {
    return apiRequest<ScheduledReviewDetail>(one(id), {signal});
  },
  create(body: ScheduledReviewWrite): Promise<ScheduledReviewDetail> {
    return apiRequest<ScheduledReviewDetail>(BASE, {method: 'POST', body: JSON.stringify(body)});
  },
  update(id: string, body: ScheduledReviewWrite): Promise<ScheduledReviewDetail> {
    return apiRequest<ScheduledReviewDetail>(one(id), {method: 'PUT', body: JSON.stringify(body)});
  },
  remove(id: string): Promise<void> {
    return apiRequest<void>(one(id), {method: 'DELETE'});
  },
  pause(id: string): Promise<ScheduledReviewDetail> {
    return apiRequest<ScheduledReviewDetail>(`${one(id)}/pause`, {method: 'POST'});
  },
  resume(id: string): Promise<ScheduledReviewDetail> {
    return apiRequest<ScheduledReviewDetail>(`${one(id)}/resume`, {method: 'POST'});
  },
  runNow(id: string): Promise<ScheduledRunQueued> {
    return apiRequest<ScheduledRunQueued>(`${one(id)}/run`, {method: 'POST'});
  },
  runs(id: string, page: number, pageSize: number, signal?: AbortSignal): Promise<ScheduledRunPage> {
    return apiRequest<ScheduledRunPage>(`${one(id)}/runs?page=${page}&page_size=${pageSize}`, {signal});
  },
  settings(signal?: AbortSignal): Promise<ScheduledReviewSettings> {
    return apiRequest<ScheduledReviewSettings>('/scheduled-review-settings', {signal});
  },
  saveSettings(body: ScheduledReviewSettings): Promise<ScheduledReviewSettings> {
    return apiRequest<ScheduledReviewSettings>('/scheduled-review-settings', {
      method: 'PUT',
      body: JSON.stringify(body),
    });
  },
};
