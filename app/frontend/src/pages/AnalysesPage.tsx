import {useMemo, useState} from 'react';
import {useNavigate} from 'react-router';
import {useMutation, useQueryClient} from '@tanstack/react-query';
import {CalendarClock, EyeOff, FileSearch, Play, Trash2} from 'lucide-react';
import {api} from '@/lib/api';
import {qk, useAnalyses} from '@/hooks/queries';
import {formatDateTime, formatDuration, formatNumber, isActiveStatus, matchesSearch, relativeTime} from '@/lib/format';
import type {AnalysisSummary, RunStatus} from '@/types';
import {PageHeader} from '@/components/layout/AppShell';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {SearchInput} from '@/components/ui/Input';
import {Segmented} from '@/components/ui/Tabs';
import {Table, THead, Th, Tr, Td} from '@/components/ui/Table';
import {StatusPill} from '@/components/ui/Badge';
import {SeverityBar, SeverityCountsInline} from '@/components/ui/Charts';
import {ProgressBar} from '@/components/ui/Progress';
import {Tooltip} from '@/components/ui/Tooltip';
import {EmptyState, ErrorState, SkeletonRows} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';

type Filter = 'all' | 'active' | 'completed' | 'problem';
const FILTERS: Record<Filter, (s: RunStatus) => boolean> = {
  all: () => true,
  active: (s) => s === 'queued' || s === 'running',
  completed: (s) => s === 'completed',
  problem: (s) => s === 'failed' || s === 'cancelled',
};

export function AnalysesPage() {
  const query = useAnalyses();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const client = useQueryClient();
  const feedback = useFeedback();

  const list = useMemo(
    () => (query.data ?? []).filter((a) => FILTERS[filter](a.status) && matchesSearch(q, a.name, a.connection_name, String(a.id))),
    [query.data, filter, q],
  );

  const remove = useMutation({
    mutationFn: (a: AnalysisSummary) => api.analyses.remove(a.id),
    onSuccess: () => {
      client.invalidateQueries({queryKey: qk.analyses});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success('Analiz silindi');
    },
    onError: (e) => feedback.error('Analiz silinemedi', e),
  });

  const onDelete = async (a: AnalysisSummary) => {
    if (
      await feedback.confirm({
        title: `“${a.name}” silinsin mi?`,
        description: `${formatNumber(a.finding_count)} bulgu ve saklanan nesne tanımları kalıcı olarak silinir. Bu işlem geri alınamaz.`,
      })
    )
      remove.mutate(a);
  };

  const count = (f: Filter) => (query.data ?? []).filter((a) => FILTERS[f](a.status)).length;

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Analizler"
        description="Tüm analiz çalışmaları; çalışan analizler canlı olarak güncellenir."
        actions={
          <Button variant="primary" icon={<Play className="size-3.5 fill-current" />} onClick={() => navigate('/analyses/new')}>
            Yeni Analiz
          </Button>
        }
      />
      <Card data-tour="analyses-table" className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <SearchInput value={q} onChange={setQ} placeholder="Ad, bağlantı veya #id ara…" className="w-full sm:w-72" />
          <Segmented
            value={filter}
            onChange={setFilter}
            options={[
              {value: 'all', label: `Tümü · ${count('all')}`},
              {value: 'active', label: `Çalışan · ${count('active')}`},
              {value: 'completed', label: `Tamamlanan · ${count('completed')}`},
              {value: 'problem', label: `Hatalı/İptal · ${count('problem')}`},
            ]}
          />
        </div>
        {query.isPending ? (
          <SkeletonRows rows={6} />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : (query.data ?? []).length === 0 ? (
          <EmptyState
            icon={<FileSearch />}
            title="Henüz analiz yok"
            description="Bir bağlantı seçin, nesne havuzunu oluşturun ve kurallarınızı çalıştırın."
            action={
              <Button variant="primary" icon={<Play className="size-3.5 fill-current" />} onClick={() => navigate('/analyses/new')}>
                İlk analizi başlat
              </Button>
            }
          />
        ) : list.length === 0 ? (
          <EmptyState compact icon={<FileSearch />} title="Eşleşen analiz yok" description="Arama veya durum filtresini değiştirin." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th className="min-w-64">Analiz</Th>
                <Th className="w-32">Durum</Th>
                <Th className="w-44">Kapsam</Th>
                <Th className="w-60">Bulgular</Th>
                <Th className="w-24 text-right">Süre</Th>
                <Th className="w-32">Oluşturuldu</Th>
                <Th className="w-12" />
              </tr>
            </THead>
            <tbody>
              {list.map((a) => (
                <Tr key={a.id} interactive onClick={() => navigate(`/analyses/${a.id}`)}>
                  <Td className="max-w-0">
                    <div className="flex items-start gap-2">
                      <span className="pt-px text-[11.5px] text-fg-subtle tnum">#{a.id}</span>
                      <span className="line-clamp-2 font-medium break-words text-fg" title={a.name}>{a.name}</span>
                      {a.schedule_id ? (
                        <Tooltip content={`Zamanlanmış: ${a.schedule_name ?? `#${a.schedule_id}`}`}>
                          <span className="flex shrink-0 text-accent" aria-label="Zamanlanmış analiz">
                            <CalendarClock className="size-3.5" />
                          </span>
                        </Tooltip>
                      ) : null}
                    </div>
                    <div className="truncate text-[11.5px] text-fg-subtle">{a.connection_name || '—'}</div>
                  </Td>
                  <Td>
                    <Tooltip content={a.error ?? undefined}>
                      <span>
                        <StatusPill status={a.status} />
                      </span>
                    </Tooltip>
                  </Td>
                  <Td className="text-xs whitespace-nowrap text-fg-muted tnum">
                    {formatNumber(a.object_count)} nesne × {formatNumber(a.rule_count)} kural
                    <div className="text-[11px] text-fg-subtle">{formatNumber(a.total_checks)} kontrol</div>
                  </Td>
                  <Td>
                    {isActiveStatus(a.status) ? (
                      <div className="flex items-center gap-2">
                        <ProgressBar value={a.completed_checks} max={a.total_checks} active size="sm" />
                        <span className="w-9 text-right text-[11px] text-fg-subtle tnum">
                          {a.total_checks ? Math.round((a.completed_checks / a.total_checks) * 100) : 0}%
                        </span>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[13px] font-semibold text-fg tnum">{formatNumber(a.finding_count)}</span>
                          <SeverityCountsInline counts={a.severity_counts} />
                        </div>
                        <SeverityBar counts={a.severity_counts} height={4} />
                        {(a.suppressed_count ?? 0) > 0 && (
                          <span className="flex items-center gap-1 text-[11px] text-fg-muted">
                            <EyeOff className="size-3" />
                            {formatNumber(a.suppressed_count ?? 0)} bulgu istisna nedeniyle gizlendi
                          </span>
                        )}
                      </div>
                    )}
                  </Td>
                  <Td className="text-right text-xs whitespace-nowrap text-fg-muted tnum">{formatDuration(a.duration_ms)}</Td>
                  <Td>
                    <Tooltip content={formatDateTime(a.created_at)}>
                      <span className="text-xs whitespace-nowrap text-fg-muted">{relativeTime(a.created_at)}</span>
                    </Tooltip>
                  </Td>
                  <Td onClick={(e) => e.stopPropagation()}>
                    <Button variant="ghost" size="xs" iconOnly aria-label="Sil" className="opacity-50 group-hover/row:opacity-100 hover:text-bad" onClick={() => onDelete(a)}>
                      <Trash2 className="size-3.5" />
                    </Button>
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
