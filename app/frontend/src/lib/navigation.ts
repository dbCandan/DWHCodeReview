import type {IconName} from '@/components/ui/Icon';

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  /** Address prefixes that belong to this item (it is the current page on any of them). */
  match: string[];
}

/** A block of the side menu: the daily work, then the super admin's Yönetim; a line parts them. */
export interface NavGroup {
  items: NavItem[];
}

export type AdminSectionId = 'kurallar' | 'sql' | 'llm' | 'llm-cagrilari' | 'zamanlama' | 'kullanicilar';

export interface AdminSection {
  id: AdminSectionId;
  label: string;
  icon: IconName;
  summary: string;
}

export interface AppNavigation {
  /** The side menu, in order; a group without items is left out. */
  groups: NavGroup[];
  /** The sections of the Yönetim page this user may open; empty when it offers nothing. */
  adminSections: AdminSection[];
}

/** Whether `pathname` belongs to `item`; the home item matches only itself. */
export function isCurrent(item: Pick<NavItem, 'match'>, pathname: string): boolean {
  return item.match.some((prefix) =>
    prefix === '/' ? pathname === '/' : pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
