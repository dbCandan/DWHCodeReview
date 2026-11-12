import {useMemo, useState, type ReactNode} from 'react';
import {Link} from 'react-router';
import {useQuery} from '@tanstack/react-query';
import {ArrowRight, BarChart3, Blocks, Bot, CalendarClock, Check, Database, FileSearch, ListChecks, Play, Regex, ScanSearch, Sparkles, TriangleAlert} from 'lucide-react';
import {api} from '@/lib/api';
import {qk, useAnalyses, useConnections, useLlmSettings, useRules} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {formatNumber, relativeTime} from '@/lib/format';
import {SEVERITY_VAR} from '@/lib/severity';
import {formatRunTime} from '@/lib/schedules';
import {shortModelName, trendAnalyses} from '@/lib/dashboard';
import type {AnalysisSummary, Dashboard} from '@/types';
import {Card, CardHeader} from '@/components/ui/Card';
import {buttonClass} from '@/components/ui/Button';
import {Donut, SeverityBar, SeverityLegend, Sparkline} from '@/components/ui/Charts';
import {SeverityBadge, StatusPill} from '@/components/ui/Badge';
import {EmptyState, ErrorState, Skeleton} from '@/components/ui/Feedback';
import {ProgressBar} from '@/components/ui/Progress';
import {Tooltip} from '@/components/ui/Tooltip';
import {FindingTrend, type TrendScale} from '@/components/dashboard/FindingTrend';
import {Segmented} from '@/components/ui/Tabs';

const TREND_SCALE_KEY = 'dwhcr.dashboard.trendScale';

export function DashboardPage() {
  const query = useQuery({
    queryKey: qk.dashboard,
    queryFn: api.dashboard,
    refetchInterval: (q) => (q.state.data?.recent_analyses.some((a) => a.status === 'running' || a.status === 'queued') ? 2000 : false),
  });
  const data = query.data;
  const fit = data !== undefined && !isFirstRun(data);

  return (
    // lg+: the overview fits the viewport (top bar 3.5rem + main padding 3.5rem); lists scroll inside their cards.
    <div className={cn('flex animate-fade-in flex-col', fit && 'lg:h-[calc(100dvh-3.5rem-3.5rem)]')}>
      {query.isPending ? (
        <DashboardSkeleton />
      ) : query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} title="Genel bakış yüklenemedi" />
        </Card>
      ) : data ? (
        <DashboardContent data={data} />
      ) : null}
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {Array.from({length: 5}).map((_, i) => (
          <Skeleton key={i} className="h-[92px] rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-72 rounded-xl lg:col-span-2" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    </div>
  );
}

function isFirstRun(data: Dashboard) {
  return data.connection_count === 0 || data.analysis_count === 0;
}

// ---------------------------------------------------------------------------------------------
// KPI tiles
// ---------------------------------------------------------------------------------------------

function Tile({to, label, icon, children, className}: {to: string; label: string; icon: ReactNode; children: ReactNode; className?: string}) {
  return (
    <Link
      to={to}
      className={cn(
        'group relative flex min-w-0 flex-col gap-1.5 overflow-hidden rounded-xl border border-line bg-surface px-4 py-3 shadow-card transition-colors hover:border-line-strong hover:bg-surface-2/50',
        className,
      )}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-medium text-fg-muted">{label}</span>
        <span className="flex text-fg-subtle transition-colors group-hover:text-fg-muted [&>svg]:size-3.5">{icon}</span>
      </span>
      {children}
    </Link>
  );
}

const Big = ({children, className}: {children: ReactNode; className?: string}) => (
  <span className={cn('text-[24px] leading-7 font-semibold tracking-[-0.02em] text-fg tnum', className)}>{children}</span>
);
const Sub = ({children, className}: {children: ReactNode; className?: string}) => (
  <span className={cn('block truncate text-[11.5px] text-fg-subtle', className)}>{children}</span>
);

function KpiRow({data}: {data: Dashboard}) {
  const analyses = useAnalyses();
  const rules = useRules();
  const llm = useLlmSettings();
  const connections = useConnections();
  const upcoming = data.upcoming_schedules;
  const schedules = useQuery({
    queryKey: qk.schedules,
    queryFn: api.schedules.list,
    enabled: upcoming !== undefined,
    retry: false,
    staleTime: 60_000,
  });

  const spark = useMemo(() => trendAnalyses(analyses.data ?? data.recent_analyses, 12).map((a) => a.finding_count), [analyses.data, data.recent_analyses]);
  const latest = (data.recent_analyses ?? [])[0];
  const kinds = useMemo(() => {
    const list = rules.data ?? [];
    return {regex: list.filter((r) => r.kind === 'regex').length, builtin: list.filter((r) => r.kind === 'builtin').length, llm: list.filter((r) => r.kind === 'llm').length};
  }, [rules.data]);
  const enabledSchedules = schedules.data ? schedules.data.filter((s) => s.enabled).length : (upcoming?.length ?? 0);
  const next = upcoming?.find((s) => s.next_run_at) ?? null;
  const critical = data.severity_counts?.critical ?? 0;

  return (
    <div data-tour="dashboard-kpis" className="grid shrink-0 grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Tile to="/analyses" label="Toplam bulgu" icon={<TriangleAlert />} className="col-span-2 md:col-span-1">
        <span className="flex items-baseline gap-2">
          <Big>{formatNumber(data.total_findings)}</Big>
          {critical > 0 ? (
            <span className="text-[12px] font-semibold text-sev-critical-fg tnum">{formatNumber(critical)} kritik</span>
          ) : (
            <span className="text-[12px] text-fg-subtle">kritik yok</span>
          )}
        </span>
        <SeverityBar counts={data.severity_counts} height={5} />
        <Sub>son 10 tamamlanmış analiz</Sub>
      </Tile>

      <Tile to="/analyses" label="Analizler" icon={<FileSearch />}>
        <span className="flex items-end justify-between gap-2">
          <Big>{formatNumber(data.analysis_count)}</Big>
          {spark.length > 1 && <Sparkline values={spark} width={84} height={26} />}
        </span>
        <Sub>{latest ? `son: ${relativeTime(latest.created_at)}` : 'henüz analiz yok'}</Sub>
      </Tile>

      <Tile to="/rules" label="Kural seti" icon={<ListChecks />}>
        <span className="flex items-baseline gap-2">
          <Big>{formatNumber(data.rule_count)}</Big>
          <span className="text-[12px] text-fg-muted">
            kural · <span className="tnum">{formatNumber(data.group_count)}</span> grup
          </span>
        </span>
        <span className="flex items-center gap-3 text-[11.5px] tnum">
          <Tooltip content="Regex kuralları">
            <span className="inline-flex items-center gap-1 text-fg-muted">
              <Regex className="size-3" /> {kinds.regex}
            </span>
          </Tooltip>
          <Tooltip content="Yerleşik kontroller">
            <span className="inline-flex items-center gap-1 text-builtin">
              <Blocks className="size-3" /> {kinds.builtin}
            </span>
          </Tooltip>
          <Tooltip content="LLM kuralları">
            <span className="inline-flex items-center gap-1 text-accent">
              <Sparkles className="size-3" /> {kinds.llm}
            </span>
          </Tooltip>
          <span className="ml-auto truncate text-fg-subtle">{formatNumber(data.enabled_rule_count)} etkin</span>
        </span>
      </Tile>

      <Tile to={upcoming?.length ? '/schedules' : '/schedules/new'} label="Zamanlanmış" icon={<CalendarClock />}>
        {upcoming === undefined || upcoming.length === 0 ? (
          <>
            <Big className="text-fg-subtle">—</Big>
            <Sub>
              Zamanlama yok · <span className="font-medium text-accent group-hover:underline">oluştur</span>
            </Sub>
          </>
        ) : (
          <>
            <span className="flex items-baseline gap-2">
              <Big>{formatNumber(enabledSchedules)}</Big>
              <span className="text-[12px] text-fg-muted">etkin</span>
            </span>
            <Sub className="text-fg-muted">
              sonraki: <span className="font-medium text-fg">{formatRunTime(next?.next_run_at)}</span>
              {next && <span className="text-fg-subtle"> · {next.name}</span>}
            </Sub>
          </>
        )}
      </Tile>

      <Tile to={llm.data && !llm.data.enabled ? '/settings' : '/connections'} label="Bağlantı / LLM" icon={<Database />}>
        <span className="flex items-baseline gap-2">
          <Big>{formatNumber(data.connection_count)}</Big>
          <span className="truncate text-[12px] text-fg-muted">{connections.data?.[0]?.name ?? 'bağlantı'}</span>
        </span>
        <span className="flex min-w-0 items-center gap-1.5 text-[11.5px]">
          <Bot className="size-3 shrink-0 text-fg-subtle" />
          {llm.data === undefined ? (
            <span className="text-fg-subtle">LLM durumu…</span>
          ) : llm.data.enabled ? (
            <>
              <span className="inline-flex items-center gap-1 font-medium text-ok">
                <span className="size-1.5 rounded-full bg-ok" /> Etkin
              </span>
              <span className="truncate font-mono text-fg-muted" title={llm.data.model}>
                {shortModelName(llm.data.model)}
              </span>
            </>
          ) : (
            <span className="inline-flex items-center gap-1 font-medium text-fg-muted">
              <span className="size-1.5 rounded-full bg-fg-subtle" /> LLM kapalı
            </span>
          )}
        </span>
      </Tile>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Main grid
// ---------------------------------------------------------------------------------------------

function DashboardContent({data}: {data: Dashboard}) {
  const firstRun = isFirstRun(data);
  const analyses = useAnalyses();
  const trend = useMemo(() => trendAnalyses(analyses.data ?? data.recent_analyses, 12), [analyses.data, data.recent_analyses]);
  const [trendScale, setTrendScaleState] = useState<TrendScale>(() => {
    try {
      return localStorage.getItem(TREND_SCALE_KEY) === 'log' ? 'log' : 'linear';
    } catch {
      return 'linear';
    }
  });
  const setTrendScale = (value: TrendScale) => {
    setTrendScaleState(value);
    try {
      localStorage.setItem(TREND_SCALE_KEY, value);
    } catch {
      /* storage unavailable: keep the choice for this session only */
    }
  };
  const recent = data.recent_analyses ?? [];
  const topRules = data.top_rules ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {firstRun && <Onboarding data={data} />}
      <KpiRow data={data} />

      <div className="grid gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.3fr)] lg:grid-rows-[minmax(0,0.8fr)_minmax(0,1fr)]">
        <Card className="flex min-w-0 flex-col lg:col-span-2 lg:min-h-0">
          <CardHeader
            icon={<BarChart3 className="size-4" />}
            title="Bulgu eğilimi"
            description={`Son ${trend.length || 12} tamamlanmış analiz · önem derecesine göre`}
            actions={
              <span className="flex items-center gap-3">
                <span className="hidden items-center gap-3 text-[11px] text-fg-muted xl:flex">
                  {(['critical', 'high', 'medium', 'low', 'info'] as const).map((s) => (
                    <span key={s} className="inline-flex items-center gap-1">
                      <span className="size-2 rounded-sm" style={{background: SEVERITY_VAR[s]}} />
                      {{critical: 'Kritik', high: 'Yüksek', medium: 'Orta', low: 'Düşük', info: 'Bilgi'}[s]}
                    </span>
                  ))}
                </span>
                <Segmented
                  size="sm"
                  value={trendScale}
                  onChange={setTrendScale}
                  options={[
                    {value: 'linear', label: 'Doğrusal'},
                    {value: 'log', label: 'Logaritmik'},
                  ]}
                />
              </span>
            }
          />
          {trend.length === 0 ? (
            <EmptyState compact icon={<BarChart3 />} title="Tamamlanmış analiz yok" description="Analizler tamamlandıkça bulgu sayıları burada çizilir." />
          ) : (
            <div className="h-64 px-3 pt-3 pb-2 lg:h-auto lg:min-h-0 lg:flex-1">
              <FindingTrend analyses={trend} scale={trendScale} />
            </div>
          )}
        </Card>

        <Card className="flex min-w-0 flex-col lg:col-start-3 lg:row-start-2 lg:min-h-0">
          <CardHeader
            title="Son analizler"
            actions={
              <Link to="/analyses" className={buttonClass('ghost', 'xs')}>
                Tümü <ArrowRight className="size-3" />
              </Link>
            }
          />
          {recent.length === 0 ? (
            <EmptyState
              compact
              icon={<ScanSearch />}
              title="Henüz analiz yok"
              action={
                <Link to="/analyses/new" className={buttonClass('primary', 'sm')}>
                  <Play className="size-3 fill-current" /> Analiz başlat
                </Link>
              }
            />
          ) : (
            <ul className="max-h-[420px] divide-y divide-line overflow-y-auto lg:max-h-none lg:min-h-0 lg:flex-1">
              {recent.map((a) => (
                <RecentAnalysisRow key={a.id} analysis={a} />
              ))}
            </ul>
          )}
        </Card>

        <Card className="flex min-w-0 flex-col lg:col-span-2 lg:col-start-1 lg:row-start-2 lg:min-h-0">
          <CardHeader title="En çok bulgu üreten kurallar" />
          {topRules.length === 0 ? (
            <EmptyState compact icon={<ListChecks />} title="Henüz bulgu yok" />
          ) : (
            <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
              <TopRules data={data} />
            </div>
          )}
        </Card>

        <Card className="flex min-w-0 flex-col lg:col-start-3 lg:row-start-1 lg:min-h-0">
          <CardHeader title="Önem dağılımı" description="Son 10 tamamlanmış analiz" />
          <div className="flex flex-1 items-center justify-center gap-6 p-4 lg:min-h-0 lg:overflow-hidden">
            <Donut counts={data.severity_counts} size={124} thickness={13} />
            <SeverityLegend counts={data.severity_counts} className="w-full max-w-56 min-w-36" />
          </div>
        </Card>
      </div>
    </div>
  );
}

function RecentAnalysisRow({analysis: a}: {analysis: AnalysisSummary}) {
  const active = a.status === 'running' || a.status === 'queued';
  return (
    <li>
      <Link to={`/analyses/${a.id}`} className="flex flex-col gap-1.5 px-4 py-2.5 transition-colors hover:bg-surface-2">
        <span className="flex items-center gap-2">
          <StatusPill status={a.status} className="h-5 px-1.5 text-[11px]" />
          {a.schedule_id ? <CalendarClock className="size-3 shrink-0 text-accent" aria-label="Zamanlanmış" /> : null}
          <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">{a.name}</span>
          <span className="shrink-0 text-[13px] font-semibold text-fg tnum">{formatNumber(a.finding_count)}</span>
        </span>
        <span className="flex items-center gap-3">
          <span className="w-24 shrink-0 truncate text-[11px] text-fg-subtle">{relativeTime(a.created_at)}</span>
          {active ? (
            <span className="flex flex-1 items-center gap-2">
              <ProgressBar value={a.completed_checks} max={a.total_checks} active size="sm" />
              <span className="text-[11px] text-fg-subtle tnum">{a.total_checks ? Math.round((a.completed_checks / a.total_checks) * 100) : 0}%</span>
            </span>
          ) : (
            <SeverityBar counts={a.severity_counts} height={4} className="flex-1" />
          )}
        </span>
      </Link>
    </li>
  );
}

function TopRules({data}: {data: Dashboard}) {
  const max = Math.max(...data.top_rules.map((r) => r.count), 1);
  return (
    <ol className="flex flex-col px-2 py-1.5">
      {data.top_rules.map((r, i) => (
        <li key={r.code} className="grid grid-cols-[16px_minmax(0,1fr)_auto] items-center gap-x-2.5 rounded-lg px-2 py-1.5 hover:bg-surface-2/60">
          <span className="text-[11px] font-medium text-fg-subtle tnum">{i + 1}</span>
          <span className="min-w-0">
            <span className="block font-mono text-[11px] font-semibold whitespace-nowrap text-fg-muted">{r.code}</span>
            <span className="block truncate text-[12px] text-fg" title={r.name}>
              {r.name}
            </span>
            <span className="mt-1 block h-1 overflow-hidden rounded-full bg-surface-3">
              <span className="block h-full rounded-full" style={{width: `${(r.count / max) * 100}%`, background: SEVERITY_VAR[r.severity]}} />
            </span>
          </span>
          <span className="flex items-center gap-1.5">
            <SeverityBadge severity={r.severity} compact />
            <span className="w-11 text-right text-[13px] font-semibold text-fg tnum">{formatNumber(r.count)}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function Onboarding({data}: {data: Dashboard}) {
  const steps = [
    {
      done: data.connection_count > 0,
      title: 'Bağlantı ekle',
      text: 'SQL Server sunucunuzun adresini ve kullanıcı bilgilerini girin, bağlantıyı test edin.',
      to: '/connections?new=1',
      cta: 'Bağlantı ekle',
      icon: <Database className="size-4" />,
    },
    {
      done: data.rule_count > 0 && data.connection_count > 0,
      title: 'Kuralları gözden geçir',
      text: 'Regex veya LLM tabanlı kuralları düzenleyin, gruplara ayırın ve canlı test edin.',
      to: '/rules',
      cta: 'Kurallara git',
      icon: <ListChecks className="size-4" />,
    },
    {
      done: data.analysis_count > 0,
      title: 'Analiz başlat',
      text: 'Nesne havuzunu oluşturun, kuralları seçin ve bulguları raporlayın.',
      to: '/analyses/new',
      cta: 'Analiz başlat',
      icon: <Play className="size-4" />,
    },
  ];
  const next = steps.findIndex((s) => !s.done);
  return (
    <Card className="relative overflow-hidden">
      <div className="hairline-top absolute inset-x-0 top-0 h-px" />
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 pt-4">
        <div>
          <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-fg">DWH Code Review’a hoş geldiniz</h2>
          <p className="mt-0.5 text-[12.5px] text-fg-subtle">Üç adımda ilk kod incelemenizi çalıştırın.</p>
        </div>
        <span className="text-xs text-fg-subtle tnum">
          {steps.filter((s) => s.done).length}/3 tamamlandı
        </span>
      </div>
      <ol className="grid gap-3 p-5 md:grid-cols-3">
        {steps.map((s, i) => {
          const current = i === next;
          return (
            <li
              key={s.title}
              className={cn(
                'relative flex flex-col rounded-xl border p-4 transition-colors',
                current ? 'border-accent/40 bg-accent-soft/50' : 'border-line bg-surface-2/40',
              )}
            >
              <div className="flex items-center gap-2.5">
                <span
                  className={cn(
                    'flex size-7 items-center justify-center rounded-full border text-xs font-semibold',
                    s.done
                      ? 'border-ok/40 bg-ok-soft text-ok'
                      : current
                        ? 'border-accent-solid bg-accent-solid text-white animate-pulse-ring'
                        : 'border-line-strong text-fg-subtle',
                  )}
                >
                  {s.done ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
                </span>
                <span className="text-[13px] font-semibold text-fg">{s.title}</span>
              </div>
              <p className="mt-2 flex-1 text-[12.5px] leading-5 text-fg-muted">{s.text}</p>
              <Link to={s.to} className={cn(buttonClass(current ? 'primary' : 'secondary', 'sm'), 'mt-3 self-start')}>
                {s.icon}
                {s.cta}
              </Link>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
