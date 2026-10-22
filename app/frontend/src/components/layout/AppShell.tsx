import {Suspense, useEffect, useState} from 'react';
import {Link, Outlet, useLocation} from 'react-router';
import {BrandMark} from '@/components/brand/BrandMark';
import {CommandPalette} from '@/components/layout/CommandPalette';
import {Backdrop} from '@/components/layout/Backdrop';
import {GlobalReviewIndicator, ReviewWindows} from '@/components/review/ReviewWindows';
import {Icon} from '@/components/ui/Icon';
import {LoadingState} from '@/components/ui/States';
import {useAuth} from '@/contexts/AuthContext';
import {useIntl} from '@/contexts/IntlContext';
import {ReviewSessionProvider, useReviewSession} from '@/contexts/ReviewSessionContext';
import {NavigationProvider, useAppNavigation} from '@/contexts/NavigationContext';
import {isCurrent} from '@/lib/navigation';
import {roleLabel} from '@/lib/access';
import {config} from '@/lib/config';

/**
 * Signed-in layout, "Evren": a star field behind everything, one side menu with the daily work
 * and the super admin's Yönetim, Ctrl+K quick navigation, the live review and the user at the
 * foot; the page fills the rest of the screen. On a narrow screen the menu folds behind a button.
 * Hiding a destination is not authorization; every page's data comes from role-checked endpoints.
 */
export function AppShell() {
  return (
    <ReviewSessionProvider>
      <NavigationProvider>
        <ShellLayout />
      </NavigationProvider>
    </ReviewSessionProvider>
  );
}

function ShellLayout() {
  const {user, logout} = useAuth();
  const {t} = useIntl();
  const {session} = useReviewSession();
  const navigation = useAppNavigation();
  const {pathname} = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPath, setMenuPath] = useState(pathname);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  // Close the narrow-screen menu after navigation.
  if (menuPath !== pathname) {
    setMenuPath(pathname);
    setMenuOpen(false);
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen(true);
      } else if (event.key === 'Escape') {
        setMenuOpen(false);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const reviewing = session.phase === 'running';
  const displayName = user?.display_name || user?.username || '';
  const role = user?.is_super_admin ? t('home.overview.superAdmin') : roleLabel(user?.role);

  async function signOut() {
    setSigningOut(true);
    await logout();
  }

  return (
    <div className="shell" data-menu={menuOpen ? 'open' : 'closed'}>
      <Backdrop />
      <a className="skip-link" href="#main-content">
        {t('shell.skipToContent')}
      </a>
      <header className="mobilebar">
        <Link to="/" className="side-brand" aria-label={`${config.productName} ana sayfa`}>
          <BrandMark />
          <span className="side-brand-text" aria-hidden="true">
            <b>{config.productName}</b>
          </span>
        </Link>
        <button
          type="button"
          className="icon-button"
          aria-expanded={menuOpen}
          aria-controls="side-menu"
          onClick={() => setMenuOpen(!menuOpen)}
        >
          <Icon name="menu" />
          <span>{t('shell.menu')}</span>
        </button>
      </header>
      <aside id="side-menu" className="side">
        <Link to="/" className="side-brand" aria-label={`${config.productName} ana sayfa`}>
          <BrandMark />
          <span className="side-brand-text" aria-hidden="true">
            <b>{config.productName}</b>
            <small>{t('shell.tagline')}</small>
          </span>
        </Link>
        <button
          type="button"
          className="cmdk-trigger"
          onClick={() => setPaletteOpen(true)}
          aria-keyshortcuts="Control+K"
          aria-label="Hızlı geçiş (Ctrl+K)"
        >
          <Icon name="search" />
          <span className="grow">Ara veya git…</span>
          <kbd>Ctrl K</kbd>
        </button>
        <nav className="menu" aria-label={t('shell.navigation')}>
          {navigation.groups.map((group, index) => (
            <div key={index} className="menu-group">
              {group.items.map((item) => (
                <Link key={item.to} to={item.to} aria-current={isCurrent(item, pathname) ? 'page' : undefined}>
                  <Icon name={item.icon} />
                  <span className="grow truncate">{item.label}</span>
                  {reviewing &&
                    ((item.to === '/inceleme' && session.kind === 'object') ||
                      (item.to === '/sql-inceleme' && session.kind === 'script')) && (
                      <span className="pulse-dot" role="img" aria-label="İnceleme sürüyor" />
                    )}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <GlobalReviewIndicator />
          <div className="side-user">
            <span className="avatar" aria-hidden="true">
              {initials(displayName)}
            </span>
            <span className="side-user-text">
              <strong className="truncate">{displayName}</strong>
              <span className="truncate">{role}</span>
            </span>
            <button
              type="button"
              className="icon-button"
              onClick={() => void signOut()}
              disabled={signingOut}
              aria-busy={signingOut || undefined}
              title={t('auth.session.signOut')}
            >
              <Icon name="logOut" />
              <span className="sr-only">{t('auth.session.signOut')}</span>
            </button>
          </div>
        </div>
      </aside>
      {menuOpen && (
        <button type="button" className="side-scrim" aria-label="Menüyü kapat" onClick={() => setMenuOpen(false)} />
      )}
      <main id="main-content" className="shell-main" tabIndex={-1}>
        <Suspense fallback={<LoadingState />}>
          <Outlet />
        </Suspense>
      </main>
      <ReviewWindows />
      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} />}
    </div>
  );
}

/** Up to two initials of a display name for the avatar disc; decorative. */
function initials(name: string): string {
  const parts = name.trim().split(/[\s._-]+/).filter(Boolean);
  return parts
    .slice(0, 2)
    .map((part) => part[0].toLocaleUpperCase('tr-TR'))
    .join('');
}
