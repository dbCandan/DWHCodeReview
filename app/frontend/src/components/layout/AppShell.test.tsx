import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import App from '@/App';
import {AuthProvider} from '@/contexts/AuthContext';
import {IntlProvider} from '@/contexts/IntlContext';
import {clearAuth, readAccessToken, writeSession} from '@/lib/authStorage';
import messages from '@/locales/tr.json';
import {AuthService} from '@/services/auth';
import {ConnectionService} from '@/services/connections';
import {ReviewService} from '@/services/reviews';
import {RuleSetService} from '@/services/ruleSet';
import {ScheduledReviewService} from '@/services/scheduledReviews';
import {apiError, testUser, type TestRole} from '@/test/render';
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

function menu(): HTMLElement {
  return screen.getByRole('navigation', {name: messages['shell.navigation']});
}

function menuLinks(): string[] {
  return within(menu())
    .getAllByRole('link')
    .map((link) => link.textContent ?? '');
}

function tabLinks(): string[] {
  return within(screen.getByRole('navigation', {name: 'Yönetim bölümleri'}))
    .getAllByRole('link')
    .map((link) => link.textContent ?? '');
}

function openTabs(): Promise<HTMLElement> {
  return screen.findByRole('navigation', {name: 'Yönetim bölümleri'});
}

const WORK = ['Ana sayfa', 'Nesne incelemesi', 'SQL betiği', 'Zamanlanmış', 'Geçmiş', 'Kural kitaplığı'];

function pageViews() {
  vi.spyOn(ReviewService, 'runs').mockResolvedValue({items: [], page: 1, page_size: 5, total: 0});
  vi.spyOn(RuleSetService, 'latest').mockRejectedValue(apiError(404, 'no_published_rule_set'));
  vi.spyOn(ScheduledReviewService, 'settings').mockResolvedValue({max_concurrent_runs: 2});
  vi.spyOn(ScheduledReviewService, 'emailStatus').mockResolvedValue({
    scheduler_enabled: true,
    smtp_configured: false,
    smtp_security: 'starttls',
    allowed_domains: ['kurum.example'],
    suggested_recipient: null,
  });
}

function connectionViews(editable: boolean) {
  const environment = editable ? 'local' : 'nonprod';
  const managed_by = editable ? 'local_process' : 'deployment';
  vi.spyOn(ConnectionService, 'sql').mockResolvedValue({environment, editable, configured: true, managed_by});
  vi.spyOn(ConnectionService, 'llm').mockResolvedValue({environment, editable, chat_api: 'openai', model: 'm'});
}

describe('application shell', () => {
  beforeEach(() => {
    connectionViews(true);
    pageViews();
  });

  it('offers a user the daily work and no administration, without asking for settings', async () => {
    renderApp('inceleyici');
    await screen.findByRole('navigation', {name: messages['shell.navigation']});
    expect(menuLinks()).toEqual(WORK);
    expect(ConnectionService.sql).not.toHaveBeenCalled();
  });

  it('gathers every administration screen under one Yönetim entry for the super admin', async () => {
    renderApp('super_admin', '/yonetim');
    await within(await openTabs()).findByRole('link', {name: 'SQL bağlantısı'});
    expect(menuLinks()).toEqual([...WORK, 'Yönetim']);
    expect(within(menu()).getByRole('link', {name: 'Yönetim'})).toHaveAttribute('aria-current', 'page');
    expect(tabLinks()).toEqual([
      'Genel durum',
      'Kurallar',
      'SQL bağlantısı',
      'LLM bağlantısı',
      'LLM çağrıları',
      'Zamanlama ve e-posta',
      'Kullanıcılar',
    ]);
    expect(screen.getByRole('heading', {name: 'Yönetim', level: 1})).toBeInTheDocument();
  });

  it('hides the connection sections when the backend reports them read-only (nonprod)', async () => {
    vi.restoreAllMocks();
    pageViews();
    connectionViews(false);
    renderApp('super_admin', '/yonetim');
    await openTabs();
    await waitFor(() => expect(ConnectionService.llm).toHaveBeenCalled());
    expect(tabLinks()).toEqual(['Genel durum', 'Kurallar', 'LLM çağrıları', 'Zamanlama ve e-posta', 'Kullanıcılar']);
  });

  it('offers the SQL connection section in nonprod only to the super admin who may edit it', async () => {
    // sql-server-connection Requirement 5: the backend reports editable only to the super admin.
    vi.restoreAllMocks();
    pageViews();
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
    renderApp('super_admin', '/yonetim');
    await within(await openTabs()).findByRole('link', {name: 'SQL bağlantısı'});
    expect(tabLinks()).not.toContain('LLM bağlantısı');
    expect(tabLinks()).toContain('Kullanıcılar');
  });

  it('shows the health of the system on Genel durum', async () => {
    renderApp('super_admin', '/yonetim');
    const health = await screen.findByRole('region', {name: 'Sistem durumu'});
    expect(await within(health).findByText('Bağlı')).toBeInTheDocument();
    expect(await within(health).findByText('Yapılandırılmadı')).toBeInTheDocument();
    expect(await within(health).findByText('Yayımlanmadı')).toBeInTheDocument();
  });

  it.each(['/kurallar', '/yonetim', '/yonetim/kullanicilar', '/ayarlar/llm'])(
    'shows the forbidden screen when a user opens %s',
    async (path) => {
      renderApp('inceleyici', path);
      expect(await screen.findByRole('heading', {name: messages['access.forbidden.title']})).toBeInTheDocument();
    },
  );

  it.each([
    ['/kural-onerilerim', 'Yayımlanmış kurallar'],
    ['/inceleme', 'Nesne incelemesi'],
  ])('takes %s to its page', async (path, heading) => {
    renderApp('inceleyici', path);
    expect(await screen.findByRole('heading', {name: heading, level: 1})).toBeInTheDocument();
  });

  it('takes an old administration address to its section on the Yönetim page', async () => {
    renderApp('super_admin', '/ayarlar/zamanlama');
    expect(await screen.findByRole('heading', {name: 'Zamanlama ve e-posta', level: 2})).toBeInTheDocument();
    const tabs = await openTabs();
    expect(within(tabs).getByRole('link', {name: 'Zamanlama ve e-posta'})).toHaveAttribute('aria-current', 'page');
  });

  it('opens quick navigation with Ctrl+K and goes to the chosen place', async () => {
    renderApp('super_admin');
    await within(await screen.findByRole('navigation', {name: messages['shell.navigation']})).findByRole('link', {
      name: 'Yönetim',
    });
    fireEvent.keyDown(window, {key: 'k', ctrlKey: true});
    const input = await screen.findByRole('combobox', {name: 'Gidilecek sayfa'});
    fireEvent.change(input, {target: {value: 'zamanlama ve'}});
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent('Zamanlama ve e-posta');
    fireEvent.keyDown(input, {key: 'Enter'});
    expect(await screen.findByRole('heading', {name: 'Zamanlama ve e-posta', level: 2})).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows the display name and role, and signs out through the server', async () => {
    const logout = vi.spyOn(AuthService, 'logout').mockResolvedValue(undefined);
    renderApp('inceleyici');
    const side = await screen.findByRole('complementary');
    expect(within(side).getByText('Ayşe İnceleyici')).toBeInTheDocument();
    expect(within(side).getByText('Kullanıcı')).toBeInTheDocument();
    fireEvent.click(within(side).getByRole('button', {name: messages['auth.session.signOut']}));
    await screen.findByLabelText(messages['auth.login.username']);
    expect(logout).toHaveBeenCalledTimes(1);
    expect(readAccessToken()).toBeNull();
  });
});
