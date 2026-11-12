import {Link, useLocation} from 'react-router';
import {PanelLeftClose, PanelLeftOpen} from 'lucide-react';
import {cn} from '@/lib/utils';
import {useHealth} from '@/hooks/queries';
import {Tooltip} from '@/components/ui/Tooltip';
import {NAV} from './nav';
import {BrandMark} from './BrandMark';

export function Sidebar({
  collapsed,
  onToggle,
  onNavigate,
  mobile,
}: {
  collapsed: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
  mobile?: boolean;
}) {
  const {pathname} = useLocation();
  const health = useHealth();
  const online = health.isSuccess;
  return (
    <aside
      className={cn(
        'flex h-full flex-col border-r border-line bg-surface/70 transition-[width] duration-200 ease-out',
        collapsed ? 'w-[60px]' : 'w-[232px]',
        mobile && 'w-[260px] bg-elevated shadow-pop',
      )}
    >
      <div className={cn('flex h-14 shrink-0 items-center gap-2.5 px-4', collapsed && 'justify-center px-0')}>
        <Link to="/" onClick={onNavigate} className="flex min-w-0 items-center gap-2.5 rounded-lg">
          <BrandMark />
          {!collapsed && (
            <span className="min-w-0 leading-tight">
              <span className="block truncate text-[13.5px] font-semibold tracking-[-0.01em] text-fg">DWH Code Review</span>
              <span className="block truncate text-[11px] text-fg-subtle">SQL Server statik analiz</span>
            </span>
          )}
        </Link>
      </div>

      <nav data-tour="nav" className="flex-1 overflow-y-auto px-2.5 pt-2 pb-4">
        {NAV.map((section, si) => (
          <div key={si} className={cn(si > 0 && 'mt-5')}>
            {section.title &&
              (collapsed ? (
                <div className="mx-auto mb-2 h-px w-6 bg-line-strong" />
              ) : (
                <div className="mb-1.5 px-2.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-fg-subtle">
                  {section.title}
                </div>
              ))}
            <ul className="flex flex-col gap-0.5">
              {section.items.map((item) => {
                const active = item.match(pathname);
                const Icon = item.icon;
                const link = (
                  <Link
                    to={item.to}
                    onClick={onNavigate}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'group relative flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium transition-colors duration-150',
                      collapsed && 'justify-center px-0',
                      active ? 'bg-surface-3/80 text-fg' : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
                    )}
                  >
                    {active && <span className="absolute top-1.5 bottom-1.5 left-0 w-[2px] rounded-full bg-accent shadow-[0_0_8px_var(--color-accent)]" />}
                    <Icon className={cn('size-4 shrink-0 transition-colors', active ? 'text-accent' : 'text-fg-subtle group-hover:text-fg-muted')} />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </Link>
                );
                return (
                  <li key={item.to}>
                    {collapsed ? (
                      <Tooltip content={item.label} side="right" delay={100}>
                        {link}
                      </Tooltip>
                    ) : (
                      link
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className={cn('flex shrink-0 items-center gap-2 border-t border-line p-2.5', collapsed && 'flex-col')}>
        <Tooltip
          content={online ? `Backend bağlı · v${health.data?.version ?? '?'}` : 'Backend yanıt vermiyor (127.0.0.1:8000)'}
          side={collapsed ? 'right' : 'top'}
        >
          <div className={cn('flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-[11.5px] text-fg-subtle', collapsed && 'justify-center px-0')}>
            <span className="relative flex size-2 shrink-0">
              {online && <span className="absolute inset-0 animate-ping rounded-full bg-ok/60" />}
              <span className={cn('relative size-2 rounded-full', online ? 'bg-ok' : health.isPending ? 'bg-fg-subtle' : 'bg-bad')} />
            </span>
            {!collapsed && (
              <span className="truncate">{online ? `Bağlı · v${health.data?.version}` : health.isPending ? 'Kontrol ediliyor…' : 'Backend çevrimdışı'}</span>
            )}
          </div>
        </Tooltip>
        {onToggle && (
          <Tooltip content={collapsed ? 'Menüyü genişlet' : 'Menüyü daralt'} side={collapsed ? 'right' : 'top'}>
            <button
              type="button"
              onClick={onToggle}
              aria-label={collapsed ? 'Menüyü genişlet' : 'Menüyü daralt'}
              className="flex size-7 items-center justify-center rounded-md text-fg-subtle transition-colors hover:bg-surface-2 hover:text-fg"
            >
              {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            </button>
          </Tooltip>
        )}
      </div>
    </aside>
  );
}
