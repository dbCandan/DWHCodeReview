import {useRef, useState} from 'react';
import {RuleSelectionPicker} from '@/components/review/RuleSelectionPicker';
import {LastReviewBanner} from '@/components/review/LastReviewBanner';
import {ObjectTable} from '@/components/review/ObjectTable';
import {Alert} from '@/components/ui/Alert';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {PageHeader} from '@/components/ui/PageHeader';
import {Pager} from '@/components/ui/Pager';
import {EmptyState, ErrorState, LoadingState} from '@/components/ui/States';
import {useReviewSession} from '@/contexts/ReviewSessionContext';
import {useDebouncedValue} from '@/hooks/useDebouncedValue';
import {useResource} from '@/hooks/useResource';
import {describeError} from '@/lib/errorMessages';
import {
  OBJECT_TYPES,
  SELECTION_TECHNICAL_LIMIT,
  addSelections,
  databaseCount,
  toggleAll,
  toggleSelection,
  type SelectionMap,
} from '@/lib/objectSelection';
import {CatalogService} from '@/services/catalog';
import type {CatalogObject} from '@/types/sqlReview';

const PAGE_SIZE = 100;
/** Page size of the requests that gather every object matching the filter (the API maximum). */
const GATHER_PAGE_SIZE = 500;
/** From this many objects on, the page explains what a large run means. */
const LARGE_RUN_NOTICE = 100;

type Gather =
  | {status: 'idle'}
  | {status: 'running'; loaded: number; total: number}
  | {status: 'done'; matched: number}
  | {status: 'error'; message: string};

/**
 * Object review (sql-review object-review Requirement 1–3): pick a database, filter its objects on
 * the server, collect any number of objects from one or more databases and start the review. The
 * header checkbox selects the listed page; "select all matching" gathers every page of the current
 * filter with paged requests, so thousands of objects are selected without being rendered.
 */
export default function ObjectReviewPage() {
  const {session, startObjectReview} = useReviewSession();
  const [ruleCodes, setRuleCodes] = useState<string[]>([]);
  const [database, setDatabase] = useState('');
  const [text, setText] = useState('');
  const [type, setType] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [page, setPage] = useState(1);
  const [selection, setSelection] = useState<SelectionMap>({});
  const query = useDebouncedValue(text.trim(), 300);
  const databases = useResource('databases', (signal) => CatalogService.databases(signal));
  const objectsKey = database ? JSON.stringify([database, query, type, fromDate, page]) : null;
  const objects = useResource(objectsKey, (signal) =>
    CatalogService.objects(database, {q: query, type, fromDate, page, pageSize: PAGE_SIZE}, signal),
  );

  const [gather, setGather] = useState<Gather>({status: 'idle'});
  const gatherRef = useRef<AbortController | null>(null);

  const selected = Object.values(selection);
  const running = session.phase === 'running';
  const gathering = gather.status === 'running';
  const beyondTechnicalLimit = selected.length > SELECTION_TECHNICAL_LIMIT;
  const matching = objects.data?.total ?? 0;

  function stopGathering() {
    gatherRef.current?.abort();
    gatherRef.current = null;
    setGather({status: 'idle'});
  }

  function filterChanged(apply: () => void) {
    stopGathering();
    apply();
    setPage(1);
  }

  /** Select every object of the current database and filter, page by page on the server. */
  async function selectAllMatching() {
    gatherRef.current?.abort();
    const controller = new AbortController();
    gatherRef.current = controller;
    const filter = {q: query, type, fromDate};
    const collected: CatalogObject[] = [];
    setGather({status: 'running', loaded: 0, total: matching});
    try {
      for (let gatherPage = 1; ; gatherPage += 1) {
        const result = await CatalogService.objects(
          database,
          {...filter, page: gatherPage, pageSize: GATHER_PAGE_SIZE},
          controller.signal,
        );
        collected.push(...result.items);
        if (controller.signal.aborted) return;
        setGather({status: 'running', loaded: collected.length, total: result.total});
        if (result.items.length === 0 || collected.length >= result.total) break;
      }
      setSelection((current) => addSelections(current, database, collected));
      setGather({status: 'done', matched: collected.length});
    } catch (error) {
      if (!controller.signal.aborted) setGather({status: 'error', message: describeError(error)});
    } finally {
      if (gatherRef.current === controller) gatherRef.current = null;
    }
  }

  function clearSelection() {
    stopGathering();
    setSelection({});
  }

  return (
    <div className="page">
      <PageHeader
        title="Nesne incelemesi"
        description="Veritabanını seçip nesneleri işaretleyin. Başka bir veritabanına geçerek seçime eklemeye devam edebilirsiniz; bir incelemedeki nesne sayısı için sınır yoktur."
      />
      <LastReviewBanner kind="object" />
      <Card
        title="Veritabanı"
        actions={
          <Button size="sm" variant="ghost" onClick={databases.reload} disabled={databases.status === 'loading'}>
            Listeyi yenile
          </Button>
        }
      >
        <div className="stack">
          <div className="field">
            <label className="field-label" htmlFor="review-database">
              Nesne listesi için veritabanı
            </label>
            <select
              id="review-database"
              className="select"
              value={database}
              disabled={databases.data === undefined || databases.data.items.length === 0}
              onChange={(event) => filterChanged(() => setDatabase(event.target.value))}
            >
              <option value="">{databases.status === 'loading' ? 'Yükleniyor…' : '— Veritabanı seçin —'}</option>
              {databases.data?.items.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          {databases.status === 'error' && (
            <ErrorState message={describeError(databases.error)} onRetry={databases.reload} />
          )}
          {databases.status === 'success' && databases.data.items.length === 0 && (
            <p className="muted">Bağlantı hesabının erişebildiği çevrimiçi veritabanı yok.</p>
          )}
        </div>
      </Card>

      <RuleSelectionPicker value={ruleCodes} disabled={running} onChange={setRuleCodes} />

      <Card
        title="Nesne seçimi"
        actions={
          <>
            <span className="subtle tabular" aria-live="polite">
              {selected.length.toLocaleString('tr-TR')} seçili · {databaseCount(selection)} veritabanı
            </span>
            <Button size="sm" onClick={clearSelection} disabled={selected.length === 0 || running}>
              Seçimi temizle
            </Button>
            <Button
              variant="primary"
              onClick={() => startObjectReview(selected, ruleCodes)}
              disabled={selected.length === 0 || running || gathering || beyondTechnicalLimit}
              aria-label={
                selected.length === 0 ? 'İnceleme için en az bir nesne seçin' : `Seçilen ${selected.length} nesneyi incele`
              }
            >
              {running ? 'İnceleniyor…' : `Seçilenleri incele${selected.length ? ` (${selected.length})` : ''}`}
            </Button>
          </>
        }
        footer={
          objects.data ? (
            <Pager page={page} pageSize={PAGE_SIZE} total={objects.data.total} onPage={setPage} />
          ) : undefined
        }
      >
        <div className="stack">
          {beyondTechnicalLimit && (
            <Alert tone="warning">
              Tek istekte teknik olarak en çok {SELECTION_TECHNICAL_LIMIT.toLocaleString('tr-TR')} nesne
              gönderilebilir. Bu bir ürün sınırı değil, isteğin boyut sınırıdır; seçimi azaltıp kalan nesneleri ayrı
              bir incelemede çalıştırın.
            </Alert>
          )}
          {!beyondTechnicalLimit && selected.length > LARGE_RUN_NOTICE && (
            <Alert tone="info">
              Büyük seçim: inceleme her nesne için her kuralı yapay zekâ modeline ayrı sorar ve saatler sürebilir.
              Bitene kadar bu sekmeyi açık tutun; bağlantı koparsa ya da uygulama yeniden başlatılırsa sonuç
              saklanmaz.
            </Alert>
          )}
          <div className="row">
            <div className="field grow">
              <label className="field-label" htmlFor="object-search">
                Ara
              </label>
              <input
                id="object-search"
                className="input"
                type="search"
                value={text}
                maxLength={200}
                placeholder="Şema, ad veya tür…"
                disabled={!database}
                onChange={(event) => filterChanged(() => setText(event.target.value))}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="object-type">
                Tür
              </label>
              <select
                id="object-type"
                className="select"
                value={type}
                disabled={!database}
                onChange={(event) => filterChanged(() => setType(event.target.value))}
              >
                <option value="">Tüm türler</option>
                {OBJECT_TYPES.map((option) => (
                  <option key={option.code} value={option.code}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="object-from-date">
                Bu tarihten sonra oluşturulan veya değişen
              </label>
              <input
                id="object-from-date"
                className="input"
                type="date"
                value={fromDate}
                disabled={!database}
                onChange={(event) => filterChanged(() => setFromDate(event.target.value))}
              />
            </div>
          </div>
          {!database && <EmptyState title="Nesne listesini görmek için bir veritabanı seçin." />}
          {objects.status === 'error' && <ErrorState message={describeError(objects.error)} onRetry={objects.reload} />}
          {objects.status === 'loading' && objects.data === undefined && <LoadingState label="Nesneler yükleniyor…" />}
          {objects.data && objects.data.items.length === 0 && <EmptyState title="Süzgeçlere uyan nesne yok." />}
          {objects.data && matching > 0 && (
            <div className="row">
              {gathering ? (
                <>
                  <p className="subtle tabular grow" role="status">
                    Süzgece uyan nesneler seçiliyor… {gather.loaded.toLocaleString('tr-TR')} /{' '}
                    {gather.total.toLocaleString('tr-TR')}
                  </p>
                  <Button size="sm" onClick={stopGathering}>
                    Vazgeç
                  </Button>
                </>
              ) : (
                <Button size="sm" onClick={() => void selectAllMatching()} disabled={running}>
                  Süzgece uyan {matching.toLocaleString('tr-TR')} nesnenin tümünü seç
                </Button>
              )}
              {gather.status === 'done' && (
                <p className="subtle" role="status">
                  Süzgece uyan {gather.matched.toLocaleString('tr-TR')} nesne seçildi.
                </p>
              )}
            </div>
          )}
          {gather.status === 'error' && <Alert tone="error">{gather.message}</Alert>}
          {objects.data && objects.data.items.length > 0 && (
            <div aria-busy={objects.status === 'loading'}>
              <ObjectTable
                database={database}
                objects={objects.data.items}
                selection={selection}
                onToggle={(object, value) => setSelection((current) => toggleSelection(current, database, object, value))}
                onToggleAll={(items, value) => setSelection((current) => toggleAll(current, database, items, value))}
              />
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
