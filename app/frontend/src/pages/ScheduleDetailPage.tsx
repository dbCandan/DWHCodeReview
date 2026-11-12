import {Fragment, useMemo, useState} from 'react';
import {Link, useNavigate, useParams} from 'react-router';
import {useQuery} from '@tanstack/react-query';
import {
  ArrowLeft,
  CalendarClock,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Database,
  ExternalLink,
  GitCompare,
  History,
  Pause,
  Pencil,
  Play,
  Plus,
  Trash2,
  TrendingUp,
} from 'lucide-react';
import {api} from '@/lib/api';
import {qk} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {formatDateTime, formatDuration, formatNumber} from '@/lib/format';
import {formatRunTime, RUN_TRIGGER_LABEL, ruleSelectionSummary, runDurationMs} from '@/lib/schedules';
import type {RunDiffFinding, ScheduledRun} from '@/types';
import {PageHeader} from '@/components/layout/AppShell';
import {Button, buttonClass} from '@/components/ui/Button';
import {Card, CardHeader} from '@/components/ui/Card';
import {Stat} from '@/components/ui/Stat';
import {SeverityBadge} from '@/components/ui/Badge';
import {Tabs} from '@/components/ui/Tabs';
import {Table, THead, Th, Tr, Td} from '@/components/ui/Table';
import {EmptyState, ErrorState, Skeleton, SkeletonRows} from '@/components/ui/Feedback';
import {QueryChips} from '@/components/wizard/PoolStep';
import {DiffCounts, RunStatusPill, RunTrend, scheduleError} from '@/components/schedules/ScheduleParts';
import {useScheduleActions} from './SchedulesPage';

function DiffList({items, empty}: {items: RunDiffFinding[]; empty: string}) {
  if (!items.length) return <p className="px-4 py-6 text-center text-xs text-fg-subtle">{empty}</p>;
  return (
    <ul className="divide-y divide-line">
      {items.map((f, i) => (
        <li key={`${f.finding_id ?? 'x'}-${i}`} className="flex items-start gap-3 px-4 py-2">
          <SeverityBadge severity={f.severity} className="mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 text-[12px]">
              <span className="font-mono font-semibold text-fg">{f.rule_code}</span>
              <span className="truncate text-fg-muted">{f.rule_name}</span>
            </div>
            <div className="flex items-center gap-2 font-mono text-[11.5px]">
              <span className="truncate text-fg-muted">{f.object_label}</span>
              <span className="shrink-0 rounded bg-surface-3 px-1 text-fg-muted tnum">{f.line ? `L${f.line}` : '—'}</span>
            </div>
            <code className="mt-0.5 block truncate rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11.5px] text-fg">{f.snippet || '—'}</code>
            {f.message && <p className="mt-0.5 truncate text-[11.5px] text-fg-subtle">{f.message}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function RunDiffPanel({run}: {run: ScheduledRun}) {
  const [tab, setTab] = useState<'new' | 'resolved'>(run.new_count || !run.resolved_count ? 'new' : 'resolved');
  const diff = useQuery({queryKey: qk.runDiff(run.id), queryFn: () => api.schedules.diff(run.id), retry: false});
  return (
    <div className="ml-8 overflow-hidden rounded-lg border border-line-strong bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-line pr-3">
        <Tabs
          className="border-b-0 px-2"
          value={tab}
          onChange={setTab}
          items={[
            {id: 'new', label: 'Yeni', count: diff.data?.new.length ?? run.new_count},
            {id: 'resolved', label: 'Çözülen', count: diff.data?.resolved.length ?? run.resolved_count},
          ]}
        />
        {diff.data && <span className="text-[11.5px] text-fg-subtle">{formatNumber(diff.data.compared_objects)} nesne karşılaştırıldı</span>}
      </div>
      {diff.isPending ? (
        <SkeletonRows rows={3} />
      ) : diff.isError ? (
        <p className="px-4 py-4 text-xs text-fg-muted">Farklar yüklenemedi: {scheduleError(diff.error).message}</p>
      ) : (
        <div className="max-h-96 overflow-y-auto">
          <DiffList
            items={tab === 'new' ? diff.data.new : diff.data.resolved}
            empty={tab === 'new' ? 'Önceki çalıştırmalara göre yeni bulgu yok.' : 'Çözülen bulgu yok.'}
          />
        </div>
      )}
    </div>
  );
}

export function ScheduleDetailPage() {
  const {id} = useParams();
  const scheduleId = Number(id);
  const navigate = useNavigate();
  const {run, toggle, confirmRemove} = useScheduleActions();
  const schedule = useQuery({queryKey: qk.schedule(scheduleId), queryFn: () => api.schedules.get(scheduleId), retry: false});
  const runs = useQuery({
    queryKey: qk.scheduleRuns(scheduleId),
    queryFn: () => api.schedules.runs(scheduleId, 50),
    retry: false,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'running') ? 3000 : false),
  });
  const [open, setOpen] = useState<number | null>(null);

  const kpi = useMemo(() => {
    const list = runs.data ?? [];
    const since = Date.now() - 30 * 86_400_000;
    const recent = list.filter((r) => new Date(r.started_at).getTime() >= since && r.status === 'completed');
    const lastDone = list.find((r) => r.status === 'completed');
    return {
      total: list.length,
      lastFindings: lastDone?.finding_count ?? null,
      newSum: recent.reduce((a, r) => a + r.new_count, 0),
      resolvedSum: recent.reduce((a, r) => a + r.resolved_count, 0),
    };
  }, [runs.data]);

  if (schedule.isPending)
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-20 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  if (schedule.isError)
    return (
      <Card>
        <ErrorState title="Zamanlanmış analiz yüklenemedi" error={scheduleError(schedule.error)} onRetry={() => schedule.refetch()} />
      </Card>
    );
  const s = schedule.data;

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow={
          <Link to="/schedules" className="inline-flex items-center gap-1 text-xs text-fg-subtle hover:text-fg">
            <ArrowLeft className="size-3.5" /> Zamanlanmış analizler
          </Link>
        }
        title={
          <span className="flex items-center gap-2.5">
            {s.name}
            {!s.enabled && <span className="rounded-md bg-surface-3 px-1.5 py-0.5 text-[12px] font-medium text-fg-muted ring-1 ring-line-strong ring-inset">Duraklatıldı</span>}
          </span>
        }
        description={
          <span className="flex flex-col gap-1">
            {s.description && <span>{s.description}</span>}
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-fg-muted">
              <span className="inline-flex items-center gap-1.5">
                <CalendarClock className="size-3.5" /> {s.schedule_text}
              </span>
              <span>
                Sonraki: <span className="text-fg">{s.enabled ? formatRunTime(s.next_run_at) : 'duraklatıldı'}</span>
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Database className="size-3.5" /> {s.connection_name} · {(s.scope?.databases ?? []).join(', ')}
              </span>
              <span>{s.incremental ? 'Artımlı' : 'Tam tarama'}</span>
              <span>{ruleSelectionSummary(s.rule_selection)}</span>
            </span>
          </span>
        }
        actions={
          <>
            <Button icon={s.enabled ? <Pause className="size-4" /> : <Play className="size-4" />} loading={toggle.isPending} onClick={() => toggle.mutate(s)}>
              {s.enabled ? 'Duraklat' : 'Etkinleştir'}
            </Button>
            <Link to={`/schedules/${s.id}/edit`} className={buttonClass('secondary')}>
              <Pencil className="size-4" /> Düzenle
            </Link>
            <Button variant="ghost" iconOnly aria-label="Sil" className="hover:text-bad" onClick={() => confirmRemove(s, () => navigate('/schedules'))}>
              <Trash2 className="size-4" />
            </Button>
            <Button variant="primary" icon={<Play className="size-4 fill-current" />} loading={run.isPending} onClick={() => run.mutate(s)}>
              Şimdi çalıştır
            </Button>
          </>
        }
      />

      <div className="mb-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Son bulgu sayısı" value={kpi.lastFindings ?? '—'} icon={<CircleCheck />} hint={s.last_run_at ? formatRunTime(s.last_run_at) : 'Henüz çalışmadı'} />
          <Stat label="Toplam çalıştırma" value={kpi.total} icon={<History />} hint={s.watermark_at ? `Taban: ${formatDateTime(s.watermark_at)}` : 'Karşılaştırma tabanı yok'} />
          <Stat label="Son 30 gün yeni" value={kpi.newSum} icon={<Plus />} hint="önceki çalıştırmalara göre" />
          <Stat label="Son 30 gün çözülen" value={kpi.resolvedSum} icon={<GitCompare />} hint="analiz edilen nesnelerde" />
        </div>
        <Card>
          <CardHeader icon={<TrendingUp className="size-4" />} title="Trend" />
          {runs.data ? <RunTrend runs={runs.data} /> : <Skeleton className="m-4 h-28" />}
        </Card>
      </div>

      {(s.scope?.queries ?? []).length > 0 && (
        <Card className="mb-4 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Kapsam sorguları</p>
          <div className="mt-1.5 flex flex-col gap-1.5">
            {s.scope.queries.map((q, i) => (
              <QueryChips key={i} query={q} />
            ))}
          </div>
        </Card>
      )}

      <Card className="overflow-hidden">
        <CardHeader icon={<History className="size-4" />} title="Çalıştırma geçmişi" description="Satıra tıklayınca önceki çalıştırmalara göre yeni ve çözülen bulgular açılır." />
        {runs.isPending ? (
          <SkeletonRows rows={4} />
        ) : runs.isError ? (
          <ErrorState title="Çalıştırmalar yüklenemedi" error={scheduleError(runs.error)} onRetry={() => runs.refetch()} />
        ) : runs.data.length === 0 ? (
          <EmptyState compact icon={<History />} title="Henüz çalıştırma yok" description="İlk çalıştırma zamanlamaya göre başlar; hemen denemek için “Şimdi çalıştır”." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th className="w-8 pr-0" />
                <Th className="w-44">Zaman</Th>
                <Th className="w-24">Tetikleyici</Th>
                <Th className="w-32">Durum</Th>
                <Th className="w-32 text-right">Nesne (değişen/toplam)</Th>
                <Th className="w-20 text-right">Bulgu</Th>
                <Th className="w-48">Fark</Th>
                <Th className="w-24 text-right">Süre</Th>
                <Th className="w-28 text-right" />
              </tr>
            </THead>
            <tbody>
              {runs.data.map((r) => {
                const expandable = r.status === 'completed';
                const isOpen = open === r.id;
                return (
                  <Fragment key={r.id}>
                    <Tr interactive={expandable} selected={isOpen} onClick={() => expandable && setOpen(isOpen ? null : r.id)}>
                      <Td className="pr-0">
                        {expandable ? isOpen ? <ChevronDown className="size-3.5 text-fg-subtle" /> : <ChevronRight className="size-3.5 text-fg-subtle" /> : null}
                      </Td>
                      <Td>
                        <span className="text-[12.5px] text-fg" title={formatDateTime(r.started_at)}>
                          {formatRunTime(r.started_at)}
                        </span>
                      </Td>
                      <Td className="text-xs text-fg-muted">{RUN_TRIGGER_LABEL[r.trigger] ?? r.trigger}</Td>
                      <Td>
                        <RunStatusPill status={r.status} />
                        {r.reason && <span className="mt-0.5 block max-w-56 truncate text-[11px] text-fg-subtle" title={r.reason}>{r.reason}</span>}
                      </Td>
                      <Td className="text-right text-xs text-fg-muted tnum">
                        <span className="font-semibold text-fg">{formatNumber(r.changed_object_count)}</span> / {formatNumber(r.object_count)}
                      </Td>
                      <Td className={cn('text-right text-[13px] font-semibold tnum', r.finding_count ? 'text-fg' : 'text-fg-subtle')}>{r.status === 'completed' ? formatNumber(r.finding_count) : '—'}</Td>
                      <Td>{r.status === 'completed' ? <DiffCounts newCount={r.new_count} resolvedCount={r.resolved_count} /> : <span className="text-xs text-fg-subtle">—</span>}</Td>
                      <Td className="text-right text-xs whitespace-nowrap text-fg-muted tnum">{formatDuration(runDurationMs(r))}</Td>
                      <Td className="text-right" onClick={(e) => e.stopPropagation()}>
                        {r.analysis_id ? (
                          <Link to={`/analyses/${r.analysis_id}`} className={buttonClass('ghost', 'xs')}>
                            Analizi aç <ExternalLink className="size-3" />
                          </Link>
                        ) : null}
                      </Td>
                    </Tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={9} className="border-b border-line bg-surface-2/30 px-4 py-3">
                          <RunDiffPanel run={r} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
