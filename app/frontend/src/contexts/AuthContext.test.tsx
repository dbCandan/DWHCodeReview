import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {StrictMode} from 'react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {AuthProvider, useAuth} from './AuthContext';
import {ApiError} from '@/lib/apiClient';
import {clearAuth, readAccessToken, readUser, writeSession} from '@/lib/authStorage';
import {AuthService} from '@/services/auth';
import {testUser} from '@/test/render';
import type {LoginResponse} from '@/types/auth';

const reviewer = testUser('inceleyici');

function issued(token: string, user = reviewer): LoginResponse {
  return {access_token: token, token_type: 'bearer', expires_in: 900, user};
}

function Probe() {
  const {user, loading, access, logout} = useAuth();
  return (
    <div>
      <p data-testid="session">{loading ? 'loading' : (user?.username ?? 'signed-out')}</p>
      <p data-testid="access">{JSON.stringify(access)}</p>
      <button onClick={() => void logout()}>sign out</button>
    </div>
  );
}

async function settled(): Promise<string | null> {
  render(
    <StrictMode>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </StrictMode>,
  );
  await waitFor(() => expect(screen.queryByText('loading')).toBeNull());
  return screen.getByTestId('session').textContent;
}

describe('auth context session', () => {
  beforeEach(() => clearAuth());

  it('restores the session from the refresh cookie once, even under StrictMode', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(issued('jwt-restored')), {status: 200, headers: {'Content-Type': 'application/json'}}),
    );

    expect(await settled()).toBe(reviewer.username);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/dwhcodereview/v1/auth/refresh');
    expect(readAccessToken()).toBe('jwt-restored');
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it.each([
    ['an expired refresh session', new ApiError(401, 'expired', 'session_expired', true)],
    ['a network error', new TypeError('Failed to fetch')],
  ])('shows the login when restoring fails with %s', async (_, failure) => {
    vi.spyOn(AuthService, 'refresh').mockRejectedValue(failure);
    expect(await settled()).toBe('signed-out');
  });

  it('does not call refresh when a session is already in memory', async () => {
    writeSession('jwt', reviewer);
    const refresh = vi.spyOn(AuthService, 'refresh');
    expect(await settled()).toBe(reviewer.username);
    expect(refresh).not.toHaveBeenCalled();
  });

  it('signs out when the shared client ends the session', async () => {
    writeSession('jwt', reviewer);
    expect(await settled()).toBe(reviewer.username);
    act(() => clearAuth());
    expect(screen.getByTestId('session').textContent).toBe('signed-out');
  });

  it('closes the refresh session on the server and then clears the memory session', async () => {
    writeSession('jwt', reviewer);
    const logout = vi.spyOn(AuthService, 'logout').mockResolvedValue(undefined);
    await settled();
    fireEvent.click(screen.getByRole('button', {name: 'sign out'}));
    await waitFor(() => expect(screen.getByTestId('session').textContent).toBe('signed-out'));
    expect(logout).toHaveBeenCalledTimes(1);
    expect(readUser()).toBeNull();
  });

  it('still ends the local session when the logout call fails', async () => {
    writeSession('jwt', reviewer);
    vi.spyOn(AuthService, 'logout').mockRejectedValue(new TypeError('Failed to fetch'));
    await settled();
    fireEvent.click(screen.getByRole('button', {name: 'sign out'}));
    await waitFor(() => expect(readAccessToken()).toBeNull());
  });

  it.each([
    ['inceleyici', {review: true, manageRules: false, administerUsers: false}],
    ['super_admin', {review: true, manageRules: true, administerUsers: true}],
  ] as const)('derives menu access for %s', async (role, expected) => {
    writeSession('jwt', testUser(role));
    await settled();
    expect(JSON.parse(screen.getByTestId('access').textContent ?? '{}')).toEqual(expected);
  });
});
