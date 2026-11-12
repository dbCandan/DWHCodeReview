import {useEffect, useMemo, useRef, useState} from 'react';
import {Link, useNavigate, useParams} from 'react-router';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {
  ArrowLeft,
  Ban,
  Boxes,
  Calendar,
  CircleAlert,
  Database,
  EyeOff,
  FileDown,
  FileText,
  ListChecks,
  ScanSearch,
  Timer,
  Trash2,
  TriangleAlert,
} from 'lucide-react';
import {api, ApiError} from '@/lib/api';
import {qk} from '@/hooks/queries';
import {formatDateTime, formatDuration, formatNumber, isActiveStatus} from '@/lib/format';
import {buttonClass, Button} from '@/components/ui/Button';
import {Card, CardHeader} from '@/components/ui/Card';
import {Stat} from '@/components/ui/Stat';
import {StatusPill} from '@/components/ui/Badge';
import {Donut, SeverityLegend} from '@/components/ui/Charts';
import {Tabs} from '@/components/ui/Tabs';
import {Alert, EmptyState, ErrorState, Skeleton} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';
import {ExecutionPanel} from '@/components/analysis/ExecutionPanel';
import {FindingsTab, ObjectsTab, RulesTab} from '@/components/analysis/AnalysisTabs';
import {SourceDrawer} from '@/components/analysis/SourceDrawer';
import {ScheduledAnalysisBanner} from '@/components/schedules/ScheduleParts';
import type {AnalysisDetail, AnalysisObject} from '@/types';
import {describeQuery, type PoolQueryLog} from '@/lib/wizard';

type Tab = 'findings' | 'objects' | 'rules';

export function AnalysisDetailPage() {
  const id = Number(useParams().id);
  const query = useQuery({
    queryKey: qk.analysis(id),
    queryFn: () => api.analyses.get(id),
    enabled: Number.isFinite(id),
    refetchInterval: (q) => (isActiveStatus(q.state.data?.status) ? 1000 : false),
  });

  if (!Number.isFinite(id)) return <NotFoundAnalysis />;
  if (query.isPending) return <DetailSkeleton />;
  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) return <NotFoundAnalysis />;
    return (
      <Card>
        <ErrorState error={query.error} onRetry={() => query.refetch()} title="Analiz yüklenemedi" />
      </Card>
    );
  }
  return <Detail analysis={query.data} />;
}

function NotFoundAnalysis() {
  return (
    <Card>
      <EmptyState
        icon={<ScanSearch />}
        title="Analiz bulunamadı"
        description="Bu analiz silinmiş olabilir."
        action={
          <Link to="/analyses" className={buttonClass('secondary')}>
            Analizlere dön
          </Link>
        }
      />
    </Card>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-8 w-80" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({length: 4}).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-96 rounded-xl" />
    </div>
  );
}

function Detail({analysis: a}: {analysis: AnalysisDetail}) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const feedback = useFeedback();
  const active = isActiveStatus(a.status);
  const [tab, setTab] = useState<Tab>('findings');
  const [source, setSource] = useState<{object: AnalysisObject; line: number | null} | null>(null);

  const findings = useQuery({
    queryKey: qk.findings(a.id),
    queryFn: () => api.analyses.findings(a.id),
    refetchInterval: active ? 2500 : false,
  });

  // When the run finishes: refresh everything that depends on it and announce it.
  const previous = useRef(a.status);
  useEffect(() => {
    const was = previous.current;
    previous.current = a.status;
    if (isActiveStatus(was) && !isActiveStatus(a.status)) {
      client.invalidateQueries({queryKey: qk.findings(a.id)});
      client.invalidateQueries({queryKey: qk.analyses});
      client.invalidateQueries({queryKey: qk.dashboard});
      if (a.status === 'completed') feedback.success('Analiz tamamlandı', `${formatNumber(a.finding_count)} bulgu · ${formatDuration(a.duration_ms)}`);
      else if (a.status === 'failed') feedback.error('Analiz başarısız oldu', a.error ?? undefined);
      else if (a.status === 'cancelled') feedback.info('Analiz iptal edildi');
    }
  }, [a.status, a.id, a.finding_count, a.duration_ms, a.error, client, feedback]);

  const cancel = useMutation({
    mutationFn: () => api.analyses.cancel(a.id),
    onSuccess: () => client.invalidateQueries({queryKey: qk.analysis(a.id)}),
    onError: (e) => feedback.error('İptal edilemedi', e),
  });
  const remove = useMutation({
    mutationFn: () => api.analyses.remove(a.id),
    onSuccess: () => {
      client.removeQueries({queryKey: qk.analysis(a.id)});
      client.invalidateQueries({queryKey: qk.analyses});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success('Analiz silindi');
      navigate('/analyses');
    },
    onError: (e) => feedback.error('Analiz silinemedi', e),
  });

  const onCancel = async () => {
    if (
      await feedback.confirm({
        title: 'Analiz iptal edilsin mi?',
        description: 'O ana kadar üretilen bulgular korunur; kalan kontroller çalıştırılmaz.',
        confirmLabel: 'İptal et',
      })
    )
      cancel.mutate();
  };
  const onDelete = async () => {
    if (
      await feedback.confirm({
        title: `“${a.name}” silinsin mi?`,
        description: 'Tüm bulgular ve saklanan nesne tanımları kalıcı olarak silinir. Bu işlem geri alınamaz.',
      })
    )
      remove.mutate();
  };

  const objectsById = useMemo(() => new Map(a.objects.map((o) => [o.id, o])), [a.objects]);
  const errorObjects = a.objects.filter((o) => o.status === 'error').length;
  const findingList = findings.data ?? [];

  return (
    <div className="flex animate-fade-in flex-col gap-4">
      <div>
        <Link to="/analyses" className="inline-flex items-center gap-1.5 text-xs text-fg-subtle transition-colors hover:text-fg">
          <ArrowLeft className="size-3.5" /> Analizler
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="truncate text-[22px] font-semibold tracking-[-0.02em] text-fg">{a.name}</h1>
              <StatusPill status={a.status} />
              <span className="text-xs text-fg-subtle tnum">#{a.id}</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-subtle">
              <span className="flex items-center gap-1.5">
                <Database className="size-3.5" />
                <span className="text-fg-muted">{a.connection_name || '—'}</span>
              </span>
              <span className="flex items-center gap-1.5">
                <Calendar className="size-3.5" /> Oluşturuldu <span className="text-fg-muted">{formatDateTime(a.created_at)}</span>
              </span>
              {a.started_at && (
                <span>
                  Başladı <span className="text-fg-muted">{formatDateTime(a.started_at)}</span>
                </span>
              )}
              {a.finished_at && (
                <span>
                  Bitti <span className="text-fg-muted">{formatDateTime(a.finished_at)}</span>
                </span>
              )}
              {a.duration_ms !== null && (
                <span className="flex items-center gap-1.5">
                  <Timer className="size-3.5" />
                  <span className="text-fg-muted tnum">{formatDuration(a.duration_ms)}</span>
                </span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {active ? (
              <Button icon={<Ban className="size-3.5" />} loading={cancel.isPending} onClick={onCancel}>
                İptal et
              </Button>
            ) : (
              <>
                <a href={api.analyses.reportHtmlUrl(a.id)} target="_blank" rel="noreferrer" className={buttonClass('secondary')}>
                  <FileText className="size-3.5" /> Rapor (HTML)
                </a>
                <a href={api.analyses.reportCsvUrl(a.id)} download className={buttonClass('secondary')}>
                  <FileDown className="size-3.5" /> CSV
                </a>
              </>
            )}
            <Button variant="ghost" iconOnly aria-label="Analizi sil" className="hover:text-bad" onClick={onDelete} disabled={remove.isPending}>
              <Trash2 className="size-4" />
            </Button>
          </div>
        </div>
      </div>

      {a.schedule_id ? <ScheduledAnalysisBanner scheduleId={a.schedule_id} scheduleName={a.schedule_name ?? null} runId={a.schedule_run_id ?? null} /> : null}

      {a.status === 'failed' && a.error && (
        <Alert tone="bad" title="Analiz başarısız oldu">
          {a.error}
        </Alert>
      )}

      {active && <ExecutionPanel analysis={a} onOpenObject={(o) => setSource({object: o, line: null})} />}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-2 2xl:grid-cols-4">
          <Stat label="Nesne" value={a.object_count} icon={<Boxes />} hint={errorObjects ? <span className="text-bad">{errorObjects} nesnede hata</span> : 'Havuzdaki nesneler'} />
          <Stat label="Kural" value={a.rule_count} icon={<ListChecks />} hint={`${a.rules.filter((r) => r.kind === 'llm').length} LLM kuralı`} />
          <Stat
            label="Kontrol"
            value={a.total_checks}
            icon={<ScanSearch />}
            hint={active ? `${formatNumber(a.completed_checks)} tamamlandı` : 'nesne × uygulanabilir kural'}
          />
          <Stat
            label="Bulgu"
            value={a.finding_count}
            icon={<TriangleAlert />}
            hint={
              <>
                {a.severity_counts.critical ? <span className="text-sev-critical-fg">{a.severity_counts.critical} kritik</span> : 'Kritik bulgu yok'}
                {(a.suppressed_count ?? 0) > 0 && (
                  <span className="mt-0.5 flex items-center gap-1 text-fg-muted">
                    <EyeOff className="size-3" />
                    {formatNumber(a.suppressed_count ?? 0)} bulgu istisna nedeniyle gizlendi
                  </span>
                )}
              </>
            }
          />
        </div>
        <Card>
          <div className="flex items-center gap-5 p-4">
            <Donut counts={a.severity_counts} size={116} thickness={12} />
            <SeverityLegend counts={a.severity_counts} className="max-w-xs flex-1" />
          </div>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <Tabs
          className="px-2"
          value={tab}
          onChange={setTab}
          items={[
            {id: 'findings', label: 'Bulgular', count: findingList.length},
            {id: 'objects', label: 'Nesneler', count: a.objects.length},
            {id: 'rules', label: 'Kurallar', count: a.rules.length},
          ]}
        />
        {findings.isError && tab !== 'objects' && (
          <div className="p-3">
            <Alert tone="bad" title="Bulgular yüklenemedi" action={<Button size="xs" onClick={() => findings.refetch()}>Tekrar dene</Button>}>
              {(findings.error as Error).message}
            </Alert>
          </div>
        )}
        {tab === 'findings' && (
          <FindingsTab
            analysis={a}
            findings={findingList}
            loading={findings.isPending}
            onOpenSource={(objectId, line) => {
              const object = objectsById.get(objectId);
              if (object) setSource({object, line});
            }}
          />
        )}
        {tab === 'objects' && <ObjectsTab analysis={a} onOpen={(o) => setSource({object: o, line: null})} />}
        {tab === 'rules' && <RulesTab analysis={a} findings={findingList} />}
      </Card>

      {!active && Object.keys(a.filters ?? {}).length > 0 && <FiltersCard filters={a.filters} />}

      <SourceDrawer
        key={source ? `${source.object.id}-${source.line}` : 'none'}
        analysisId={a.id}
        object={source?.object ?? null}
        initialLine={source?.line}
        onClose={() => setSource(null)}
      />
    </div>
  );
}

function FiltersCard({filters}: {filters: Record<string, unknown>}) {
  const databases = Array.isArray(filters.databases) ? (filters.databases as string[]) : [];
  const queries = Array.isArray(filters.queries) ? (filters.queries as PoolQueryLog[]) : [];
  return (
    <Card>
      <CardHeader icon={<CircleAlert className="size-4" />} title="Havuz filtreleri" description="Nesne havuzu oluşturulurken kullanılan sorgular. Her sorgudaki filtreler VE (AND) ile birleşir." />
      <div className="space-y-2 px-4 pb-4">
        {databases.length > 0 && (
          <div className="text-xs text-fg-muted">
            Veritabanları: <span className="font-medium text-fg">{databases.join(', ')}</span>
          </div>
        )}
        {queries.length === 0 && <div className="text-xs text-fg-muted">Kayıtlı sorgu yok.</div>}
        {queries.map((q, i) => {
          const parts = describeQuery(q);
          return (
            <div key={i} className="flex flex-wrap items-center gap-1.5 rounded-lg border border-line bg-surface-2/50 px-3 py-2 text-xs">
              <span className="mr-1 font-medium text-fg">Sorgu {i + 1}</span>
              {(parts.length ? parts : ['Filtre yok (tüm nesneler)']).map((p) => (
                <span key={p} className="rounded-md border border-line px-1.5 py-0.5 text-fg-muted">{p}</span>
              ))}
              <span className="ml-auto tabular-nums text-fg-muted">
                {q.matched} eşleşti · {q.added} eklendi
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
