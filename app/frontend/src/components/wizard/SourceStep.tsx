import {Link} from 'react-router';
import {useQuery} from '@tanstack/react-query';
import {Check, Database, Lock, Plus, Server} from 'lucide-react';
import {api} from '@/lib/api';
import {qk, useConnections} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {Card, CardHeader} from '@/components/ui/Card';
import {MultiSelect} from '@/components/ui/Select';
import {buttonClass} from '@/components/ui/Button';
import {Alert, EmptyState, ErrorState, Skeleton} from '@/components/ui/Feedback';

export function SourceStep({
  connectionId,
  onConnection,
  databases,
  onDatabases,
}: {
  connectionId: number | null;
  onConnection: (id: number) => void;
  databases: string[];
  onDatabases: (dbs: string[]) => void;
}) {
  const connections = useConnections();
  const dbs = useQuery({
    queryKey: qk.databases(connectionId ?? 0),
    queryFn: () => api.connections.databases(connectionId!),
    enabled: connectionId !== null,
    staleTime: 60_000,
  });

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader title="Bağlantı" description="Analiz edilecek SQL Server örneğini seçin." icon={<Server className="size-4" />} />
        <div className="p-4">
          {connections.isPending ? (
            <div className="grid gap-3 md:grid-cols-3">
              {Array.from({length: 3}).map((_, i) => (
                <Skeleton key={i} className="h-20 rounded-xl" />
              ))}
            </div>
          ) : connections.isError ? (
            <ErrorState error={connections.error} onRetry={() => connections.refetch()} />
          ) : connections.data.length === 0 ? (
            <EmptyState
              compact
              icon={<Database />}
              title="Henüz bağlantı yok"
              description="Analiz başlatmak için önce bir SQL Server bağlantısı ekleyin."
              action={
                <Link to="/connections?new=1" className={buttonClass('primary', 'sm')}>
                  <Plus className="size-3.5" /> Bağlantı ekle
                </Link>
              }
            />
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {connections.data.map((c) => {
                const on = c.id === connectionId;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => onConnection(c.id)}
                    aria-pressed={on}
                    className={cn(
                      'relative flex items-start gap-3 rounded-xl border p-3.5 text-left transition-all duration-150',
                      on ? 'border-accent bg-accent-soft ring-3 ring-accent/25' : 'border-line-control/60 bg-surface-2/40 hover:border-fg-subtle hover:bg-surface-2',
                    )}
                  >
                    <span
                      className={cn(
                        'flex size-9 shrink-0 items-center justify-center rounded-lg border',
                        on ? 'border-accent/40 bg-accent/15 text-accent' : 'border-line-strong bg-surface-3 text-fg-subtle',
                      )}
                    >
                      <Server className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-semibold text-fg">{c.name}</span>
                      <span className="block truncate font-mono text-[11.5px] text-fg-muted">
                        {c.server}:{c.port}
                      </span>
                      <span className="mt-1 flex items-center gap-1.5 text-[11px] text-fg-muted">
                        {c.username}
                        {c.encrypt && <Lock className="size-3" />}
                      </span>
                    </span>
                    {on && (
                      <span className="absolute top-2.5 right-2.5 flex size-5 items-center justify-center rounded-full bg-accent-solid text-white">
                        <Check className="size-3" strokeWidth={3} />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      <Card className={cn(connectionId === null && 'pointer-events-none opacity-60')}>
        <CardHeader
          title="Veritabanları"
          description="Bir veya birden fazla kullanıcı veritabanı seçin (sistem veritabanları listelenmez)."
          icon={<Database className="size-4" />}
          actions={databases.length > 0 && <span className="text-xs text-fg-subtle tnum">{databases.length} seçili</span>}
        />
        <div className="flex flex-col gap-3 p-4">
          {dbs.isError ? (
            <Alert tone="bad" title="Veritabanları alınamadı">
              {(dbs.error as Error).message}
            </Alert>
          ) : (
            <>
              <MultiSelect
                options={(dbs.data ?? []).map((d) => ({value: d, label: d}))}
                value={databases}
                onChange={onDatabases}
                loading={dbs.isFetching && !dbs.data}
                disabled={connectionId === null}
                placeholder={connectionId === null ? 'Önce bağlantı seçin' : 'Veritabanı seçin…'}
                searchPlaceholder="Veritabanı ara…"
                emptyText="Veritabanı bulunamadı"
              />
              {dbs.data && dbs.data.length > 0 && dbs.data.length <= 24 && (
                <div className="flex flex-wrap gap-1.5">
                  {dbs.data.map((d) => {
                    const on = databases.includes(d);
                    return (
                      <button
                        key={d}
                        type="button"
                        onClick={() => onDatabases(on ? databases.filter((x) => x !== d) : [...databases, d])}
                        className={cn(
                          'inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 font-mono text-[11.5px] transition-colors',
                          on ? 'border-accent bg-accent-soft font-semibold text-fg' : 'border-line-control bg-surface-2/50 text-fg-muted hover:border-fg-subtle hover:bg-surface-3 hover:text-fg',
                        )}
                        aria-pressed={on}
                      >
                        {on ? <Check className="size-3 text-accent" strokeWidth={3} /> : <Database className="size-3 text-fg-subtle" />}
                        {d}
                      </button>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
