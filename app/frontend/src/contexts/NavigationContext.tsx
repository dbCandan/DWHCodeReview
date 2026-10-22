import {createContext, useContext, type ReactNode} from 'react';
import {useAuth} from '@/contexts/AuthContext';
import {useConnectionMenu} from '@/hooks/useConnectionMenu';
import type {AdminSection, AppNavigation, NavGroup, NavItem} from '@/lib/navigation';

const NavigationContext = createContext<AppNavigation | null>(null);

/** Computes the navigation once for the signed-in layout; pages below read it from context. */
export function NavigationProvider({children}: {children: ReactNode}) {
  const navigation = useNavigationModel(true);
  return <NavigationContext.Provider value={navigation}>{children}</NavigationContext.Provider>;
}

/**
 * The role-aware destinations of the application. Hiding a destination is not authorization;
 * every page's data comes from role-checked endpoints.
 */
export function useAppNavigation(): AppNavigation {
  const shared = useContext(NavigationContext);
  const own = useNavigationModel(shared === null);
  return shared ?? own;
}

function useNavigationModel(enabled: boolean): AppNavigation {
  const {access} = useAuth();
  const connections = useConnectionMenu(enabled && access.manageRules);

  const adminSections: AdminSection[] = [
    ...(access.manageRules
      ? [{id: 'kurallar' as const, label: 'Kurallar', icon: 'pencil' as const, summary: 'Kural taslağını ve grupları düzenleyin, yayımlayın.'}]
      : []),
    ...(access.manageRules && connections.sql
      ? [{id: 'sql' as const, label: 'SQL bağlantısı', icon: 'plug' as const, summary: 'Nesne listelerinin okunduğu SQL Server bağlantısı.'}]
      : []),
    ...(access.manageRules && connections.llm
      ? [{id: 'llm' as const, label: 'LLM bağlantısı', icon: 'sparkles' as const, summary: 'İncelemelerin gönderildiği kurum içi LLM ucu.'}]
      : []),
    ...(access.manageRules
      ? [{id: 'llm-cagrilari' as const, label: 'LLM çağrıları', icon: 'activity' as const, summary: 'Çağrı özetleri, süreler ve hatalar.'}]
      : []),
    ...(access.administerUsers
      ? [{id: 'zamanlama' as const, label: 'Zamanlama ve e-posta', icon: 'clock' as const, summary: 'Eşzamanlı koşum sınırı, e-posta durumu ve deneme e-postası.'}]
      : []),
    ...(access.administerUsers
      ? [{id: 'kullanicilar' as const, label: 'Kullanıcılar', icon: 'users' as const, summary: 'Roller, hesap durumları ve oturumlar.'}]
      : []),
  ];

  const work: NavItem[] = [
    {to: '/', label: 'Ana sayfa', icon: 'home', match: ['/']},
    ...(access.review
      ? [
          {to: '/inceleme', label: 'Nesne incelemesi', icon: 'database' as const, match: ['/inceleme']},
          {to: '/sql-inceleme', label: 'SQL betiği', icon: 'code' as const, match: ['/sql-inceleme']},
          {to: '/zamanlanmis-incelemeler', label: 'Zamanlanmış', icon: 'clock' as const, match: ['/zamanlanmis-incelemeler']},
          {to: '/gecmis', label: 'Geçmiş', icon: 'history' as const, match: ['/gecmis']},
          {to: '/yayimlanmis-kurallar', label: 'Kural kitaplığı', icon: 'book' as const, match: ['/yayimlanmis-kurallar']},
        ]
      : []),
  ];
  // Every administration screen lives on the one Yönetim page.
  const admin: NavItem[] =
    adminSections.length > 0 ? [{to: '/yonetim', label: 'Yönetim', icon: 'sliders', match: ['/yonetim']}] : [];

  const groups: NavGroup[] = [{items: work}, {items: admin}].filter((group) => group.items.length > 0);

  return {groups, adminSections};
}
