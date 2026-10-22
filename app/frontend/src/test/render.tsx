import {render} from '@testing-library/react';
import type {ReactElement} from 'react';
import {MemoryRouter, Route, Routes} from 'react-router';
import {AuthProvider} from '@/contexts/AuthContext';
import {IntlProvider} from '@/contexts/IntlContext';
import {ReviewSessionProvider} from '@/contexts/ReviewSessionContext';
import {ApiError} from '@/lib/apiClient';
import {clearAuth, writeSession} from '@/lib/authStorage';
import type {AuthenticatedUser} from '@/types/auth';

export type TestRole = 'inceleyici' | 'super_admin';

export function testUser(role: TestRole, overrides: Partial<AuthenticatedUser> = {}): AuthenticatedUser {
  const superAdmin = role === 'super_admin';
  return {
    public_id: `00000000-0000-4000-8000-00000000000${superAdmin ? 1 : 2}`,
    tenant_id: '00000000-0000-4000-8000-000000000010',
    username: superAdmin ? 'admin' : 'ayse.inceleyici',
    display_name: superAdmin ? 'Uygulama Yöneticisi' : 'Ayşe İnceleyici',
    account_type: 'local',
    role: superAdmin ? null : role,
    roles: [role],
    permissions: ['platform:access'],
    is_super_admin: superAdmin,
    ...overrides,
  };
}

/** Sign a test user in (memory only) and render `ui` at `path` with every app provider. */
export function renderWithSession(
  ui: ReactElement,
  {role = 'inceleyici', path = '/', routePath = '*', user}: {role?: TestRole; path?: string; routePath?: string; user?: AuthenticatedUser} = {},
) {
  clearAuth();
  writeSession('test-token', user ?? testUser(role));
  return render(
    <MemoryRouter initialEntries={[path]}>
      <IntlProvider>
        <AuthProvider>
          <ReviewSessionProvider>
            <Routes>
              <Route path={routePath} element={ui} />
              <Route path="/login" element={<p>login page</p>} />
            </Routes>
          </ReviewSessionProvider>
        </AuthProvider>
      </IntlProvider>
    </MemoryRouter>,
  );
}

export function apiError(status: number, code?: string): ApiError {
  return new ApiError(status, code ?? 'error', code);
}

/** A promise the test resolves or rejects later. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return {promise, resolve, reject};
}
