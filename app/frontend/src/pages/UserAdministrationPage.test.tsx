import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import UserAdministrationPage from './UserAdministrationPage';
import {UserAdminService} from '@/services/userAdmin';
import {apiError, renderWithSession, testUser} from '@/test/render';
import type {UserSummary} from '@/types/sqlReview';

const admin = testUser('super_admin');

function row(overrides: Partial<UserSummary>): UserSummary {
  return {
    public_id: '00000000-0000-4000-8000-0000000000a1',
    username: 'ayse.kaya@kurum.local',
    display_name: 'Ayşe Kaya',
    email: 'ayse.kaya@kurum.local',
    account_type: 'directory',
    role: 'inceleyici',
    is_active: true,
    is_super_admin: false,
    last_login_at: '2026-09-26T08:00:00Z',
    ...overrides,
  };
}

const users = [
  row({public_id: admin.public_id, username: 'admin', display_name: 'Yönetici', role: null, is_super_admin: true, account_type: 'local'}),
  row({}),
];

describe('user administration page', () => {
  beforeEach(() => {
    vi.spyOn(UserAdminService, 'list').mockResolvedValue({items: users, page: 1, size: 50, total: 2});
  });

  it('lists users with account type, role and status; the super admin row cannot be changed', async () => {
    renderWithSession(<UserAdministrationPage />, {role: 'super_admin', user: admin});
    const table = await screen.findByRole('table');
    const adminRow = within(table).getByText('admin').closest('tr')!;
    expect(within(adminRow).getByText('Süper yönetici')).toBeInTheDocument();
    expect(within(adminRow).queryByRole('button')).toBeNull();
    // directory-login Decision 14: everyone else is a user; there is no role to choose.
    const userRow = within(table).getByText('Ayşe Kaya').closest('tr')!;
    expect(within(userRow).getByText('Kullanıcı')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.getByText('Kurum dizini')).toBeInTheDocument();
  });

  it('deactivates and reactivates an account', async () => {
    const setActive = vi
      .spyOn(UserAdminService, 'setActive')
      .mockResolvedValueOnce({active: false})
      .mockResolvedValueOnce({active: true});
    renderWithSession(<UserAdministrationPage />, {role: 'super_admin', user: admin});
    fireEvent.click(await screen.findByRole('button', {name: 'ayse.kaya@kurum.local hesabını pasifleştir'}));
    expect(await screen.findByText('Pasif')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'ayse.kaya@kurum.local hesabını etkinleştir'}));
    await waitFor(() => expect(screen.getByText('Etkin')).toBeInTheDocument());
    expect(setActive.mock.calls.map((call) => call[1])).toEqual([false, true]);
  });

  it('shows the backend refusal message', async () => {
    vi.spyOn(UserAdminService, 'setActive').mockRejectedValue(apiError(409, 'super_admin_protected'));
    renderWithSession(<UserAdministrationPage />, {role: 'super_admin', user: admin});
    fireEvent.click(await screen.findByRole('button', {name: 'ayse.kaya@kurum.local hesabını pasifleştir'}));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Süper yönetici hesabının rolü ve durumu bu ekrandan değiştirilemez.',
    );
  });

  it('searches on submit and starts from the first page', async () => {
    renderWithSession(<UserAdministrationPage />, {role: 'super_admin', user: admin});
    await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText('Kullanıcı ara'), {target: {value: ' ayse '}});
    fireEvent.click(screen.getByRole('button', {name: 'Ara'}));
    await waitFor(() => expect(UserAdminService.list).toHaveBeenLastCalledWith({page: 1, size: 50, q: 'ayse'}));
  });
});
