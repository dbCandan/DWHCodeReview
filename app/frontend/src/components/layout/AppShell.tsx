import {Suspense, useState} from 'react';
import {NavLink, Outlet, useLocation} from 'react-router';
import {GlobalReviewIndicator, ReviewWindows} from '@/components/review/ReviewWindows';
import {Button} from '@/components/ui/Button';
import {LoadingState} from '@/components/ui/States';
import {useAuth} from '@/contexts/AuthContext';
import {useIntl} from '@/contexts/IntlContext';
import {ReviewSessionProvider, useReviewSession} from '@/contexts/ReviewSessionContext';
import {useConnectionMenu} from '@/hooks/useConnectionMenu';
import {useRuleProposalMenu} from '@/hooks/useRuleProposalMenu';
import {roleLabel} from '@/lib/access';
import {config} from '@/lib/config';

interface MenuItem {
  to: string;
  label: string;
  busy?: boolean;
  /** Pending decisions shown next to the label (rule-proposals Requirement 7). */
  count?: number;
}

/**
 * Signed-in layout: role-aware navigation, the user and sign-out, the live review indicator and
 * windows. Hiding a menu item is not authorization; every page's data comes from role-checked
 * endpoints.
 */
export function AppShell() {
  return (
    <ReviewSessionProvider>
      <ShellLayout />
    </ReviewSessionProvider>
  );
}

function ShellLayout() {
  const {user, access, logout} = useAuth();
  const {t} = useIntl();
  const {session} = useReviewSession();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPath, setMenuPath] = useState(location.pathname);
  const [signingOut, setSigningOut] = useState(false);
  const connections = useConnectionMenu(access.manageRules);
  const proposals = useRuleProposalMenu(access.review, location.pathname);

  // Close the narrow-screen menu after navigation.
  if (menuPath !== location.pathname) {
    setMenuPath(location.pathname);
    setMenuOpen(false);
  }

  const running = session.phase === 'running';
  const reviewItems: MenuItem[] = access.review
    ? [
        {to: '/inceleme', label: 'Nesne incelemesi', busy: running && session.kind === 'object'},
        {to: '/sql-inceleme', label: 'SQL betiği incelemesi', busy: running && session.kind === 'script'},
        {to: '/gecmis', label: 'İnceleme geçmişi'},
        {to: '/zamanlanmis-incelemeler', label: 'Zamanlanmış incelemeler'},
        {to: '/yayimlanmis-kurallar', label: 'Yayımlanmış kurallar'},
        ...(proposals.canPropose ? [{to: '/kural-onerilerim', label: 'Kural önerilerim'}] : []),
      ]
    : [];
  const adminItems: MenuItem[] = [
    ...(access.manageRules ? [{to: '/kurallar', label: 'Kurallar'}] : []),
    ...(proposals.canDecide ? [{to: '/kural-onaylari', label: 'Kural onayları', count: proposals.pending}] : []),
    ...(access.manageRules && connections.sql ? [{to: '/ayarlar/sql', label: 'SQL bağlantısı'}] : []),
    ...(access.manageRules && connections.llm ? [{to: '/ayarlar/llm', label: 'LLM bağlantısı'}] : []),
    ...(access.manageRules ? [{to: '/llm-cagrilari', label: 'LLM çağrıları'}] : []),
    ...(access.administerUsers ? [{to: '/ayarlar/zamanlama', label: 'Zamanlama ayarı'}] : []),
    ...(access.administerUsers ? [{to: '/kullanicilar', label: 'Kullanıcılar'}] : []),
  ];

  async function signOut() {
    setSigningOut(true);
    await logout();
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        {t('shell.skipToContent')}
      </a>
      <aside className="app-sidebar" data-open={menuOpen}>
        <div className="row">
          <div className="grow">
            <p className="app-brand">{config.productName}</p>
            <p className="app-brand-tag">{t('shell.tagline')}</p>
          </div>
          <Button
            size="sm"
            className="app-menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="main-navigation"
            onClick={() => setMenuOpen(!menuOpen)}
          >
            {t('shell.menu')}
          </Button>
        </div>
        <nav id="main-navigation" className="app-nav" aria-label={t('shell.navigation')}>
          <MenuGroup title={t('shell.nav.home')} items={[{to: '/', label: t('shell.nav.overview')}]} />
          {reviewItems.length > 0 && <MenuGroup title="İnceleme" items={reviewItems} />}
          {adminItems.length > 0 && <MenuGroup title="Yönetim" items={adminItems} />}
        </nav>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <GlobalReviewIndicator />
          <div className="app-topbar-user push-end">
            <span>
              <strong>{user?.display_name || user?.username}</strong>{' '}
              <span className="subtle">
                · {user?.is_super_admin ? t('home.overview.superAdmin') : roleLabel(user?.role)}
              </span>
            </span>
            <Button size="sm" onClick={() => void signOut()} disabled={signingOut} busy={signingOut}>
              {t('auth.session.signOut')}
            </Button>
          </div>
        </header>
        <main id="main-content" className="app-content" tabIndex={-1}>
          <Suspense fallback={<LoadingState />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      <ReviewWindows />
    </div>
  );
}

function MenuGroup({title, items}: {title: string; items: MenuItem[]}) {
  return (
    <div className="app-nav-group">
      <p className="app-nav-title">{title}</p>
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end>
          <span>{item.label}</span>
          {item.count !== undefined && item.count > 0 && (
            <span className="badge badge-warning" aria-label={`${item.count} bekleyen`}>
              {item.count}
            </span>
          )}
          {item.busy && <span className="pulse-dot" role="img" aria-label="İnceleme sürüyor" />}
        </NavLink>
      ))}
    </div>
  );
}
