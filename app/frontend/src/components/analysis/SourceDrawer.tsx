import {useMemo, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {FileCode2, MessageSquareText} from 'lucide-react';
import {api} from '@/lib/api';
import {qk} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {findingsToMarks} from '@/lib/findings';
import {compareSeverity} from '@/lib/severity';
import {splitLines} from '@/lib/sql';
import type {AnalysisObject} from '@/types';
import {Drawer} from '@/components/ui/Overlay';
import {SeverityBadge, TypeBadge} from '@/components/ui/Badge';
import {Switch} from '@/components/ui/Switch';
import {EmptyState, ErrorState, Skeleton} from '@/components/ui/Feedback';
import {SqlViewer} from './SqlViewer';

export function SourceDrawer({
  analysisId,
  object,
  initialLine,
  onClose,
}: {
  analysisId: number;
  object: AnalysisObject | null;
  initialLine?: number | null;
  onClose: () => void;
}) {
  const [focus, setFocus] = useState<number | null>(initialLine ?? null);
  const [notes, setNotes] = useState(true);
  const query = useQuery({
    queryKey: qk.source(analysisId, object?.id ?? 0),
    queryFn: () => api.analyses.source(analysisId, object!.id),
    enabled: !!object,
  });
  const findings = useMemo(
    () => [...(query.data?.findings ?? [])].sort((a, b) => (a.line ?? 0) - (b.line ?? 0) || compareSeverity(a.severity, b.severity)),
    [query.data],
  );
  const marks = useMemo(() => findingsToMarks(findings), [findings]);
  const lineCount = query.data?.definition ? splitLines(query.data.definition).length : object?.line_count;
  const noLine = findings.filter((f) => !f.line);

  return (
    <Drawer
      open={!!object}
      onClose={onClose}
      width="max-w-[1180px]"
      title={
        object ? (
          <span className="flex items-center gap-2">
            <FileCode2 className="size-4 text-fg-subtle" />
            <span className="truncate font-mono text-[14px]">
              {object.database}.{object.schema}.<span className="text-fg">{object.name}</span>
            </span>
          </span>
        ) : (
          ''
        )
      }
      description={
        object && (
          <span className="flex items-center gap-2">
            <TypeBadge type={object.type} full />
            <span className="tnum">{lineCount ?? '—'} satır</span>·<span className="tnum">{findings.length} bulgu</span>
          </span>
        )
      }
      headerExtra={
        <label className="mr-2 hidden items-center gap-2 text-xs text-fg-muted sm:flex">
          <MessageSquareText className="size-3.5" />
          Satır içi açıklamalar
          <Switch size="sm" checked={notes} onChange={setNotes} />
        </label>
      }
    >
      {query.isPending ? (
        <div className="flex flex-col gap-2 p-5">
          {Array.from({length: 14}).map((_, i) => (
            <Skeleton key={i} className="h-3.5" />
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} title="Kaynak yüklenemedi" />
      ) : !query.data?.definition ? (
        <EmptyState icon={<FileCode2 />} title="Tanım mevcut değil" description={object?.error ?? 'Nesnenin tanımı okunamadı (şifreli olabilir).'} />
      ) : (
        <div className="grid h-full min-h-0 lg:grid-cols-[minmax(0,1fr)_300px]">
          <SqlViewer source={query.data.definition} marks={marks} focusLine={focus} showNotes={notes} className="h-full min-h-0" />
          <aside className="flex min-h-0 flex-col border-t border-line bg-canvas/50 lg:border-t-0 lg:border-l">
            <div className="border-b border-line px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">
              Bulgular · {findings.length}
            </div>
            <ul className="min-h-0 flex-1 overflow-y-auto p-2">
              {findings.length === 0 && <li className="px-3 py-8 text-center text-xs text-fg-subtle">Bu nesnede bulgu yok</li>}
              {findings.map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    disabled={!f.line}
                    onClick={() => setFocus(f.line)}
                    className={cn(
                      'flex w-full flex-col gap-1 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-surface-2',
                      focus === f.line && f.line && 'bg-surface-2 ring-1 ring-line-strong',
                    )}
                  >
                    <span className="flex items-center gap-1.5">
                      <SeverityBadge severity={f.severity} compact />
                      <span className="font-mono text-[11.5px] font-semibold text-fg">{f.rule_code}</span>
                      <span className="ml-auto font-mono text-[11px] text-fg-subtle tnum">{f.line ? `L${f.line}` : 'nesne'}</span>
                    </span>
                    <span className="line-clamp-2 text-xs text-fg-muted">{f.message || f.rule_name}</span>
                  </button>
                </li>
              ))}
            </ul>
            {noLine.length > 0 && (
              <p className="border-t border-line px-4 py-2 text-[11px] text-fg-subtle">{noLine.length} bulgu nesne geneline ait (satır yok).</p>
            )}
          </aside>
        </div>
      )}
    </Drawer>
  );
}
