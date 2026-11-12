import {useEffect, useState, type ReactNode} from 'react';
import {Outlet, useLocation, useNavigate} from 'react-router';
import {CircleHelp, Menu, Moon, Play, Search, Sun} from 'lucide-react';
import {cn, isMac, safeStorageGet, safeStorageSet} from '@/lib/utils';
import {openTour} from '@/lib/tour';
import {WelcomeTour} from '@/components/tour/WelcomeTour';
import {useTheme} from '@/hooks/theme';
import {Button} from '@/components/ui/Button';
import {Kbd} from '@/components/ui/Badge';
import {Tooltip} from '@/components/ui/Tooltip';
import {Sidebar} from './Sidebar';
import {CommandPalette} from './CommandPalette';
import {titleFor} from './nav';

function useMedia(query: string) {
  const [matches, setMatches] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const on = () => setMatches(mql.matches);
    on();
    mql.addEventListener('change', on);
    return () => mql.removeEventListener('change', on);
  }, [query]);
  return matches;
}

const COLLAPSE_KEY = 'dwhcr.sidebar.collapsed';

export function AppShell() {
  const {theme, toggle} = useTheme();
  const {pathname} = useLocation();
  const navigate = useNavigate();
  const [collapsedPref, setCollapsedPref] = useState(() => safeStorageGet(COLLAPSE_KEY) === '1');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const isMobile = useMedia('(max-width: 767px)');
  const isNarrow = useMedia('(max-width: 1100px)');
  const collapsed = collapsedPref || isNarrow;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    document.title = `${titleFor(pathname)} · DWH Code Review`;
    setMobileOpen(false);
  }, [pathname]);

  const toggleCollapse = () => {
    const next = !collapsedPref;
    setCollapsedPref(next);
    safeStorageSet(COLLAPSE_KEY, next ? '1' : '0');
  };

  const mod = isMac() ? '⌘' : 'Ctrl';

  return (
    <div className="flex h-dvh overflow-hidden">
      {/* Ambient glow */}
      <div className="pointer-events-none fixed inset-x-0 top-0 -z-0 h-[420px] bg-[radial-gradient(ellipse_60%_100%_at_50%_-30%,color-mix(in_srgb,var(--color-accent)_9%,transparent),transparent_70%)]" />

      {!isMobile && (
        <div className="relative z-20 h-full shrink-0">
          <Sidebar collapsed={collapsed} onToggle={isNarrow ? undefined : toggleCollapse} />
        </div>
      )}
      {isMobile && mobileOpen && (
        <div className="fixed inset-0 z-50">
          <div className="absolute inset-0 animate-fade-in bg-black/50" onClick={() => setMobileOpen(false)} />
          <div className="relative h-full w-fit animate-slide-in">
            <Sidebar collapsed={false} mobile onNavigate={() => setMobileOpen(false)} />
          </div>
        </div>
      )}

      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="glass sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-line px-4 lg:px-6">
          {isMobile && (
            <Button variant="ghost" size="sm" iconOnly aria-label="Menü" onClick={() => setMobileOpen(true)}>
              <Menu className="size-4" />
            </Button>
          )}
          <div className="flex min-w-0 items-center gap-2 text-[13px]">
            <span className="hidden text-fg-subtle sm:inline">DWH Code Review</span>
            <span className="hidden text-fg-subtle/60 sm:inline">/</span>
            <span className="truncate font-medium text-fg">{titleFor(pathname)}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              data-tour="palette"
              onClick={() => setPaletteOpen(true)}
              className="group flex h-8 items-center gap-2 rounded-lg border border-line-strong bg-surface-2/60 pr-1.5 pl-2.5 text-[12.5px] text-fg-subtle transition-colors hover:border-fg-subtle/40 hover:text-fg-muted md:w-64"
            >
              <Search className="size-3.5" />
              <span className="hidden flex-1 text-left md:inline">Ara veya komut çalıştır…</span>
              <span className="hidden items-center gap-0.5 md:flex">
                <Kbd>{mod}</Kbd>
                <Kbd>K</Kbd>
              </span>
            </button>
            <Tooltip content="Tanıtım turu" side="bottom">
              <Button variant="ghost" size="md" iconOnly aria-label="Tanıtım turunu başlat" onClick={() => openTour()}>
                <CircleHelp className="size-4" />
              </Button>
            </Tooltip>
            <Tooltip content={theme === 'dark' ? 'Açık tema' : 'Koyu tema'} side="bottom">
              <Button variant="ghost" size="md" iconOnly aria-label="Temayı değiştir" onClick={toggle}>
                {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
              </Button>
            </Tooltip>
            {pathname !== '/analyses/new' && (
              <Button
                variant="primary"
                size="md"
                className="hidden sm:inline-flex"
                icon={<Play className="size-3.5 fill-current" />}
                onClick={() => navigate('/analyses/new')}
              >
                Yeni Analiz
              </Button>
            )}
          </div>
        </header>
        <main className={cn('min-h-0 flex-1 overflow-y-auto')} id="main">
          <div className="mx-auto w-full max-w-[2200px] px-4 py-6 lg:px-6 lg:py-7">
            <Outlet />
          </div>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <WelcomeTour />
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5">{eyebrow}</div>}
        <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-fg">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-[13px] text-fg-subtle">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
