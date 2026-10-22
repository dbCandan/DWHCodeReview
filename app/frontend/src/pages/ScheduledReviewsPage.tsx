import {useEffect, useState} from 'react';
import {Link} from 'react-router';
import {RuleGroupPicker} from '@/components/review/RuleGroupPicker';
import {Alert} from '@/components/ui/Alert';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {ConfirmDialog} from '@/components/ui/ConfirmDialog';
import {Dialog} from '@/components/ui/Dialog';
import {Field} from '@/components/ui/Field';
import {Icon} from '@/components/ui/Icon';
import {PageHeader} from '@/components/ui/PageHeader';
import {Pager} from '@/components/ui/Pager';
import {EmptyState, ErrorState, LoadingState} from '@/components/ui/States';
import {useResource} from '@/hooks/useResource';
import {describeError, messageForCode} from '@/lib/errorMessages';
import {formatDateTime, formatNumber} from '@/lib/format';
import {OBJECT_TYPES, selectionKey} from '@/lib/objectSelection';
import {
  EMAIL_LABELS,
  MONTH_DAY_LIMIT,
  SCHEDULE_NAME_LIMIT,
  TIMEZONES,
  TRIGGER_LABELS,
  WEEKDAYS,
  emptyForm,
  formOf,
  formProblems,
  periodLabel,
  stateText,
  toWrite,
  type Frequency,
  type ScheduleForm,
} from '@/lib/scheduledReviews';
import {CatalogService} from '@/services/catalog';
import {ScheduledReviewService} from '@/services/scheduledReviews';
import type {ObjectSelection, ScheduledReviewItem, ScheduledRunItem} from '@/types/sqlReview';

const PAGE_SIZE = 50;
const RUNS_PAGE_SIZE = 20;
const PICKER_PAGE_SIZE = 200;

export const EMAIL_NOTE =
  'E-posta yalnız özet ve rapor bağlantısı taşır; SQL metni ve kod parçası e-postaya konmaz. Rapor uygulamada oturum açarak görülür.';

type Editing = {id: string | null};

/**
 * Scheduled reviews (sql-review scheduled-review-email Requirement 9): definitions with their
 * period, rule groups and recipients, pause and resume, run history with the "kaçırıldı" and
 * "e-posta gönderilemedi" warnings. The super admin also sees every definition and "Şimdi
 * çalıştır". The backend authorizes every request.
 */
export default function ScheduledReviewsPage() {
  const [page, setPage] = useState(1);
  const list = useResource(`scheduled-reviews:${page}`, (signal) =>
    ScheduledReviewService.list(page, PAGE_SIZE, signal),
  );
  const [editing, setEditing] = useState<Editing | null>(null);
  const [historyOf, setHistoryOf] = useState<ScheduledReviewItem | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ScheduledReviewItem | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  // While a run waits or runs, its state is read again so "Sürüyor" turns into the outcome.
  const anyOpen =
    list.data?.items.some((item) => item.last_run?.state === 'queued' || item.last_run?.state === 'running') ?? false;
  const reloadList = list.reload;
  useEffect(() => {
    if (!anyOpen) return;
    const timer = window.setInterval(reloadList, 5000);
    return () => window.clearInterval(timer);
  }, [anyOpen, reloadList]);

  async function act(item: ScheduledReviewItem, action: () => Promise<unknown>, done: string) {
    setBusyId(item.id);
    setNotice(null);
    setFailure(null);
    try {
      await action();
      setNotice(done);
      list.reload();
    } catch (error) {
      setFailure(describeError(error));
    } finally {
      setBusyId(null);
    }
  }

  const data = list.data;
  return (
    <div className="page page-fill">
      <PageHeader
        title="Zamanlanmış incelemeler"
        description="Seçilen nesneler belirlenen periyotta arka planda incelenir; sonuç geçmişe kaydedilir ve alıcılara özet e-posta gider."
        actions={
          <Button variant="primary" onClick={() => setEditing({id: null})}>
            Yeni zamanlanmış inceleme
          </Button>
        }
      />
      {notice && <Alert tone="success">{notice}</Alert>}
      {failure && <Alert tone="error">{failure}</Alert>}
      {list.status === 'error' && <ErrorState message={describeError(list.error)} onRetry={list.reload} />}
      {list.status === 'loading' && data === undefined && <LoadingState label="Tanımlar yükleniyor…" />}
      {data && (
        <Card
          title={`Tanımlar (${data.total})`}
          className="card-fill"
          footer={<Pager page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />}
        >
          {data.items.length === 0 ? (
            <EmptyState title="Henüz zamanlanmış inceleme yok." icon="clock">
              Nesneleri belirlediğiniz periyotta arka planda inceletmek için “Yeni zamanlanmış inceleme” ile başlayın.
            </EmptyState>
          ) : (
            <ul className="list schedule-list">
                {data.items.map((item) => (
                  <DefinitionRow
                    key={item.id}
                    item={item}
                    busy={busyId === item.id}
                    onEdit={() => setEditing({id: item.id})}
                    onHistory={() => setHistoryOf(item)}
                    onDelete={() => setPendingDelete(item)}
                    onPause={() =>
                      act(
                        item,
                        () =>
                          item.status === 'active'
                            ? ScheduledReviewService.pause(item.id)
                            : ScheduledReviewService.resume(item.id),
                        item.status === 'active' ? 'Tanım duraklatıldı.' : 'Tanım etkinleştirildi.',
                      )
                    }
                    onRunNow={() =>
                      act(item, () => ScheduledReviewService.runNow(item.id), 'Koşum sıraya alındı.')
                    }
                    onStop={() =>
                      act(
                        item,
                        () => ScheduledReviewService.stop(item.id),
                        'Koşum durduruldu; bu koşum için e-posta gönderilmez.',
                      )
                    }
                  />
                ))}
            </ul>
          )}
        </Card>
      )}
      {editing && (
        <ScheduleDialog
          id={editing.id}
          onClose={() => setEditing(null)}
          onSaved={(created) => {
            setEditing(null);
            setFailure(null);
            setNotice(created ? 'Zamanlanmış inceleme oluşturuldu.' : 'Zamanlanmış inceleme kaydedildi.');
            list.reload();
          }}
        />
      )}
      {historyOf && <RunsDialog schedule={historyOf} onClose={() => setHistoryOf(null)} />}
      {pendingDelete && (
        <ConfirmDialog
          title="Zamanlanmış inceleme silinsin mi?"
          confirmLabel="Sil"
          danger
          busy={busyId === pendingDelete.id}
          onCancel={() => setPendingDelete(null)}
          onConfirm={async () => {
            const target = pendingDelete;
            await act(target, () => ScheduledReviewService.remove(target.id), 'Zamanlanmış inceleme silindi.');
            setPendingDelete(null);
          }}
        >
          <p>
            “{pendingDelete.name}” tanımı, çalışma geçmişi ve alıcı listesiyle birlikte silinir. Daha önce
            saklanan raporlar inceleme geçmişinde kalır.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

function DefinitionRow({
  item,
  busy,
  onEdit,
  onHistory,
  onDelete,
  onPause,
  onRunNow,
  onStop,
}: {
  item: ScheduledReviewItem;
  busy: boolean;
  onEdit: () => void;
  onHistory: () => void;
  onDelete: () => void;
  onPause: () => void;
  onRunNow: () => void;
  onStop: () => void;
}) {
  const last = item.last_run;
  // Requirement 11: the owner and the super admin stop a queued or running run.
  const open = last?.state === 'queued' || last?.state === 'running';
  const groups =
    item.rule_groups.length === 0
      ? 'Tüm kurallar'
      : item.rule_groups.map((group) => group.name ?? 'Kaldırılmış grup').join(', ');
  return (
    <li>
      <article className={`schedule-card${open ? ' is-live' : ''}`} aria-label={item.name}>
        <div className="schedule-title">
          <span className="stat-icon" aria-hidden="true">
            <Icon name="clock" />
          </span>
          <div className="grow stack-tight">
            <strong className="truncate">{item.name}</strong>
            <span className="subtle">
              {!item.owned && `${item.owner_display_name} · `}
              {item.recipient_count} alıcı
            </span>
          </div>
          <Badge tone={item.status === 'active' ? 'success' : 'neutral'}>
            {item.status === 'active' ? 'Etkin' : 'Duraklatıldı'}
          </Badge>
        </div>
        <dl className="schedule-facts">
          <div>
            <dt>Periyot</dt>
            <dd>{periodLabel(item.period)}</dd>
          </div>
          <div>
            <dt>Nesneler</dt>
            <dd className="mono truncate" title={item.selection_summary}>
              {item.selection_summary}
            </dd>
          </div>
          <div>
            <dt>Kurallar</dt>
            <dd className="truncate" title={groups}>
              {groups}
            </dd>
          </div>
          <div>
            <dt>Sonraki çalışma</dt>
            <dd>{item.next_run_at ? formatDateTime(item.next_run_at) : '—'}</dd>
          </div>
          <div>
            <dt>Son sonuç</dt>
            <dd>
              {last ? (
                <span className="row">
                  {open && <span className="pulse-dot" aria-hidden="true" />}
                  {stateText({state: last.state, skip_reason: null})}
                  {last.finding_count !== null && ` · ${formatNumber(last.finding_count)} bulgu`}
                </span>
              ) : (
                <span className="subtle">Henüz çalışmadı</span>
              )}
              {last?.error_code && (
                <span className="subtle block">{messageForCode(last.error_code) ?? 'İnceleme tamamlanamadı.'}</span>
              )}
            </dd>
          </div>
        </dl>
        {(item.missed || item.email_failed) && (
          <div className="row">
            {item.missed && <Badge tone="warning">Kaçırıldı</Badge>}
            {item.email_failed && <Badge tone="danger">E-posta gönderilemedi</Badge>}
          </div>
        )}
        <div className="schedule-actions">
          {item.can_edit && open && (
            <Button
              size="sm"
              variant="danger"
              onClick={onStop}
              disabled={busy}
              aria-label={`${item.name} koşumunu durdur`}
            >
              Durdur
            </Button>
          )}
          {item.can_run_now && (
            <Button
              size="sm"
              variant="primary"
              onClick={onRunNow}
              disabled={busy}
              aria-label={`${item.name} şimdi çalıştır`}
            >
              Şimdi çalıştır
            </Button>
          )}
          <Button size="sm" onClick={onHistory} aria-label={`${item.name} çalışma geçmişi`}>
            Geçmiş
          </Button>
          {item.can_edit && (
            <Button size="sm" onClick={onEdit} disabled={busy} aria-label={`${item.name} tanımını düzenle`}>
              Düzenle
            </Button>
          )}
          {item.can_edit && (
            <Button
              size="sm"
              onClick={onPause}
              disabled={busy}
              aria-label={`${item.name} tanımını ${item.status === 'active' ? 'duraklat' : 'etkinleştir'}`}
            >
              {item.status === 'active' ? 'Duraklat' : 'Etkinleştir'}
            </Button>
          )}
          {item.can_edit && (
            <Button
              size="sm"
              variant="danger-outline"
              onClick={onDelete}
              disabled={busy}
              aria-label={`${item.name} tanımını sil`}
            >
              Sil
            </Button>
          )}
        </div>
      </article>
    </li>
  );
}

function ScheduleDialog({
  id,
  onClose,
  onSaved,
}: {
  id: string | null;
  onClose: () => void;
  onSaved: (created: boolean) => void;
}) {
  const detail = useResource(id ? `scheduled-review:${id}` : null, (signal) =>
    ScheduledReviewService.get(id ?? '', signal),
  );
  const title = id ? 'Zamanlanmış incelemeyi düzenle' : 'Yeni zamanlanmış inceleme';
  if (id && detail.status === 'error')
    return (
      <Dialog title={title} onClose={onClose}>
        <ErrorState message={describeError(detail.error)} onRetry={detail.reload} />
      </Dialog>
    );
  if (id && detail.data === undefined)
    return (
      <Dialog title={title} onClose={onClose}>
        <LoadingState label="Tanım yükleniyor…" />
      </Dialog>
    );
  return (
    <ScheduleEditor
      key={id ?? 'new'}
      id={id}
      title={title}
      initial={detail.data ? formOf(detail.data) : emptyForm()}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}

function ScheduleEditor({
  id,
  title,
  initial,
  onClose,
  onSaved,
}: {
  id: string | null;
  title: string;
  initial: ScheduleForm;
  onClose: () => void;
  onSaved: (created: boolean) => void;
}) {
  const [form, setForm] = useState<ScheduleForm>(initial);
  const [submitted, setSubmitted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const databases = useResource('catalog-databases', (signal) => CatalogService.databases(signal));
  const problems = formProblems(form);
  const shown = submitted ? problems : {};

  function change(update: Partial<ScheduleForm>) {
    setForm((current) => ({...current, ...update}));
  }

  async function save() {
    setSubmitted(true);
    if (Object.keys(problems).length > 0) return;
    setSaving(true);
    setFailure(null);
    try {
      const body = toWrite(form);
      if (id) await ScheduledReviewService.update(id, body);
      else await ScheduledReviewService.create(body);
      onSaved(id === null);
    } catch (error) {
      setFailure(describeError(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      title={title}
      onClose={saving ? undefined : onClose}
      busy={saving}
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Vazgeç
          </Button>
          <Button variant="primary" onClick={save} disabled={saving} busy={saving}>
            Kaydet
          </Button>
        </>
      }
    >
      <div className="stack">
        {failure && <Alert tone="error">{failure}</Alert>}
        <Field id="schedule-name" label="Ad" error={shown.name}>
          <input
            id="schedule-name"
            className="input"
            maxLength={SCHEDULE_NAME_LIMIT}
            value={form.name}
            aria-invalid={Boolean(shown.name)}
            onChange={(event) => change({name: event.target.value})}
          />
        </Field>

        <fieldset className="field">
          <legend className="field-label">Nesne seçimi</legend>
          <div className="row">
            <label className="check">
              <input
                type="radio"
                name="schedule-mode"
                checked={form.mode === 'filter'}
                onChange={() => change({mode: 'filter'})}
              />
              <span>Süzgeç (her çalışmada güncel nesneler)</span>
            </label>
            <label className="check">
              <input
                type="radio"
                name="schedule-mode"
                checked={form.mode === 'list'}
                onChange={() => change({mode: 'list'})}
              />
              <span>Nesne listesi</span>
            </label>
          </div>
          {databases.status === 'error' && <Alert tone="error">{describeError(databases.error)}</Alert>}
          <div className="split">
            <Field id="schedule-database" label="Veritabanı" error={shown.selection}>
              <select
                id="schedule-database"
                className="select"
                value={form.database}
                onChange={(event) => change({database: event.target.value})}
              >
                <option value="">{databases.status === 'loading' ? 'Yükleniyor…' : '— Veritabanı seçin —'}</option>
                {[...new Set([...(databases.data?.items ?? []), ...(form.database ? [form.database] : [])])].map(
                  (name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ),
                )}
              </select>
            </Field>
            {form.mode === 'filter' && (
              <>
                <Field id="schedule-query" label="Arama (isteğe bağlı)">
                  <input
                    id="schedule-query"
                    className="input"
                    maxLength={200}
                    value={form.query}
                    onChange={(event) => change({query: event.target.value})}
                  />
                </Field>
                <Field id="schedule-type" label="Tür">
                  <select
                    id="schedule-type"
                    className="select"
                    value={form.typeCode}
                    onChange={(event) => change({typeCode: event.target.value})}
                  >
                    <option value="">Tüm türler</option>
                    {OBJECT_TYPES.map((type) => (
                      <option key={type.code} value={type.code}>
                        {type.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field id="schedule-from-date" label="Bu tarihten sonra değişenler (isteğe bağlı)">
                  <input
                    id="schedule-from-date"
                    type="date"
                    className="input"
                    value={form.fromDate}
                    onChange={(event) => change({fromDate: event.target.value})}
                  />
                </Field>
              </>
            )}
          </div>
          {form.mode === 'list' && (
            <ObjectPicker database={form.database} items={form.items} onChange={(items) => change({items})} />
          )}
        </fieldset>

        <RuleGroupPicker value={form.ruleGroupIds} disabled={saving} onChange={(ruleGroupIds) => change({ruleGroupIds})} />

        <fieldset className="field">
          <legend className="field-label">Periyot</legend>
          <div className="split">
            <Field id="schedule-frequency" label="Sıklık">
              <select
                id="schedule-frequency"
                className="select"
                value={form.frequency}
                onChange={(event) => change({frequency: event.target.value as Frequency})}
              >
                <option value="daily">Günlük</option>
                <option value="weekly">Haftalık</option>
                <option value="monthly">Aylık</option>
              </select>
            </Field>
            {form.frequency === 'weekly' && (
              <Field id="schedule-weekday" label="Gün">
                <select
                  id="schedule-weekday"
                  className="select"
                  value={form.weekday}
                  onChange={(event) => change({weekday: Number(event.target.value)})}
                >
                  {WEEKDAYS.map((day, index) => (
                    <option key={day} value={index}>
                      {day}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            {form.frequency === 'monthly' && (
              <Field id="schedule-day" label="Ayın günü" hint={`1-${MONTH_DAY_LIMIT}; her ayda bulunan günler.`}>
                <select
                  id="schedule-day"
                  className="select"
                  value={form.dayOfMonth}
                  onChange={(event) => change({dayOfMonth: Number(event.target.value)})}
                >
                  {Array.from({length: MONTH_DAY_LIMIT}, (_, index) => index + 1).map((day) => (
                    <option key={day} value={day}>
                      {day}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field id="schedule-time" label="Saat" error={shown.time}>
              <input
                id="schedule-time"
                type="time"
                className="input"
                value={form.time}
                aria-invalid={Boolean(shown.time)}
                onChange={(event) => change({time: event.target.value})}
              />
            </Field>
            <Field id="schedule-timezone" label="Zaman dilimi">
              <select
                id="schedule-timezone"
                className="select"
                value={form.timezone}
                onChange={(event) => change({timezone: event.target.value})}
              >
                {[...new Set([...TIMEZONES, form.timezone])].map((zone) => (
                  <option key={zone} value={zone}>
                    {zone}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </fieldset>

        <Field
          id="schedule-recipients"
          label="Alıcılar"
          hint={`Her satıra bir kurum e-posta adresi; en çok 20 alıcı. ${EMAIL_NOTE}`}
          error={shown.recipients}
        >
          <textarea
            id="schedule-recipients"
            className="textarea"
            rows={4}
            value={form.recipients}
            aria-invalid={Boolean(shown.recipients)}
            aria-describedby="schedule-recipients-hint"
            onChange={(event) => change({recipients: event.target.value})}
          />
        </Field>
      </div>
    </Dialog>
  );
}

function ObjectPicker({
  database,
  items,
  onChange,
}: {
  database: string;
  items: ObjectSelection[];
  onChange: (items: ObjectSelection[]) => void;
}) {
  const [query, setQuery] = useState('');
  const objects = useResource(database ? `schedule-objects:${database}:${query}` : null, (signal) =>
    CatalogService.objects(database, {q: query, page: 1, pageSize: PICKER_PAGE_SIZE}, signal),
  );
  const chosen = new Set(items.map((item) => selectionKey(item.database, item)));

  function toggle(selection: ObjectSelection, checked: boolean) {
    const key = selectionKey(selection.database, selection);
    onChange(checked ? [...items, selection] : items.filter((item) => selectionKey(item.database, item) !== key));
  }

  return (
    <div className="stack">
      {items.length > 0 && (
        <ul className="list stack-tight" aria-label="Seçilen nesneler">
          {items.map((item) => (
            <li key={selectionKey(item.database, item)} className="row">
              <span className="mono grow">
                [{item.database}] {item.schema}.{item.name} ({item.type_code})
              </span>
              <Button size="sm" variant="ghost" onClick={() => toggle(item, false)} aria-label={`${item.name} nesnesini çıkar`}>
                Çıkar
              </Button>
            </li>
          ))}
        </ul>
      )}
      {database && (
        <>
          <Field id="schedule-object-search" label="Nesne ara">
            <input
              id="schedule-object-search"
              type="search"
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </Field>
          {objects.status === 'error' && <Alert tone="error">{describeError(objects.error)}</Alert>}
          {objects.status === 'loading' && objects.data === undefined && <LoadingState label="Nesneler yükleniyor…" />}
          <div className="stack-tight">
            {(objects.data?.items ?? []).map((object) => {
              const selection = {database, schema: object.schema, name: object.name, type_code: object.type_code};
              return (
                <label key={selectionKey(database, object)} className="check">
                  <input
                    type="checkbox"
                    checked={chosen.has(selectionKey(database, object))}
                    onChange={(event) => toggle(selection, event.target.checked)}
                  />
                  <span className="mono">
                    {object.schema}.{object.name} ({object.type_code})
                  </span>
                </label>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function RunsDialog({schedule, onClose}: {schedule: ScheduledReviewItem; onClose: () => void}) {
  const [page, setPage] = useState(1);
  const runs = useResource(`scheduled-runs:${schedule.id}:${page}`, (signal) =>
    ScheduledReviewService.runs(schedule.id, page, RUNS_PAGE_SIZE, signal),
  );
  return (
    <Dialog
      title={`${schedule.name} — çalışma geçmişi`}
      onClose={onClose}
      footer={<Button onClick={onClose}>Kapat</Button>}
    >
      {runs.status === 'error' && <ErrorState message={describeError(runs.error)} onRetry={runs.reload} />}
      {runs.status === 'loading' && runs.data === undefined && <LoadingState label="Çalışmalar yükleniyor…" />}
      {runs.data && (
        <div className="stack">
          {runs.data.items.length === 0 ? (
            <EmptyState title="Bu tanım henüz çalışmadı." />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Zaman</th>
                    <th scope="col">Tetikleme</th>
                    <th scope="col">Durum</th>
                    <th scope="col">Bulgu</th>
                    <th scope="col">E-posta</th>
                    <th scope="col">Rapor</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.items.map((run) => (
                    <RunRow key={run.id} run={run} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager page={page} pageSize={RUNS_PAGE_SIZE} total={runs.data.total} onPage={setPage} />
        </div>
      )}
    </Dialog>
  );
}

function RunRow({run}: {run: ScheduledRunItem}) {
  const trigger =
    run.trigger === 'manual' && run.triggered_by_name
      ? `${TRIGGER_LABELS.manual} (${run.triggered_by_name})`
      : TRIGGER_LABELS[run.trigger];
  return (
    <tr>
      <td>{formatDateTime(run.started_at ?? run.due_at)}</td>
      <td>{trigger}</td>
      <td>
        <div className="stack-tight">
          {run.state === 'missed' ? <Badge tone="warning">{stateText(run)}</Badge> : stateText(run)}
          {run.error_code && (
            <span className="subtle">{messageForCode(run.error_code) ?? 'İnceleme tamamlanamadı.'}</span>
          )}
        </div>
      </td>
      <td>{run.finding_count === null ? '—' : formatNumber(run.finding_count)}</td>
      <td>
        {run.email_status === null ? (
          '—'
        ) : run.email_status === 'failed' ? (
          <Badge tone="danger">{EMAIL_LABELS.failed}</Badge>
        ) : (
          EMAIL_LABELS[run.email_status]
        )}
      </td>
      <td>
        {run.review_run_id ? <Link to={`/gecmis?run=${encodeURIComponent(run.review_run_id)}`}>Raporu aç</Link> : '—'}
      </td>
    </tr>
  );
}
