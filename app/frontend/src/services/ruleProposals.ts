import {apiRequest} from '@/lib/apiClient';
import type {
  PublishRequestDetail,
  PublishRequestPage,
  PublishRequestStatus,
  RuleProposalCapabilities,
  RuleProposalCreate,
  RuleProposalDetail,
  RuleProposalPage,
  RuleProposerList,
} from '@/types/sqlReview';

type Scope = 'mine' | 'pending' | 'all';

function post<T>(path: string, body?: unknown): Promise<T> {
  return apiRequest<T>(path, {method: 'POST', body: body === undefined ? undefined : JSON.stringify(body)});
}

/** Rule and group proposals, publish requests and the proposal permission (sql-review rule-proposals). */
export const RuleProposalService = {
  capabilities(signal?: AbortSignal): Promise<RuleProposalCapabilities> {
    return apiRequest<RuleProposalCapabilities>('/rule-proposals/capabilities', {signal});
  },
  list(scope: Scope, page: number, pageSize: number, signal?: AbortSignal): Promise<RuleProposalPage> {
    return apiRequest<RuleProposalPage>(`/rule-proposals?scope=${scope}&page=${page}&page_size=${pageSize}`, {signal});
  },
  get(id: string, signal?: AbortSignal): Promise<RuleProposalDetail> {
    return apiRequest<RuleProposalDetail>(`/rule-proposals/${encodeURIComponent(id)}`, {signal});
  },
  create(body: RuleProposalCreate): Promise<RuleProposalDetail> {
    return post<RuleProposalDetail>('/rule-proposals', body);
  },
  withdraw(id: string): Promise<RuleProposalDetail> {
    return post<RuleProposalDetail>(`/rule-proposals/${encodeURIComponent(id)}/withdraw`);
  },
  approve(id: string): Promise<RuleProposalDetail> {
    return post<RuleProposalDetail>(`/rule-proposals/${encodeURIComponent(id)}/approve`);
  },
  reject(id: string, reason: string): Promise<RuleProposalDetail> {
    return post<RuleProposalDetail>(`/rule-proposals/${encodeURIComponent(id)}/reject`, {reason});
  },
  requestPublish(baseRevision: number): Promise<PublishRequestDetail> {
    return post<PublishRequestDetail>('/rule-set/publish-requests', {base_revision: baseRevision});
  },
  publishRequests(
    status: PublishRequestStatus | null,
    page: number,
    pageSize: number,
    signal?: AbortSignal,
  ): Promise<PublishRequestPage> {
    const filter = status === null ? '' : `status=${status}&`;
    return apiRequest<PublishRequestPage>(`/rule-set/publish-requests?${filter}page=${page}&page_size=${pageSize}`, {
      signal,
    });
  },
  publishRequest(id: string, signal?: AbortSignal): Promise<PublishRequestDetail> {
    return apiRequest<PublishRequestDetail>(`/rule-set/publish-requests/${encodeURIComponent(id)}`, {signal});
  },
  approveRequest(id: string): Promise<PublishRequestDetail> {
    return post<PublishRequestDetail>(`/rule-set/publish-requests/${encodeURIComponent(id)}/approve`);
  },
  rejectRequest(id: string, reason: string): Promise<PublishRequestDetail> {
    return post<PublishRequestDetail>(`/rule-set/publish-requests/${encodeURIComponent(id)}/reject`, {reason});
  },
  proposers(signal?: AbortSignal): Promise<RuleProposerList> {
    return apiRequest<RuleProposerList>('/rule-proposers', {signal});
  },
  grant(userId: string): Promise<void> {
    return apiRequest<void>(`/rule-proposers/${encodeURIComponent(userId)}`, {method: 'PUT'});
  },
  revoke(userId: string): Promise<void> {
    return apiRequest<void>(`/rule-proposers/${encodeURIComponent(userId)}`, {method: 'DELETE'});
  },
};
