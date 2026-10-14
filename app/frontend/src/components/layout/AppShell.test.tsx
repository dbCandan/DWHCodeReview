import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import App from '@/App';
import {AuthProvider} from '@/contexts/AuthContext';
import {IntlProvider} from '@/contexts/IntlContext';
import {clearAuth, readAccessToken, writeSession} from '@/lib/authStorage';
import messages from '@/locales/tr.json';
import {AuthService} from '@/services/auth';
import {ConnectionService} from '@/services/connections';
import {RuleProposalService} from '@/services/ruleProposals';
import {testUser, type TestRole} from '@/test/render';
import {MemoryRouter} from 'react-router';

function renderApp(role: TestRole, path = '/') {
  clearAuth();
  writeSession('jwt', testUser(role));
  render(
    <MemoryRouter initialEntries={[path]}>
      <IntlProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </IntlProvider>
    </MemoryRouter>,
  );
}

function menuLinks(): string[] {
  const nav = screen.getByRole('navigation', {name: messages['shell.navigation']});
  return within(nav)
    .getAllByRole('link')
    .map((link) => link.textContent ?? '');
}

function connectionViews(editable: boolean) {
  const environment = editable ? 'local' : 'nonprod';
  const managed_by = editable ? 'local_process' : 'deployment';
  vi.spyOn(ConnectionService, 'sql').mockResolvedValue({environment, editable, configured: true, managed_by});
  vi.spyOn(ConnectionService, 'llm').mockResolvedValue({environment, editable, chat_api: 'openai', model: 'm'});
  proposalMenu(false, false);
}

function proposalMenu(canPropose: boolean, canDecide: boolean, pending = {proposals: 0, requests: 0}) {
  vi.spyOn(RuleProposalService, 'capabilities').mockResolvedValue({can_propose: canPropose, can_decide: canDecide});
  vi.spyOn(RuleProposalService, 'list').mockResolvedValue({items: [], page: 1, page_size: 1, total: pending.proposals});
  vi.spyOn(RuleProposalService, 'publishRequests').mockResolvedValue({
    items: [],
    page: 1,
    page_size: 1,
    total: pending.requests,
  });
}

describe('application shell', () => {
  beforeEach(() => connectionViews(true));

  it('offers review pages but no administration to a reviewer and does not ask for settings', async () => {
    renderApp('inceleyici');
    await screen.findByRole('navigation', {name: messages['shell.navigation']});
    expect(menuLinks()).toEqual([
      'Ana sayfa',
      'Nesne incelemesi',
      'SQL betiği incelemesi',
      'İnceleme geçmişi',
      'Zamanlanmış incelemeler',
      'Yayımlanmış kurallar',
    ]);
    expect(ConnectionService.sql).not.toHaveBeenCalled();
  });

  it('adds rules, editable connections and LLM calls for the rule manager', async () => {
    renderApp('kural-yoneticisi');
    await screen.findByRole('link', {name: 'SQL bağlantısı'});
    expect(menuLinks()).toEqual([
      'Ana sayfa',
      'Nesne incelemesi',
      'SQL betiği incelemesi',
      'İnceleme geçmişi',
      'Zamanlanmış incelemeler',
      'Yayımlanmış kurallar',
      'Kurallar',
      'SQL bağlantısı',
      'LLM bağlantısı',
      'LLM çağrıları',
    ]);
  });

  it('hides the connection pages when the backend reports them read-only (nonprod)', async () => {
    vi.restoreAllMocks();
    proposalMenu(false, false);
    connectionViews(false);
    renderApp('kural-yoneticisi');
    await screen.findByRole('link', {name: 'Kurallar'});
    await waitFor(() => expect(ConnectionService.llm).toHaveBeenCalled());
    expect(menuLinks()).not.toContain('SQL bağlantısı');
    expect(menuLinks()).not.toContain('LLM bağlantısı');
  });

  it('offers the SQL connection page in nonprod only to the super admin who may edit it', async () => {
    // sql-server-connection Requirement 5: the backend reports editable only to the super admin.
    vi.restoreAllMocks();
    proposalMenu(false, false);
    vi.spyOn(ConnectionService, 'llm').mockResolvedValue({
      environment: 'nonprod',
      editable: false,
      chat_api: 'openai',
      model: 'm',
    });
    vi.spyOn(ConnectionService, 'sql').mockResolvedValue({
      environment: 'nonprod',
      editable: true,
      configured: false,
      managed_by: 'super_admin',
      password_set: false,
    });
    renderApp('super_admin');
    await screen.findByRole('link', {name: 'SQL bağlantısı'});
    expect(menuLinks()).not.toContain('LLM bağlantısı');
    expect(menuLinks()).toContain('Kullanıcılar');
    expect(menuLinks()).toContain('Zamanlama ayarı');
  });

  it('hides the nonprod SQL connection page from the rule manager while the super admin manages it', async () => {
    vi.restoreAllMocks();
    proposalMenu(false, false);
    vi.spyOn(ConnectionService, 'llm').mockResolvedValue({
      environment: 'nonprod',
      editable: false,
      chat_api: 'openai',
      model: 'm',
    });
    const sql = vi.spyOn(ConnectionService, 'sql').mockResolvedValue({
      environment: 'nonprod',
      editable: false,
      configured: true,
      managed_by: 'super_admin',
    });
    renderApp('kural-yoneticisi');
    await screen.findByRole('link', {name: 'Kurallar'});
    await waitFor(() => expect(sql).toHaveBeenCalled());
    expect(menuLinks()).not.toContain('SQL bağlantısı');
  });

  it('adds user administration for the super admin', async () => {
    renderApp('super_admin');
    await screen.findByRole('link', {name: 'Kullanıcılar'});
    expect(menuLinks()).toContain('Kurallar');
  });

  it('offers "Kural önerilerim" to a user the super admin allowed to propose', async () => {
    proposalMenu(true, false);
    renderApp('inceleyici');
    await screen.findByRole('link', {name: 'Kural önerilerim'});
    expect(menuLinks()).not.toContain('Kural onayları');
  });

  it('offers "Kural onayları" with the pending count to the super admin', async () => {
    proposalMenu(true, true, {proposals: 2, requests: 1});
    renderApp('super_admin');
    const link = await screen.findByRole('link', {name: /Kural onayları/});
    expect(await within(link).findByLabelText('3 bekleyen')).toHaveTextContent('3');
  });

  it('shows the forbidden screen when a reviewer opens the approvals address directly', async () => {
    renderApp('inceleyici', '/kural-onaylari');
    expect(await screen.findByRole('heading', {name: messages['access.forbidden.title']})).toBeInTheDocument();
  });

  it('shows the forbidden screen when a reviewer opens the rules address directly', async () => {
    renderApp('inceleyici', '/kurallar');
    expect(await screen.findByRole('heading', {name: messages['access.forbidden.title']})).toBeInTheDocument();
  });

  it('shows the display name and role, and signs out through the server', async () => {
    const logout = vi.spyOn(AuthService, 'logout').mockResolvedValue(undefined);
    renderApp('inceleyici');
    const banner = await screen.findByRole('banner');
    expect(within(banner).getByText('Ayşe İnceleyici')).toBeInTheDocument();
    expect(within(banner).getByText(/· İnceleyici/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: messages['auth.session.signOut']}));
    await screen.findByLabelText(messages['auth.login.username']);
    expect(logout).toHaveBeenCalledTimes(1);
    expect(readAccessToken()).toBeNull();
  });
});
