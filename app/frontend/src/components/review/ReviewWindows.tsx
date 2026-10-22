import {useState} from 'react';
import {ExportButtons} from '@/components/review/ExportButtons';
import {ReviewResultsView} from '@/components/review/ReviewResultsView';
import {Alert} from '@/components/ui/Alert';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {Dialog} from '@/components/ui/Dialog';
import {Icon} from '@/components/ui/Icon';
import {useReviewSession, type ReviewSessionState} from '@/contexts/ReviewSessionContext';
import {useOpenStoredRun} from '@/hooks/useOpenStoredRun';
import {messageForCode} from '@/lib/errorMessages';
import {
  completionRatio,
  orderedObjects,
  progressLine,
  stageLabel,
  tokenLabel,
  type LiveObject,
} from '@/lib/reviewProgress';
import {hasStoredSql} from '@/lib/reviewResults';

function kindLabel(session: ReviewSessionState): string {
  return session.kind === 'script' ? 'SQL betiği incelemesi' : 'Nesne incelemesi';
}

function finishedLine(session: ReviewSessionState): string {
  if (session.phase === 'cancelled')
    return session.stopConfirmed
      ? 'İnceleme durduruldu. Sunucu durdurmayı doğruladı; LLM çağrıları kesildi.'
      : 'İnceleme durduruldu.';
  if (session.phase === 'failed') return 'İnceleme hata ile sona erdi.';
  return 'İnceleme tamamlandı.';
}

/** The live window, the results window and nothing else: rendered once in the application shell. */
export function ReviewWindows() {
  const {session} = useReviewSession();
  if (session.view === 'live') return <LiveReviewDialog />;
  if (session.view === 'results') return <ReviewResultsDialog />;
  if (session.phase === 'running') return <ReviewDock />;
  return null;
}

/**
 * While a review runs with its window closed, a small dock in the corner keeps its progress and
 * the stop button in sight on every page (object-review Requirement 14, 15).
 */
function ReviewDock() {
  const {session, stop, showLive} = useReviewSession();
  const progress = session.progress;
  const percent = progress ? Math.round(completionRatio(progress) * 100) : 0;
  return (
    <aside className="review-dock" aria-label="Süren inceleme">
      <div className="review-dock-head">
        <span className="pulse-dot" aria-hidden="true" />
        <strong className="grow truncate">{kindLabel(session)}</strong>
        <span className="tabular review-dock-percent">%{percent}</span>
      </div>
      <p className="subtle truncate" title={session.title}>
        {session.title}
      </p>
      <div
        className="progress"
        role="progressbar"
        aria-label="İnceleme ilerlemesi"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span style={{width: `${percent}%`}} />
      </div>
      <p className="subtle tabular" role="status">
        {session.stopping
          ? 'Durduruluyor…'
          : progress
            ? progressLine(progress)
            : 'İstek gönderiliyor…'}
      </p>
      <div className="row">
        <Button size="sm" onClick={showLive}>
          Canlı pencereyi aç
        </Button>
        <Button size="sm" variant="danger" onClick={stop} disabled={session.stopping} busy={session.stopping}>
          {session.stopping ? 'Durduruluyor…' : 'Analizi durdur'}
        </Button>
      </div>
    </aside>
  );
}

function LiveReviewDialog() {
  const {session, stop, showResults, closeWindows} = useReviewSession();
  const openStoredRun = useOpenStoredRun();
  const running = session.phase === 'running';
  const progress = session.progress;
  const objects = progress ? orderedObjects(progress) : [];
  const recent = progress ? progress.recent : [];
  const percent = progress ? Math.round(completionRatio(progress) * 100) : 0;
  // A large run does not send its results; whether SQL text was stored is answered by the export.
  const sqlAvailable =
    session.phase === 'completed' && (session.resultsOmitted || hasStoredSql(true, session.results));

  return (
    <Dialog
      title="Canlı inceleme"
      busy={running}
      onClose={running ? undefined : closeWindows}
      headerActions={
        running ? (
          <>
            <Button onClick={closeWindows} title="Pencere küçülür; ilerleme sağ altta görünmeye devam eder">
              Arka planda sürdür
            </Button>
            <Button variant="danger" onClick={stop} disabled={session.stopping} busy={session.stopping}>
              {session.stopping ? 'Durduruluyor…' : 'Analizi durdur'}
            </Button>
          </>
        ) : undefined
      }
      footer={
        running ? (
          <p className="subtle grow" role="status">
            {session.stopping
              ? 'Durdurma isteği sunucuya gönderildi; LLM çağrıları kesiliyor…'
              : 'Analiz sürüyor. “Arka planda sürdür” ile başka sayfalara geçebilirsiniz; ilerleme sağ altta görünür.'}
          </p>
        ) : (
          <>
            <p className="grow" role="status">
              {finishedLine(session)}
            </p>
            {session.phase === 'completed' && session.runId && (
              <ExportButtons runId={session.runId} sqlAvailable={sqlAvailable} />
            )}
            {session.results.length > 0 && (
              <Button variant="primary" onClick={() => showResults(true)}>
                Sonuçları göster
              </Button>
            )}
            {session.phase === 'completed' && session.resultsOmitted && session.runId && (
              <Button variant="primary" onClick={() => openStoredRun(session.runId!)}>
                Sonuçları geçmişte aç
              </Button>
            )}
            <Button onClick={closeWindows}>Kapat</Button>
          </>
        )
      }
    >
      <div className="stack-tight">
        <p className="rule-text">
          <strong>{kindLabel(session)}:</strong> {session.title}
        </p>
        {session.subtitle && <p className="subtle mono wrap-anywhere">{session.subtitle}</p>}
        {progress?.ruleVersion != null && <p className="subtle">Kural sürümü {progress.ruleVersion}</p>}
      </div>
      <div className="stack-tight">
        <div
          className="progress"
          role="progressbar"
          aria-label="İnceleme ilerlemesi"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
        >
          <span style={{width: `${percent}%`}} />
        </div>
        <p className="subtle tabular" aria-live="polite">
          {progress ? progressLine(progress) : 'İstek gönderiliyor…'}
        </p>
      </div>
      {session.phase === 'completed' && session.resultsOmitted && (
        <Alert tone="info">
          Bu inceleme çok sayıda nesne içerdiği için sonuçlar bu pencerede gösterilmez. Sonuçlar kaydedildi;
          İnceleme geçmişi sayfasında sayfa sayfa açabilir ya da buradan indirebilirsiniz.
        </Alert>
      )}
      {session.phase === 'failed' && session.errorMessage && <Alert tone="error">{session.errorMessage}</Alert>}
      {session.phase === 'cancelled' && <Alert tone="info">{session.errorMessage}</Alert>}
      {objects.length === 0 && recent.length === 0 && running && <p className="muted">Nesne kuyruğu hazırlanıyor…</p>}
      {objects.length > 0 && (
        <section className="stack" aria-label="Şu an incelenen nesneler">
          {objects.map((object) => (
            <LiveObjectCard key={object.index} object={object} initiallyOpen={objects.length <= 3 || object.index === 0} />
          ))}
        </section>
      )}
      {recent.length > 0 && (
        <section className="stack" aria-label="Son biten nesneler">
          {progress !== null && progress.objectsDone + progress.objectsFailed > recent.length && (
            <p className="subtle">Biten nesnelerden yalnız son {recent.length} tanesi listelenir.</p>
          )}
          {recent.map((object) => (
            <LiveObjectCard key={object.index} object={object} initiallyOpen={false} />
          ))}
        </section>
      )}
    </Dialog>
  );
}

function LiveObjectCard({object, initiallyOpen}: {object: LiveObject; initiallyOpen: boolean}) {
  const [open, setOpen] = useState(initiallyOpen);
  const bodyId = `live-object-${object.index}`;
  const tone = object.stage === 'error' ? 'danger' : object.stage === 'done' ? 'success' : 'warning';
  return (
    <section className="disclosure" aria-label={object.label}>
      <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)}>
        <span className="stack-tight">
          <strong className="mono">{object.label}</strong>
          <span className="subtle">
            {object.rulesTotal > 0 ? `Kural ${object.rulesDone} / ${object.rulesTotal}` : 'Kurallar bekleniyor'}
          </span>
        </span>
        <span className="row">
          {object.stage === 'rules' && <span className="pulse-dot" aria-hidden="true" />}
          <Badge tone={tone}>{stageLabel(object.stage)}</Badge>
          <span aria-hidden="true">{open ? '▾' : '▸'}</span>
        </span>
      </button>
      {open && (
        <div id={bodyId} className="disclosure-body">
          {object.error && <Alert tone="error">{messageForCode(object.error.code) ?? object.error.message}</Alert>}
          {object.ruleOrder.length === 0 && !object.error && (
            <p className="muted">{object.rulesTotal > 0 ? 'Kurallar kuyruğa alınıyor…' : 'Henüz kural başlamadı.'}</p>
          )}
          <ul className="list stack-tight">
            {object.ruleOrder.map((ruleId) => {
              const rule = object.rules[ruleId];
              return (
                <li key={ruleId} className="row">
                  <span className="mono">{ruleId}</span>
                  {rule.tier && <Badge tone={rule.tier === 'critical' ? 'danger' : 'info'}>{rule.tier === 'critical' ? 'Kritik' : 'Normal'}</Badge>}
                  {rule.twoPart && <Badge>İki parça</Badge>}
                  {rule.stage === 'running' && <span className="spinner" role="img" aria-label="Sürüyor" />}
                  {rule.stage === 'done' && <Badge tone="success">Tamamlandı</Badge>}
                  {rule.stage === 'failed' && <Badge tone="warning">Yanıt alınamadı</Badge>}
                  <span className="subtle tabular push-end">{tokenLabel(rule)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

function ReviewResultsDialog() {
  const {session, showLive, closeWindows, applyMark} = useReviewSession();
  const sqlAvailable = hasStoredSql(session.phase === 'completed', session.results);
  return (
    <Dialog
      title="İnceleme sonuçları"
      onClose={closeWindows}
      headerActions={
        session.resultsFromLive ? (
          <Button size="sm" variant="ghost" onClick={showLive}>
            ← Canlı pencereye dön
          </Button>
        ) : undefined
      }
      footer={
        <>
          {session.runId && <ExportButtons runId={session.runId} sqlAvailable={sqlAvailable} />}
          <Button onClick={closeWindows}>Kapat</Button>
        </>
      }
    >
      <p className="subtle">
        {kindLabel(session)}: {session.title}
      </p>
      <ReviewResultsView results={session.results} runId={session.runId} canMark onMarked={applyMark} />
    </Dialog>
  );
}

/** Top-bar indicator of the tab's review, visible on every page. */
export function GlobalReviewIndicator() {
  const {session, showLive} = useReviewSession();
  if (session.phase === 'idle') return null;
  const percent = session.progress ? Math.round(completionRatio(session.progress) * 100) : 0;
  const text =
    session.phase === 'running'
      ? `İnceleme sürüyor · %${percent}`
      : session.phase === 'completed'
        ? 'Son inceleme tamamlandı'
        : session.phase === 'cancelled'
          ? 'Son inceleme durduruldu'
          : 'Son inceleme hata verdi';
  return (
    <Button
      size="sm"
      variant="ghost"
      className={`review-pill is-${session.phase}`}
      onClick={showLive}
      aria-label={`${text}. Canlı pencereyi aç`}
      title={text}
    >
      {session.phase === 'running' ? (
        <span className="pulse-dot" aria-hidden="true" />
      ) : (
        <Icon name={session.phase === 'completed' ? 'check' : 'activity'} />
      )}
      <span className="grow truncate tabular">{text}</span>
    </Button>
  );
}
