import {apiRequest} from '@/lib/apiClient';
import type {
  RuleGroupItem,
  RuleItem,
  RuleSetVersionDetail,
  RuleSetVersionPage,
  RuleSetWorkspace,
} from '@/types/sqlReview';

/** Rule-set draft and published versions (sql-review rule-management API contract). */
export const RuleSetService = {
  workspace(signal?: AbortSignal): Promise<RuleSetWorkspace> {
    return apiRequest<RuleSetWorkspace>('/rule-set', {signal});
  },
  saveDraft(
    baseRevision: number,
    critical: RuleItem[],
    normal: RuleItem[],
    groups: RuleGroupItem[],
  ): Promise<RuleSetWorkspace> {
    return apiRequest<RuleSetWorkspace>('/rule-set/draft', {
      method: 'PUT',
      body: JSON.stringify({base_revision: baseRevision, critical, normal, groups}),
    });
  },
  publish(baseRevision: number): Promise<RuleSetVersionDetail> {
    return apiRequest<RuleSetVersionDetail>('/rule-set/versions', {
      method: 'POST',
      body: JSON.stringify({base_revision: baseRevision}),
    });
  },
  versions(page: number, pageSize: number, signal?: AbortSignal): Promise<RuleSetVersionPage> {
    return apiRequest<RuleSetVersionPage>(`/rule-set/versions?page=${page}&page_size=${pageSize}`, {signal});
  },
  latest(signal?: AbortSignal): Promise<RuleSetVersionDetail> {
    return apiRequest<RuleSetVersionDetail>('/rule-set/versions/latest', {signal});
  },
  version(number: number, signal?: AbortSignal): Promise<RuleSetVersionDetail> {
    return apiRequest<RuleSetVersionDetail>(`/rule-set/versions/${number}`, {signal});
  },
};
