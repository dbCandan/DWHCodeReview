import {useMemo, useState} from 'react';
import {useMutation, useQuery} from '@tanstack/react-query';
import {Boxes, ChevronDown, Filter, Inbox, Info, ListPlus, RotateCcw, Search, Trash2, X} from 'lucide-react';
import {api} from '@/lib/api';
import {qk} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {formatDate, formatNumber, matchesSearch, OBJECT_TYPE_LABEL, OBJECT_TYPES, relativeTime} from '@/lib/format';
import {objectKey, sortObjects, type SortDir, type SortKey} from '@/lib/pool';
import {buildObjectQuery, describeQuery, EMPTY_FILTER, type FilterForm} from '@/lib/wizard';
import type {DbObject, ObjectQuery} from '@/types';
import {Card, CardHeader} from '@/components/ui/Card';
import {Button} from '@/components/ui/Button';
import {Field, Input, SearchInput} from '@/components/ui/Input';
import {MultiSelect} from '@/components/ui/Select';
import {Chip} from '@/components/ui/Tabs';
import {Checkbox} from '@/components/ui/Switch';
import {Pagination, SortTh, Table, THead, Th, Tr, Td} from '@/components/ui/Table';
import {TypeBadge} from '@/components/ui/Badge';
import {Tooltip} from '@/components/ui/Tooltip';
import {Alert, EmptyState, SkeletonRows} from '@/components/ui/Feedback';

const PAGE_SIZE = 50;

export interface PoolStepProps {
  connectionId: number;
  databases: string[];
  filter: FilterForm;
  onFilter: (f: FilterForm) => void;
  pool: DbObject[];
  onAdd: (items: DbObject[], query: ObjectQuery, matched: number) => void;
  onRemove: (keys: string[]) => void;
  onClear: () => void;
}

/** Object-query filter fields (schemas, name, types, dates). Shared by the New Analysis pool and the schedule scope editor. */
export function FilterFields({
  connectionId,
  databases,
  filter,
  onFilter,
}: {
  connectionId: number;
  databases: string[];
  filter: FilterForm;
  onFilter: (f: FilterForm) => void;
}) {
  const set = <K extends keyof FilterForm>(k: K, v: FilterForm[K]) => onFilter({...filter, [k]: v});
  const schemas = useQuery({
    queryKey: qk.schemas(connectionId, databases),
    queryFn: () => api.connections.schemas(connectionId, databases),
    enabled: connectionId > 0 && databases.length > 0,
    staleTime: 60_000,
  });
  const schemaOptions = useMemo(
    () =>
      (schemas.data ?? []).map((s) => ({
        value: `${s.database}.${s.schema}`,
        label: s.schema,
        group: databases.length > 1 ? s.database : undefined,
        hint: formatNumber(s.object_count),
      })),
    [schemas.data, databases.length],
  );
  return (
    <>
      <Field label="Şemalar" hint={schemas.isError ? undefined : 'Boş = tüm şemalar'} error={schemas.isError ? (schemas.error as Error).message : undefined}>
        <MultiSelect
          options={schemaOptions}
          value={filter.schemas}
          onChange={(v) => set('schemas', v)}
          loading={schemas.isFetching && !schemas.data}
          allLabel="Tüm şemalar"
          searchPlaceholder="Şema ara…"
          emptyText="Şema bulunamadı"
        />
      </Field>
      <Field label="Nesne adı içerir">
        <Input value={filter.search} onChange={(e) => set('search', e.target.value)} placeholder="örn. usp_Load" leading={<Search className="size-3.5" />} />
      </Field>
      <Field label="Nesne tipleri" className="md:col-span-2" hint={filter.types.length ? undefined : 'Hiçbiri seçili değilse tüm tipler listelenir.'}>
        <div className="flex flex-wrap gap-1.5">
          {OBJECT_TYPES.map((t) => {
            const on = filter.types.includes(t);
            return (
              <Chip key={t} active={on} onClick={() => set('types', on ? filter.types.filter((x) => x !== t) : [...filter.types, t])}>
                {OBJECT_TYPE_LABEL[t]}
              </Chip>
            );
          })}
        </div>
      </Field>
      <Field label="Oluşturma tarihi">
        <DateRange from={filter.created_from} to={filter.created_to} onFrom={(v) => set('created_from', v)} onTo={(v) => set('created_to', v)} />
      </Field>
      <Field label="Değişiklik tarihi">
        <DateRange from={filter.modified_from} to={filter.modified_to} onFrom={(v) => set('modified_from', v)} onTo={(v) => set('modified_to', v)} />
      </Field>
    </>
  );
}

export function PoolStep({connectionId, databases, filter, onFilter, pool, onAdd, onRemove, onClear}: PoolStepProps) {
  const [results, setResults] = useState<{items: DbObject[]; total: number; query: ObjectQuery} | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<{key: SortKey; dir: SortDir}>({key: 'name', dir: 'asc'});
  const [page, setPage] = useState(0);
  const [resultQ, setResultQ] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false); // collapsed by default; the header shows a summary + Listele

  const list = useMutation({
    mutationFn: (query: ObjectQuery) => api.connections.objects(connectionId, query).then((r) => ({...r, query})),
    onSuccess: (r) => {
      setResults(r);
      setSelected(new Set());
      setPage(0);
      setResultQ('');
      setFiltersOpen(false); // make room for the results; the header keeps a summary + Listele
    },
  });
  const runList = () => list.mutate(buildObjectQuery(databases, filter));
  const activeFilters = describeQuery(buildObjectQuery(databases, filter)).filter((p) => !p.startsWith('Veritabanı'));

  const poolKeys = useMemo(() => new Set(pool.map(objectKey)), [pool]);
  const visibleAll = useMemo(() => {
    if (!results) return [];
    const filtered = results.items.filter((o) => matchesSearch(resultQ, o.schema, o.name, o.database));
    return sortObjects(filtered, sort.key, sort.dir);
  }, [results, resultQ, sort]);
  const pageCount = Math.ceil(visibleAll.length / PAGE_SIZE);
  const pageItems = visibleAll.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const selectable = (o: DbObject) => !poolKeys.has(objectKey(o));
  const pageSelectable = pageItems.filter(selectable);
  const allPageSelected = pageSelectable.length > 0 && pageSelectable.every((o) => selected.has(objectKey(o)));
  const somePageSelected = pageSelectable.some((o) => selected.has(objectKey(o)));
  const newInResults = results ? results.items.filter(selectable).length : 0;

  const onSort = (key: SortKey) => setSort((s) => ({key, dir: s.key === key && s.dir === 'asc' ? 'desc' : 'asc'}));
  const toggle = (o: DbObject) =>
    setSelected((s) => {
      const n = new Set(s);
      const k = objectKey(o);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });

  const addSelected = () => {
    if (!results) return;
    const items = results.items.filter((o) => selected.has(objectKey(o)));
    onAdd(items, results.query, results.total);
    setSelected(new Set());
  };
  const addAll = () => {
    if (!results) return;
    onAdd(visibleAll, results.query, results.total);
    setSelected(new Set());
  };

  const filterCount =
    filter.schemas.length +
    filter.types.length +
    [filter.created_from, filter.created_to, filter.modified_from, filter.modified_to, filter.search.trim()].filter(Boolean).length;

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-4">
        <Card className="overflow-hidden">
          <div
            role="button"
            tabIndex={0}
            aria-expanded={filtersOpen}
            onClick={() => setFiltersOpen((o) => !o)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setFiltersOpen((o) => !o);
              }
            }}
            className={cn(
              'flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2/50',
              filtersOpen && 'border-b border-line',
            )}
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-line-strong bg-surface-2 text-fg-muted">
              <Filter className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-[13px] font-semibold text-fg">
                Filtreler
                {filterCount > 0 && (
                  <span className="rounded-full bg-accent-soft px-1.5 text-[11px] font-semibold text-accent tnum">{filterCount}</span>
                )}
              </p>
              {filtersOpen ? (
                <p className="flex items-center gap-1.5 text-[11.5px] text-fg-subtle">
                  <Info className="size-3" /> Tüm filtreler VE (AND) ile birleştirilir; boş bırakılan filtre uygulanmaz.
                </p>
              ) : (
                <div className="mt-1 flex flex-wrap gap-1">
                  {activeFilters.length === 0 ? (
                    <span className="text-[11.5px] text-fg-subtle">Filtre yok · {databases.length} veritabanındaki tüm nesneler</span>
                  ) : (
                    activeFilters.map((p) => (
                      <span key={p} className="rounded-md border border-line-control bg-surface-2 px-1.5 py-0.5 text-[11px] text-fg-muted">
                        {p}
                      </span>
                    ))
                  )}
                </div>
              )}
            </div>
            <span className="flex shrink-0 items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
              {filterCount > 0 && (
                <Button variant="ghost" size="sm" icon={<RotateCcw className="size-3.5" />} onClick={() => onFilter(EMPTY_FILTER)}>
                  Sıfırla
                </Button>
              )}
              {!filtersOpen && (
                <Button size="sm" variant="primary" loading={list.isPending} icon={<Search className="size-3.5" />} onClick={runList}>
                  Listele
                </Button>
              )}
            </span>
            <ChevronDown className={cn('size-4 shrink-0 text-fg-subtle transition-transform', filtersOpen && 'rotate-180')} />
          </div>
          {filtersOpen && (
          <form
            className="grid gap-4 p-4 md:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              runList();
            }}
          >
            <FilterFields connectionId={connectionId} databases={databases} filter={filter} onFilter={onFilter} />
            <div className="flex flex-wrap items-center gap-2 md:col-span-2">
              <Button type="submit" variant="primary" loading={list.isPending} icon={<Search className="size-3.5" />}>
                Listele
              </Button>
              <span className="text-xs text-fg-subtle">
                {databases.length} veritabanında arama yapılacak{filterCount ? ` · ${filterCount} filtre` : ''}
              </span>
            </div>
          </form>
          )}
        </Card>

        <Card className="overflow-hidden">
          <CardHeader
            icon={<Boxes className="size-4" />}
            title="Sonuçlar"
            description={
              results
                ? results.total > results.items.length
                  ? `${formatNumber(results.total)} eşleşme · ilk ${formatNumber(results.items.length)} listelendi`
                  : `${formatNumber(results.total)} eşleşme · ${formatNumber(newInResults)} tanesi havuzda değil`
                : 'Filtreleri ayarlayıp “Listele”ye basın.'
            }
            actions={
              results &&
              results.items.length > 0 && (
                <>
                  <Button size="sm" disabled={!selected.size} icon={<ListPlus className="size-3.5" />} variant={selected.size ? 'primary' : 'secondary'} onClick={addSelected}>
                    Havuza ekle{selected.size ? ` (${formatNumber(selected.size)})` : ''}
                  </Button>
                  <Button size="sm" variant="ghost" disabled={!newInResults} onClick={addAll}>
                    {resultQ ? 'Görünenleri' : 'Tümünü'} ekle
                  </Button>
                </>
              )
            }
          />
          {list.isError && (
            <div className="p-3">
              <Alert tone="bad" title="Nesneler listelenemedi">
                {(list.error as Error).message}
              </Alert>
            </div>
          )}
          {list.isPending ? (
            <SkeletonRows rows={8} />
          ) : !results ? (
            <EmptyState compact icon={<Search />} title="Henüz listeleme yapılmadı" description="Farklı filtrelerle birden çok kez listeleyip havuza ekleyebilirsiniz; tekrar eden nesneler otomatik ayıklanır." />
          ) : results.items.length === 0 ? (
            <EmptyState compact icon={<Inbox />} title="Filtrelerle eşleşen nesne yok" description="Filtreleri genişletmeyi deneyin." />
          ) : (
            <>
              <div className="flex items-center gap-2 border-b border-line px-3 py-2">
                <SearchInput value={resultQ} onChange={(v) => {setResultQ(v); setPage(0);}} inputSize="sm" placeholder="Sonuçlarda ara…" className="w-64" />
                {selected.size > 0 && (
                  <button type="button" className="text-xs text-fg-subtle hover:text-fg" onClick={() => setSelected(new Set())}>
                    Seçimi temizle
                  </button>
                )}
                <button
                  type="button"
                  className="ml-auto text-xs font-medium text-accent hover:underline"
                  onClick={() => setSelected(new Set(visibleAll.filter(selectable).map(objectKey)))}
                >
                  Tüm sonuçları seç ({formatNumber(visibleAll.filter(selectable).length)})
                </button>
              </div>
              <Table>
                <THead>
                  <tr>
                    <Th className="w-10">
                      <Checkbox
                        checked={allPageSelected}
                        indeterminate={!allPageSelected && somePageSelected}
                        label="Sayfadakileri seç"
                        disabled={!pageSelectable.length}
                        onChange={() =>
                          setSelected((s) => {
                            const n = new Set(s);
                            for (const o of pageSelectable) {
                              if (allPageSelected) n.delete(objectKey(o));
                              else n.add(objectKey(o));
                            }
                            return n;
                          })
                        }
                      />
                    </Th>
                    <SortTh label="Veritabanı" sortKey="database" active={sort.key} dir={sort.dir} onSort={onSort} />
                    <SortTh label="Şema" sortKey="schema" active={sort.key} dir={sort.dir} onSort={onSort} />
                    <SortTh label="Ad" sortKey="name" active={sort.key} dir={sort.dir} onSort={onSort} />
                    <SortTh label="Tip" sortKey="type" active={sort.key} dir={sort.dir} onSort={onSort} />
                    <SortTh label="Oluşturma" sortKey="create_date" active={sort.key} dir={sort.dir} onSort={onSort} />
                    <SortTh label="Değişiklik" sortKey="modify_date" active={sort.key} dir={sort.dir} onSort={onSort} />
                  </tr>
                </THead>
                <tbody>
                  {pageItems.map((o) => {
                    const k = objectKey(o);
                    const inPool = poolKeys.has(k);
                    const on = selected.has(k);
                    return (
                      <Tr key={k} interactive={!inPool} selected={on} onClick={() => !inPool && toggle(o)} className={cn(inPool && 'opacity-55')}>
                        <Td>
                          {inPool ? (
                            <Tooltip content="Zaten havuzda">
                              <span className="flex size-4 items-center justify-center rounded-[5px] bg-ok-soft text-ok">
                                <Boxes className="size-2.5" />
                              </span>
                            </Tooltip>
                          ) : (
                            <Checkbox checked={on} onChange={() => toggle(o)} label={`${o.name} seç`} />
                          )}
                        </Td>
                        <Td className="font-mono text-[11.5px] text-fg-muted">{o.database}</Td>
                        <Td className="font-mono text-[11.5px] text-fg-muted">{o.schema}</Td>
                        <Td className="max-w-0 min-w-40">
                          <span className="block truncate font-mono text-[12px] text-fg">{o.name}</span>
                        </Td>
                        <Td>
                          <TypeBadge type={o.type} />
                        </Td>
                        <Td>
                          <DateCell value={o.create_date} />
                        </Td>
                        <Td>
                          <DateCell value={o.modify_date} />
                        </Td>
                      </Tr>
                    );
                  })}
                </tbody>
              </Table>
              <Pagination page={page} pageCount={pageCount} onPage={setPage} total={visibleAll.length} pageSize={PAGE_SIZE} />
            </>
          )}
        </Card>
      </div>

      <PoolPanel pool={pool} onRemove={onRemove} onClear={onClear} />
    </div>
  );
}

function DateCell({value}: {value: string | null}) {
  return (
    <span className="block whitespace-nowrap leading-4">
      <span className="block text-xs text-fg-muted tnum">{formatDate(value)}</span>
      <span className="block text-[11px] text-fg-subtle">{relativeTime(value)}</span>
    </span>
  );
}

function DateRange({from, to, onFrom, onTo}: {from: string; to: string; onFrom: (v: string) => void; onTo: (v: string) => void}) {
  return (
    <div className="flex items-center gap-2">
      <Input type="date" value={from} max={to || undefined} onChange={(e) => onFrom(e.target.value)} aria-label="Başlangıç" className="tnum" />
      <span className="text-fg-subtle">–</span>
      <Input type="date" value={to} min={from || undefined} onChange={(e) => onTo(e.target.value)} aria-label="Bitiş" className="tnum" />
      {(from || to) && (
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          aria-label="Tarih aralığını temizle"
          onClick={() => {
            onFrom('');
            onTo('');
          }}
        >
          <X className="size-3.5" />
        </Button>
      )}
    </div>
  );
}

const POOL_RENDER_LIMIT = 400;

function PoolPanel({pool, onRemove, onClear}: {pool: DbObject[]; onRemove: (keys: string[]) => void; onClear: () => void}) {
  const [q, setQ] = useState('');
  const shown = useMemo(() => pool.filter((o) => matchesSearch(q, o.database, o.schema, o.name)), [pool, q]);
  const byType = useMemo(() => {
    const m = new Map<string, number>();
    for (const o of pool) m.set(o.type, (m.get(o.type) ?? 0) + 1);
    return [...m.entries()];
  }, [pool]);
  return (
    <Card className="flex flex-col overflow-hidden xl:sticky xl:top-4 xl:max-h-[calc(100dvh-140px)]">
      <div className="relative border-b border-line px-4 py-3">
        <div className="hairline-top absolute inset-x-0 top-0 h-px" />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Boxes className="size-4 text-accent" />
            <h3 className="text-[13px] font-semibold text-fg">Havuz</h3>
          </div>
          {pool.length > 0 && (
            <Button variant="ghost" size="xs" icon={<Trash2 className="size-3" />} onClick={onClear}>
              Temizle
            </Button>
          )}
        </div>
        <p className="mt-2 text-[28px] leading-8 font-semibold tracking-tight text-fg tnum">
          {formatNumber(pool.length)}
          <span className="ml-1.5 text-xs font-normal text-fg-subtle">nesne</span>
        </p>
        {byType.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {byType.map(([t, n]) => (
              <span key={t} className="inline-flex items-center gap-1 rounded-md bg-surface-3 px-1.5 py-0.5 text-[11px] text-fg-muted">
                {OBJECT_TYPE_LABEL[t as DbObject['type']]} <span className="font-semibold text-fg tnum">{n}</span>
              </span>
            ))}
          </div>
        )}
      </div>
      {pool.length === 0 ? (
        <EmptyState compact icon={<Inbox />} title="Havuz boş" description="Soldaki sonuçlardan nesne seçip “Havuza ekle”ye basın." />
      ) : (
        <>
          {pool.length > 8 && (
            <div className="border-b border-line p-2">
              <SearchInput value={q} onChange={setQ} inputSize="sm" placeholder="Havuzda ara…" />
            </div>
          )}
          <ul className="min-h-0 flex-1 overflow-y-auto p-1.5" style={{maxHeight: 520}}>
            {shown.slice(0, POOL_RENDER_LIMIT).map((o) => (
              <li key={objectKey(o)} className="group flex items-center gap-2 rounded-md px-2 py-1 hover:bg-surface-2">
                <TypeBadge type={o.type} />
                <span className="min-w-0 flex-1 truncate font-mono text-[11.5px]">
                  <span className="text-fg-subtle">
                    {o.database}.{o.schema}.
                  </span>
                  <span className="text-fg">{o.name}</span>
                </span>
                <button
                  type="button"
                  aria-label={`${o.name} havuzdan çıkar`}
                  onClick={() => onRemove([objectKey(o)])}
                  className="flex size-5 shrink-0 items-center justify-center rounded text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100 hover:bg-surface-3 hover:text-bad focus:opacity-100"
                >
                  <X className="size-3" />
                </button>
              </li>
            ))}
            {shown.length > POOL_RENDER_LIMIT && (
              <li className="px-2 py-2 text-center text-[11.5px] text-fg-subtle">+{formatNumber(shown.length - POOL_RENDER_LIMIT)} nesne daha</li>
            )}
          </ul>
        </>
      )}
    </Card>
  );
}

export function QueryChips({query}: {query: Partial<ObjectQuery>}) {
  return (
    <span className="flex flex-wrap gap-1">
      {describeQuery(query).map((p) => (
        <span key={p} className="rounded-md border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] text-fg-muted">
          {p}
        </span>
      ))}
    </span>
  );
}
