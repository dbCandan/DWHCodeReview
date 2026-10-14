import {useState} from 'react';
import {useSearchParams} from 'react-router';
import {ExportButtons} from '@/components/review/ExportButtons';
import {ReviewResultsView} from '@/components/review/ReviewResultsView';
import {Alert} from '@/components/ui/Alert';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {ConfirmDialog} from '@/components/ui/ConfirmDialog';
import {PageHeader} from '@/components/ui/PageHeader';
import {Pager} from '@/components/ui/Pager';
import {EmptyState, ErrorState, LoadingState} from '@/components/ui/States';
import {useAuth} from '@/contexts/AuthContext';
import {useResource} from '@/hooks/useResource';
import {describeError, messageForCode} from '@/lib/errorMessages';
import {formatDateTime} from '@/lib/format';
import {applyFalsePositive, hasStoredSql} from '@/lib/reviewResults';
import type {Tone} from '@/lib/utils';
import {ReviewService} from '@/services/reviews';
import type {ReviewRunDetail, ReviewRunStatus, ReviewRunSummary} from '@/types/sqlReview';

const PAGE_SIZE = 50;
/** Objects of a run shown per page of its results (review-history-export Requirement 3). */
const RESULTS_PAGE_SIZE = 50;

const STATUS: Record<ReviewRunStatus, {label: string; tone: Tone}> = {
  running: {label: 'Sürüyor', tone: 'warning'},
  completed: {label: 'Tamamlandı', tone: 'success'},
  failed: {label: 'Hata', tone: 'danger'},
  cancelled: {label: 'Durduruldu', tone: 'neutral'},
  interrupted: {label: 'Yarıda kesildi', tone: 'warning'},
};

type Scope = 'mine' | 'all';
type PendingDelete = {kind: 'one'; run: ReviewRunSummary} | {kind: 'all'};

/**
 * Review history stored on the server (sql-review review-history-export Requirement 1–5, 10, 11):
 * own runs for everyone, all runs read-only for the rule manager, details with false-positive
 * marks, CSV and SQL downloads and deletion of own finished runs.
 */
export default function ReviewHistoryPage() {
  const {access} = useAuth();
  const [scope, setScope] = useState<Scope>('mine');
  const [page, setPage] = useState(1);
  // "?run=<id>" opens that run: a large review points here instead of showing its results itself.
  const [searchParams] = useSearchParams();
  const requestedRun = searchParams.get('run');
  const [openedRun, setOpenedRun] = useState(requestedRun);
  const [selectedId, setSelectedId] = useState<string | null>(requestedRun);
  if (requestedRun !== openedRun) {
    setOpenedRun(requestedRun);
    if (requestedRun !== null) setSelectedId(requestedRun);
  }
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState<{tone: 'success' | 'error'; text: string} | null>(null);
  const effectiveScope: Scope = access.manageRules ? scope : 'mine';
  const runs = useResource(`runs:${effectiveScope}:${page}`, (signal) =>
    ReviewService.runs(effectiveScope, page, PAGE_SIZE, signal),
  );

  async function confirmDelete() {
    if (pendingDelete === null) return;
    setDeleting(true);
    setNotice(null);
    try {
      if (pendingDelete.kind === 'one') {
        await ReviewService.deleteRun(pendingDelete.run.id);
        if (selectedId === pendingDelete.run.id) setSelectedId(null);
        setNotice({tone: 'success', text: 'İnceleme silindi.'});
      } else {
        const result = await ReviewService.deleteOwnRuns();
        setSelectedId(null);
        setNotice({tone: 'success', text: `${result.deleted_count} inceleme silindi.`});
      }
      runs.reload();
    } catch (error) {
      setNotice({tone: 'error', text: describeError(error)});
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  }

  const data = runs.data;
  return (
    <div className="page">
      <PageHeader
        title="İnceleme geçmişi"
        description="Biten incelemeleriniz sunucuda saklanır ve hangi bilgisayardan girerseniz girin burada görünür. Kayıtlar saklama süresi dolunca kendiliğinden silinir."
        actions={
          <>
            <Button onClick={runs.reload}>Yenile</Button>
            <Button variant="danger-outline" onClick={() => setPendingDelete({kind: 'all'})}>
              Tümünü sil
            </Button>
          </>
        }
      />
      {access.manageRules && (
        <fieldset className="row">
          <legend className="sr-only">Gösterilen incelemeler</legend>
          {(['mine', 'all'] as const).map((value) => (
            <label key={value} className="check">
              <input
                type="radio"
                name="history-scope"
                checked={scope === value}
                onChange={() => {
                  setScope(value);
                  setPage(1);
                  setSelectedId(null);
                }}
              />
              <span>{value === 'mine' ? 'Benim incelemelerim' : 'Tüm incelemeler'}</span>
            </label>
          ))}
        </fieldset>
      )}
      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      <div className="master-detail">
        <Card
          title={`Kayıtlar${data ? ` (${data.total})` : ''}`}
          footer={data ? <Pager page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} /> : undefined}
          bodyClassName="stack"
        >
          {runs.status === 'error' && <ErrorState message={describeError(runs.error)} onRetry={runs.reload} />}
          {runs.status === 'loading' && data === undefined && <LoadingState label="Geçmiş yükleniyor…" />}
          {data && data.items.length === 0 && (
            <EmptyState title="Henüz kayıtlı inceleme yok.">
              Nesne veya SQL betiği incelemesi bitince burada listelenir.
            </EmptyState>
          )}
          {data && data.items.length > 0 && (
            <ul className="list">
              {data.items.map((run) => (
                <li key={run.id} className="list-item">
                  <RunRow
                    run={run}
                    showOwner={effectiveScope === 'all'}
                    selected={run.id === selectedId}
                    onSelect={() => setSelectedId(run.id)}
                  />
                  {run.owned && run.status !== 'running' && (
                    <div className="row row-end list-item-actions">
                      <Button
                        size="sm"
                        variant="danger-outline"
                        aria-label={`${run.title} incelemesini sil`}
                        onClick={() => setPendingDelete({kind: 'one', run})}
                      >
                        Sil
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
        {selectedId === null ? (
          <Card title="Sonuçlar">
            <EmptyState title="Soldan bir inceleme seçin." />
          </Card>
        ) : (
          <RunDetail key={selectedId} runId={selectedId} />
        )}
      </div>
      {pendingDelete && (
        <ConfirmDialog
          title={pendingDelete.kind === 'all' ? 'Tüm incelemeleriniz silinsin mi?' : 'Bu inceleme silinsin mi?'}
          confirmLabel="Sil"
          danger
          busy={deleting}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDelete(null)}
        >
          <p className="rule-text">
            {pendingDelete.kind === 'all'
              ? 'Kendi biten incelemeleriniz, sonuçları, işaretleri ve saklanan SQL metinleriyle kalıcı olarak silinir. Başkalarının incelemelerine dokunulmaz.'
              : `“${pendingDelete.run.title}” incelemesi, sonuçları, işaretleri ve saklanan SQL metniyle kalıcı olarak silinir.`}
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

function RunRow({
  run,
  showOwner,
  selected,
  onSelect,
}: {
  run: ReviewRunSummary;
  showOwner: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const status = STATUS[run.status];
  return (
    <button
      type="button"
      className="list-button stack-tight"
      aria-current={selected}
      aria-label={`${run.title} — ${status.label}, ${formatDateTime(run.started_at)}`}
      onClick={onSelect}
    >
      <span className="row">
        <Badge tone={KIND_BADGES[run.kind].tone}>{KIND_BADGES[run.kind].label}</Badge>
        <Badge tone={status.tone}>{status.label}</Badge>
        <span className="subtle">{formatDateTime(run.started_at)}</span>
      </span>
      <strong>{run.title}</strong>
      {run.subtitle && <span className="subtle mono">{run.subtitle}</span>}
      {run.error_code && run.status !== 'cancelled' && (
        <span className="field-error">{messageForCode(run.error_code) ?? run.error_message}</span>
      )}
      <span className="subtle">
        Kural sürümü {run.rule_version} · {run.object_count} nesne · {run.finding_count} bulgu
        {showOwner ? ` · ${run.owner_display_name}` : ''}
      </span>
    </button>
  );
}

const KIND_BADGES: Record<ReviewRunSummary['kind'], {tone: 'info' | 'primary' | 'warning'; label: string}> = {
  object: {tone: 'info', label: 'Nesne'},
  script: {tone: 'primary', label: 'SQL'},
  scheduled: {tone: 'warning', label: 'Zamanlanmış'},
};

function RunDetail({runId}: {runId: string}) {
  const [resultsPage, setResultsPage] = useState(1);
  const detail = useResource(`run:${runId}:${resultsPage}`, (signal) =>
    ReviewService.run(runId, resultsPage, RESULTS_PAGE_SIZE, signal),
  );
  const run = detail.data;
  if (detail.status === 'error')
    return (
      <Card title="Sonuçlar">
        <ErrorState message={describeError(detail.error)} onRetry={detail.reload} />
      </Card>
    );
  if (run === undefined)
    return (
      <Card title="Sonuçlar">
        <LoadingState label="İnceleme yükleniyor…" />
      </Card>
    );
  const status = STATUS[run.status];
  return (
    <Card
      title={run.title}
      actions={<Badge tone={status.tone}>{status.label}</Badge>}
      footer={
        <ExportButtons
          runId={run.id}
          // Only one page of a large run is loaded; the export itself answers when no text is stored.
          sqlAvailable={
            run.status === 'completed' &&
            (run.object_count > run.results.length || hasStoredSql(true, run.results))
          }
          size="sm"
        />
      }
    >
      <div className="stack">
        <p className="subtle">
          {formatDateTime(run.started_at)} · kural sürümü {run.rule_version} · {run.object_count} nesne ·{' '}
          {run.finding_count} bulgu · {run.owner_display_name}
        </p>
        {run.subtitle && <p className="subtle mono">{run.subtitle}</p>}
        <p className="subtle">{selectionLine(run)}</p>
        {!run.owned && <Alert tone="info">Bu inceleme başka bir kullanıcıya ait; yalnız okunabilir.</Alert>}
        {run.status === 'cancelled' && <Alert tone="info">Bu inceleme durduruldu; kısmi sonuç saklanmaz.</Alert>}
        {run.status === 'interrupted' && <Alert tone="warning">Bu inceleme yarıda kesildi; sonucu saklanmadı.</Alert>}
        {run.status === 'failed' && (
          <Alert tone="error">{messageForCode(run.error_code) ?? run.error_message ?? 'İnceleme tamamlanamadı.'}</Alert>
        )}
        {run.status === 'completed' && run.object_count > RESULTS_PAGE_SIZE && (
          <div className="stack-tight">
            <p className="subtle">
              Sonuçlar nesne sırasıyla, sayfa başına {RESULTS_PAGE_SIZE} nesne gösterilir; süzgeç yalnız açık sayfadaki
              nesnelere uygulanır. Bütün sonuçlar için CSV dosyasını indirin.
            </p>
            <Pager page={resultsPage} pageSize={RESULTS_PAGE_SIZE} total={run.object_count} onPage={setResultsPage} />
          </div>
        )}
        {run.results.length > 0 && (
          <ReviewResultsView
            results={run.results}
            runId={run.id}
            canMark={run.owned}
            onMarked={(target, value) =>
              detail.replace({...run, results: applyFalsePositive(run.results, target, value)})
            }
          />
        )}
      </div>
    </Card>
  );
}

/** The run's rule selection (rule-group-selection Requirement 7, Decision 6). */
function selectionLine(run: ReviewRunDetail): string {
  const groups = run.selected_rule_groups ?? [];
  const codes = run.selected_rule_codes ?? [];
  if (run.all_rules || (groups.length === 0 && codes.length === 0)) return 'Kurallar: Tüm kurallar';
  const parts: string[] = [];
  if (groups.length > 0) parts.push(`Kural grupları: ${groups.map((group) => group.name).join(', ')}`);
  if (codes.length > 0) parts.push(`Seçilen kurallar: ${codes.join(', ')}`);
  return parts.join(' · ');
}
