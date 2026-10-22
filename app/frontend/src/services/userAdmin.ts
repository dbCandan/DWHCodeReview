import {apiRequest} from '@/lib/apiClient';
import type {UserPage, UserSummary} from '@/types/sqlReview';

type ActiveResult = {active: boolean};

/** Super-admin user administration (application-foundation directory-login Requirement 5). */
export const UserAdminService = {
  list(params: {page: number; size: number; q?: string}): Promise<UserPage> {
    const query = new URLSearchParams({page: String(params.page), size: String(params.size)});
    if (params.q) query.set('q', params.q);
    return apiRequest<UserPage>(`/admin/users?${query.toString()}`);
  },
  setActive(user: Pick<UserSummary, 'public_id'>, active: boolean): Promise<ActiveResult> {
    return apiRequest<ActiveResult>(`/admin/users/${encodeURIComponent(user.public_id)}/active`, {
      method: 'PUT',
      body: JSON.stringify({active}),
    });
  },
};
