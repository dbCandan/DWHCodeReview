import {Link, useNavigate} from 'react-router';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {CalendarClock, Database, GitCompare, Pencil, Play, Plus, Trash2} from 'lucide-react';
import {api} from '@/lib/api';
import {qk} from '@/hooks/queries';
import {formatDateTime, formatNumber} from '@/lib/format';
import {formatRunTime, ruleSelectionSummary} from '@/lib/schedules';
import type {ScheduledAnalysis, ScheduledAnalysisInput} from '@/types';
import {PageHeader} from '@/components/layout/AppShell';
import {Button, buttonClass} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {Switch} from '@/components/ui/Switch';
import {Table, THead, Th, Tr, Td} from '@/components/ui/Table';
import {Tooltip} from '@/components/ui/Tooltip';
import {EmptyState, ErrorState, SkeletonRows} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';
import {DiffCounts, RunStatusPill, scheduleError} from '@/components/schedules/ScheduleParts';

export const useSchedules = () => useQuery({queryKey: qk.schedules, queryFn: api.schedules.list, retry: false});

export function toScheduleInput(s: ScheduledAnalysis): ScheduledAnalysisInput {
  return {
    name: s.name,
    description: s.description ?? '',
    enabled: s.enabled,
    connection_id: s.connection_id,
    scope: {databases: s.scope?.databases ?? [], queries: s.scope?.queries ?? []},
    rule_selection: s.rule_selection ?? {mode: 'all_enabled', group_ids: [], rule_ids: []},
    schedule: s.schedule,
    incremental: s.incremental ?? true,
    first_run_full: s.first_run_full ?? true,
  };
}

/** Run-now / pause / delete actions shared by the list and the detail page. */
export function useScheduleActions() {
  const client = useQueryClient();
  const feedback = useFeedback();
  const refresh = (id?: number) => {
    client.invalidateQueries({queryKey: qk.schedules});
    if (id !== undefined) client.invalidateQueries({queryKey: qk.scheduleRuns(id)});
    client.invalidateQueries({queryKey: qk.analyses});
    client.invalidateQueries({queryKey: qk.dashboard});
  };
  const run = useMutation({
    mutationFn: (s: ScheduledAnalysis) => api.schedules.run(s.id),
    onSuccess: (r, s) => {
      refresh(s.id);
      if (r.status === 'skipped') feedback.info('Çalıştırma atlandı', r.reason ?? undefined);
      else if (r.status === 'failed') feedback.error('Çalıştırma başarısız', new Error(r.reason ?? 'Bilinmeyen hata'));
      else feedback.success('Çalıştırma başlatıldı', `${s.name}${r.analysis_id ? ` · Analiz #${r.analysis_id}` : ''}`);
    },
    onError: (e) => feedback.error('Çalıştırılamadı', scheduleError(e)),
  });
  const toggle = useMutation({
    mutationFn: (s: ScheduledAnalysis) => api.schedules.update(s.id, {...toScheduleInput(s), enabled: !s.enabled}),
    onSuccess: (s) => {
      refresh(s.id);
      feedback.success(s.enabled ? 'Zamanlama etkinleştirildi' : 'Zamanlama duraklatıldı', s.name);
    },
    onError: (e) => feedback.error('Güncellenemedi', scheduleError(e)),
  });
  const remove = useMutation({
    mutationFn: (s: ScheduledAnalysis) => api.schedules.remove(s.id),
    onSuccess: () => {
      refresh();
      feedback.success('Zamanlanmış analiz silindi', 'Oluşturulmuş analizler korunur.');
    },
    onError: (e) => feedback.error('Silinemedi', scheduleError(e)),
  });
  const confirmRemove = async (s: ScheduledAnalysis, after?: () => void) => {
    if (
      await feedback.confirm({
        title: `“${s.name}” silinsin mi?`,
        description: 'Zamanlama ve çalıştırma geçmişi silinir. Daha önce oluşturulan analizler Analizler sayfasında kalır. Bu işlem geri alınamaz.',
      })
    )
      remove.mutate(s, {onSuccess: after});
  };
  return {run, toggle, remove, confirmRemove};
}

export function SchedulesPage() {
  const list = useSchedules();
  const navigate = useNavigate();
  const {run, toggle, confirmRemove} = useScheduleActions();
  const items = list.data ?? [];

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Zamanlanmış analizler"
        description="Kapsamı ve kuralları bir kez tanımlayın; sistem belirlediğiniz periyotta yalnızca değişen veya yeni nesneleri analiz eder ve yeni/çözülen bulguları karşılaştırır."
        actions={
          <Link to="/schedules/new" className={buttonClass('primary')}>
            <Plus className="size-4" /> Zamanlanmış analiz oluştur
          </Link>
        }
      />
      <Card data-tour="schedules-table" className="overflow-hidden">
        {list.isPending ? (
          <SkeletonRows rows={4} />
        ) : list.isError ? (
          <ErrorState title="Zamanlanmış analizler yüklenemedi" error={scheduleError(list.error)} onRetry={() => list.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<CalendarClock />}
            title="Henüz zamanlanmış analiz yok"
            description="Örneğin her gece 02:00’de EDWDM’deki değişen prosedür ve view’ları tüm etkin kurallarla tarayan bir tanım oluşturun. Sonuçlar Analizler sayfasında birikir."
            action={
              <Link to="/schedules/new" className={buttonClass('primary', 'sm')}>
                <Plus className="size-3.5" /> Zamanlanmış analiz oluştur
              </Link>
            }
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th className="w-14">Etkin</Th>
                <Th>Ad · zamanlama</Th>
                <Th className="w-44">Sonraki çalıştırma</Th>
                <Th className="w-60">Son çalıştırma</Th>
                <Th className="hidden w-64 xl:table-cell">Kapsam · kurallar</Th>
                <Th className="w-28 text-right">İşlemler</Th>
              </tr>
            </THead>
            <tbody>
              {items.map((s) => (
                <Tr key={s.id} interactive onClick={() => navigate(`/schedules/${s.id}`)} className={s.enabled ? '' : 'opacity-70'}>
                  <Td onClick={(e) => e.stopPropagation()}>
                    <Switch size="sm" checked={s.enabled} onChange={() => toggle.mutate(s)} label={`${s.name} etkin`} />
                  </Td>
                  <Td className="max-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium text-fg">{s.name}</span>
                      {!s.enabled && <span className="shrink-0 rounded-md bg-surface-3 px-1.5 text-[11px] text-fg-muted ring-1 ring-line-strong ring-inset">Duraklatıldı</span>}
                    </div>
                    <div className="flex items-center gap-1.5 text-[11.5px] text-fg-muted">
                      <CalendarClock className="size-3 shrink-0 text-fg-subtle" />
                      {s.schedule_text}
                    </div>
                  </Td>
                  <Td>
                    {s.enabled && s.next_run_at ? (
                      <Tooltip content={formatDateTime(s.next_run_at)}>
                        <span className="text-[12.5px] text-fg">{formatRunTime(s.next_run_at)}</span>
                      </Tooltip>
                    ) : (
                      <span className="text-xs text-fg-subtle">—</span>
                    )}
                  </Td>
                  <Td>
                    {s.last_run ? (
                      <div className="flex flex-col gap-0.5">
                        <span className="flex items-center gap-2">
                          <RunStatusPill status={s.last_run.status} />
                          <span className="text-[11.5px] text-fg-subtle">{formatRunTime(s.last_run.started_at)}</span>
                        </span>
                        {s.last_run.status === 'completed' ? (
                          <span className="flex items-center gap-2 text-[12px] text-fg-muted">
                            <span className="font-semibold text-fg tnum">{formatNumber(s.last_run.finding_count)}</span> bulgu
                            <DiffCounts newCount={s.last_run.new_count} resolvedCount={s.last_run.resolved_count} />
                          </span>
                        ) : (
                          s.last_run.reason && <span className="truncate text-[11.5px] text-fg-subtle">{s.last_run.reason}</span>
                        )}
                      </div>
                    ) : (
                      <span className="text-xs text-fg-subtle">Henüz çalışmadı</span>
                    )}
                  </Td>
                  <Td className="hidden max-w-0 xl:table-cell">
                    <div className="flex items-center gap-1.5 truncate text-[12px] text-fg-muted">
                      <Database className="size-3 shrink-0 text-fg-subtle" />
                      <span className="truncate">
                        {s.connection_name} · {(s.scope?.databases ?? []).join(', ') || '—'}
                        {s.incremental ? ' · artımlı' : ' · tam tarama'}
                      </span>
                    </div>
                    <div className="truncate text-[11.5px] text-fg-subtle">
                      {(s.scope?.queries ?? []).length ? `${s.scope.queries.length} sorgu` : 'Tüm nesneler'} · {ruleSelectionSummary(s.rule_selection)}
                    </div>
                  </Td>
                  <Td className="text-right">
                    <div className="flex justify-end gap-0.5" onClick={(e) => e.stopPropagation()}>
                      <Tooltip content="Şimdi çalıştır">
                        <Button variant="ghost" size="xs" iconOnly aria-label="Şimdi çalıştır" loading={run.isPending && run.variables?.id === s.id} onClick={() => run.mutate(s)}>
                          <Play className="size-3.5" />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Farklar ve geçmiş">
                        <Button variant="ghost" size="xs" iconOnly aria-label="Geçmiş" onClick={() => navigate(`/schedules/${s.id}`)}>
                          <GitCompare className="size-3.5" />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Düzenle">
                        <Button variant="ghost" size="xs" iconOnly aria-label="Düzenle" onClick={() => navigate(`/schedules/${s.id}/edit`)}>
                          <Pencil className="size-3.5" />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Sil">
                        <Button variant="ghost" size="xs" iconOnly aria-label="Sil" className="hover:text-bad" onClick={() => confirmRemove(s)}>
                          <Trash2 className="size-3.5" />
                        </Button>
                      </Tooltip>
                    </div>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
