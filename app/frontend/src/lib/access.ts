import type {AuthenticatedUser} from '@/types/auth';

export const ROLE_REVIEWER = 'inceleyici';

/**
 * What the navigation offers to the signed-in user. It never replaces backend authorization.
 * application-foundation directory-login Decision 14: there are users and the super admin; rules,
 * connections, LLM calls, scheduling and users are the super admin's.
 */
export interface Access {
  /** Every signed-in user (the super admin passes every role check on the backend). */
  review: boolean;
  /** Super admin: rules, connection settings and LLM call summaries. */
  manageRules: boolean;
  /** Super admin: user administration. */
  administerUsers: boolean;
}

export type AccessRequirement = keyof Access;

export function accessOf(user: AuthenticatedUser | null): Access {
  if (user === null) return {review: false, manageRules: false, administerUsers: false};
  const superAdmin = Boolean(user.is_super_admin);
  return {
    review: superAdmin || user.role === ROLE_REVIEWER,
    manageRules: superAdmin,
    administerUsers: superAdmin,
  };
}

export function roleLabel(role: string | null | undefined): string {
  return role === ROLE_REVIEWER ? 'Kullanıcı' : 'Rol yok';
}
