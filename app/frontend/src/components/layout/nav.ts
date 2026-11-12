import {CalendarClock, Database, History, LayoutDashboard, Layers, ListChecks, Play, Settings, type LucideIcon} from 'lucide-react';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  keywords: string;
  match: (pathname: string) => boolean;
}

export interface NavSection {
  title?: string;
  items: NavItem[];
}

export const NAV: NavSection[] = [
  {
    items: [
      {to: '/', label: 'Genel Bakış', icon: LayoutDashboard, keywords: 'dashboard ozet anasayfa', match: (p) => p === '/'},
    ],
  },
  {
    title: 'Analiz',
    items: [
      {to: '/analyses/new', label: 'Yeni Analiz', icon: Play, keywords: 'baslat calistir sihirbaz havuz', match: (p) => p === '/analyses/new'},
      {
        to: '/analyses',
        label: 'Analizler',
        icon: History,
        keywords: 'gecmis calismalar rapor bulgular',
        match: (p) => p.startsWith('/analyses') && p !== '/analyses/new',
      },
      {
        to: '/schedules',
        label: 'Zamanlanmış',
        icon: CalendarClock,
        keywords: 'zamanlama periyodik gece otomatik artimli cron',
        match: (p) => p.startsWith('/schedules'),
      },
    ],
  },
  {
    title: 'Kural Seti',
    items: [
      {to: '/rules', label: 'Kurallar', icon: ListChecks, keywords: 'regex llm kural', match: (p) => p.startsWith('/rules')},
      {to: '/rule-groups', label: 'Kural Grupları', icon: Layers, keywords: 'grup set', match: (p) => p.startsWith('/rule-groups')},
    ],
  },
  {
    title: 'Yapılandırma',
    items: [
      {to: '/connections', label: 'Bağlantılar', icon: Database, keywords: 'sql server sunucu veritabani', match: (p) => p.startsWith('/connections')},
      {to: '/settings', label: 'Ayarlar', icon: Settings, keywords: 'llm openai tema gorunum', match: (p) => p.startsWith('/settings')},
    ],
  },
];

export const NAV_ITEMS = NAV.flatMap((s) => s.items);

export function titleFor(pathname: string): string {
  if (/^\/analyses\/\d+/.test(pathname)) return 'Analiz detayı';
  if (pathname.startsWith('/rules/assistant')) return 'LLM ile kural oluştur';
  if (pathname === '/schedules/new') return 'Yeni zamanlanmış analiz';
  if (/^\/schedules\/\d+\/edit/.test(pathname)) return 'Zamanlanmış analizi düzenle';
  if (/^\/schedules\/\d+/.test(pathname)) return 'Zamanlanmış analiz';
  return NAV_ITEMS.find((i) => i.match(pathname))?.label ?? 'Sayfa bulunamadı';
}
