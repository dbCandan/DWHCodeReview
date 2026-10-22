import {useEffect, useRef, type ComponentType} from 'react';
import {Link, Navigate, useParams} from 'react-router';
import {RoleRoute} from '@/components/auth/RoleRoute';
import {Icon, type IconName} from '@/components/ui/Icon';
import {EmbeddedPage, PageHeader} from '@/components/ui/PageHeader';
import {useAuth} from '@/contexts/AuthContext';
import {
  LlmCallsPage,
  LlmConnectionPage,
  RulesPage,
  ScheduledReviewSettingsPage,
  SqlConnectionPage,
  UserAdministrationPage,
} from '@/generated/lazyPages';
import {useAppNavigation} from '@/contexts/NavigationContext';
import type {AdminSectionId} from '@/lib/navigation';
import {useResource} from '@/hooks/useResource';
import type {AccessRequirement} from '@/lib/access';
import {formatNumber} from '@/lib/format';
import {ConnectionService} from '@/services/connections';
import {RuleSetService} from '@/services/ruleSet';
import {ScheduledReviewService} from '@/services/scheduledReviews';

const SECTIONS: Record<AdminSectionId, {page: ComponentType; require: AccessRequirement}> = {
  kurallar: {page: RulesPage, require: 'manageRules'},
  sql: {page: SqlConnectionPage, require: 'manageRules'},
  llm: {page: LlmConnectionPage, require: 'manageRules'},
  'llm-cagrilari': {page: LlmCallsPage, require: 'manageRules'},
  zamanlama: {page: ScheduledReviewSettingsPage, require: 'administerUsers'},
  kullanicilar: {page: UserAdministrationPage, require: 'administerUsers'},
};

function isSection(value: string | undefined): value is AdminSectionId {
  return value !== undefined && Object.hasOwn(SECTIONS, value);
}

/**
 * Yönetim: every administration screen on one page. A row of tabs lists the sections this user
 * may open; the chosen section fills the rest, and without a choice "Genel durum" shows the health
 * of the system. Each section is the same page as before, shown with a second-level heading, so
 * its behaviour and its backend checks stay unchanged.
 */
export default function AdminPage() {
  return (
    <RoleRoute require="manageRules">
      <AdminLayout />
    </RoleRoute>
  );
}

function AdminLayout() {
  const {section} = useParams();
  const {adminSections} = useAppNavigation();
  const tabs = useRef<HTMLElement>(null);
  // On a narrow screen the tabs scroll sideways; keep the chosen one in view.
  useEffect(() => {
    tabs.current?.querySelector<HTMLElement>('[aria-current="page"]')?.scrollIntoView?.({block: 'nearest', inline: 'nearest'});
  }, [section, adminSections.length]);
  if (section !== undefined && !isSection(section)) return <Navigate to="/yonetim" replace />;
  const current = section !== undefined && isSection(section) ? section : null;
  const Page = current ? SECTIONS[current].page : null;

  return (
    <div className="page page-fill admin">
      <PageHeader title="Yönetim" description="Kurallar, bağlantılar, zamanlama ve kullanıcılar tek yerde." />
      <nav ref={tabs} className="admin-tabs" aria-label="Yönetim bölümleri">
        <Link to="/yonetim" aria-current={current === null ? 'page' : undefined}>
          <Icon name="grid" />
          <span>Genel durum</span>
        </Link>
        {adminSections.map((item) => (
          <Link key={item.id} to={`/yonetim/${item.id}`} aria-current={current === item.id ? 'page' : undefined}>
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>
      <div className="admin-panel">
        {current && Page ? (
          <RoleRoute require={SECTIONS[current].require}>
            <EmbeddedPage host="Yönetim">
              <Page />
            </EmbeddedPage>
          </RoleRoute>
        ) : (
          <Overview />
        )}
      </div>
    </div>
  );
}

type Health = 'ok' | 'warn' | 'unknown';

interface HealthCard {
  key: string;
  to: string;
  icon: IconName;
  label: string;
  value: string;
  text: string;
  health: Health;
}

/** The system at a glance: one card per moving part; each opens its section. */
function Overview() {
  const {access} = useAuth();
  const sql = useResource('admin:sql', (signal) => ConnectionService.sql(signal));
  const llm = useResource('admin:llm', (signal) => ConnectionService.llm(signal));
  const rules = useResource('admin:rules', (signal) => RuleSetService.latest(signal));
  const email = useResource(access.administerUsers ? 'scheduled-review-email' : null, (signal) =>
    ScheduledReviewService.emailStatus(signal),
  );

  const llmReady = llm.data ? Boolean(llm.data.base_url || llm.data.chat_url) : null;
  const mailReady = email.data
    ? email.data.scheduler_enabled && email.data.smtp_configured && email.data.allowed_domains.length > 0
    : null;
  const ruleCount = rules.data ? rules.data.critical_count + rules.data.normal_count : null;

  const cards: HealthCard[] = [
    {
      key: 'rules',
      to: '/yonetim/kurallar',
      icon: 'book',
      label: 'Kurallar',
      value: rules.data ? `Sürüm ${rules.data.number}` : rules.status === 'error' ? 'Yayımlanmadı' : '…',
      text: ruleCount !== null ? `${formatNumber(ruleCount)} kural, ${formatNumber(rules.data!.groups.length)} grup` : 'İncelemeler yayımlanmış sürümle çalışır.',
      health: rules.data ? 'ok' : rules.status === 'error' ? 'warn' : 'unknown',
    },
    {
      key: 'sql',
      to: sql.data?.editable ? '/yonetim/sql' : '/yonetim',
      icon: 'database',
      label: 'SQL Server',
      value: sql.data ? (sql.data.configured ? 'Bağlı' : 'Yapılandırılmadı') : '…',
      text: sql.data?.managed_by === 'deployment' ? 'Dağıtım tarafından sağlanıyor.' : 'Nesne listeleri buradan okunur.',
      health: sql.data ? (sql.data.configured ? 'ok' : 'warn') : 'unknown',
    },
    {
      key: 'llm',
      to: llm.data?.editable ? '/yonetim/llm' : '/yonetim/llm-cagrilari',
      icon: 'sparkles',
      label: 'LLM',
      value: llmReady === null ? '…' : llmReady ? llm.data!.model : 'Adres yok',
      text: 'İncelemeler kurum içi LLM ucuna gider.',
      health: llmReady === null ? 'unknown' : llmReady ? 'ok' : 'warn',
    },
    ...(access.administerUsers
      ? [
          {
            key: 'mail',
            to: '/yonetim/zamanlama',
            icon: 'mail' as const,
            label: 'E-posta',
            value: mailReady === null ? '…' : mailReady ? 'Hazır' : 'Yapılandırılmadı',
            text: 'Zamanlanmış incelemelerin özeti e-postayla gider.',
            health: (mailReady === null ? 'unknown' : mailReady ? 'ok' : 'warn') as Health,
          },
        ]
      : []),
  ];

  return (
    <div className="page">
      <h2 className="sr-only">Genel durum</h2>
      <section aria-label="Sistem durumu" className="health-grid">
        {cards.map((card) => (
          <Link key={card.key} to={card.to} className={`health-card is-${card.health}`}>
            <span className="health-key">
              <Icon name={card.icon} />
              {card.label}
            </span>
            <strong className="health-value truncate">{card.value}</strong>
            <span className="health-text">{card.text}</span>
          </Link>
        ))}
      </section>
    </div>
  );
}
