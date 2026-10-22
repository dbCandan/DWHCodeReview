import {useState, type FormEvent, type ReactNode} from 'react';
import {Alert} from '@/components/ui/Alert';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {Field} from '@/components/ui/Field';
import {PageHeader} from '@/components/ui/PageHeader';
import {ErrorState, LoadingState} from '@/components/ui/States';
import {useResource} from '@/hooks/useResource';
import {describeError} from '@/lib/errorMessages';
import {smtpFailureText} from '@/lib/scheduledReviews';
import {ScheduledReviewService} from '@/services/scheduledReviews';
import type {ScheduledEmailStatus, ScheduledEmailTestResult} from '@/types/sqlReview';

const MIN = 1;
const MAX = 10;

/**
 * The super admin's scheduled review setting (sql-review scheduled-review-email Requirement 7,
 * Decision 8): how many scheduled runs may run at the same time in the tenant; more wait in turn.
 * Below it, whether the summary e-mail can leave this deployment and a test send (Requirement 10).
 */
export default function ScheduledReviewSettingsPage() {
  const settings = useResource('scheduled-review-settings', (signal) => ScheduledReviewService.settings(signal));
  return (
    <div className="page">
      <PageHeader
        title="Zamanlama ve e-posta"
        description="Zamanlanmış koşumların aynı anda kaçının çalışacağını belirleyin; özet e-postanın bu ortamdan çıkıp çıkamadığını görün ve deneyin."
      />
      <div className="settings-grid">
        <div>
          {settings.status === 'error' && <ErrorState message={describeError(settings.error)} onRetry={settings.reload} />}
          {settings.data === undefined && settings.status !== 'error' && <LoadingState label="Ayar yükleniyor…" />}
          {settings.data && (
            <SettingsForm
              initial={settings.data.max_concurrent_runs}
              onSaved={(value) => settings.replace({max_concurrent_runs: value})}
            />
          )}
        </div>
        <EmailCard />
      </div>
    </div>
  );
}

/** Requirement 10: the e-mail path's readiness and a test send to one corporate address. */
function EmailCard() {
  const status = useResource('scheduled-review-email', (signal) => ScheduledReviewService.emailStatus(signal));
  return (
    <Card title="Özet e-posta" labelledBy="email-card-title">
      {status.status === 'error' && <ErrorState message={describeError(status.error)} onRetry={status.reload} />}
      {status.data === undefined && status.status !== 'error' && <LoadingState label="E-posta durumu okunuyor…" />}
      {status.data && <EmailPanel status={status.data} />}
    </Card>
  );
}

function EmailPanel({status}: {status: ScheduledEmailStatus}) {
  const [recipient, setRecipient] = useState(status.suggested_recipient ?? '');
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<ScheduledEmailTestResult | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const ready = status.scheduler_enabled && status.smtp_configured && status.allowed_domains.length > 0;

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!recipient.trim()) return;
    setSending(true);
    setResult(null);
    setFailure(null);
    try {
      setResult(await ScheduledReviewService.sendTestEmail(recipient.trim()));
    } catch (error) {
      setFailure(describeError(error));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="stack-lg">
      <ul className="list check-list" aria-label="E-posta hazırlığı">
        <CheckRow ok={status.scheduler_enabled} label="Zamanlayıcı">
          {status.scheduler_enabled ? 'Açık' : 'Kapalı: DWHCODEREVIEW_SCHEDULER_ENABLED ayarı açılmalı.'}
        </CheckRow>
        <CheckRow ok={status.smtp_configured} label="SMTP sunucusu">
          {status.smtp_configured
            ? `Yapılandırıldı (${status.smtp_security === 'tls' ? 'doğrudan TLS' : 'STARTTLS'})`
            : 'Yapılandırılmadı: SMTP sunucu adresi ve gönderen adresi verilmeli; çıkış (egress) izni açılmalı.'}
        </CheckRow>
        <CheckRow ok={status.allowed_domains.length > 0} label="İzinli alan adları">
          {status.allowed_domains.length > 0 ? status.allowed_domains.join(', ') : 'Tanımlı değil: hiçbir alıcı kabul edilmez.'}
        </CheckRow>
      </ul>
      {!ready && (
        <Alert tone="warning">
          Bu ortamda özet e-posta gönderilemez; koşumların e-posta durumu “E-posta yapılandırılmadı” görünür.
          Eksik ayarı işletim ekibi dağıtım değerlerinden verir.
        </Alert>
      )}
      <form className="row" onSubmit={send} aria-label="Deneme e-postası">
        <div className="grow">
          <Field id="test-recipient" label="Deneme e-postası alıcısı" hint="Tek bir kurum adresi; rapor verisi gönderilmez.">
            <input
              id="test-recipient"
              type="email"
              className="input"
              value={recipient}
              onChange={(event) => setRecipient(event.target.value)}
              autoComplete="email"
            />
          </Field>
        </div>
        <Button type="submit" variant="secondary" disabled={sending || !recipient.trim()} busy={sending}>
          Deneme gönder
        </Button>
      </form>
      {failure && <Alert tone="error">{failure}</Alert>}
      {result?.status === 'sent' && <Alert tone="success">Deneme e-postası SMTP sunucusuna teslim edildi.</Alert>}
      {result?.status === 'not_configured' && <Alert tone="warning">SMTP yapılandırılmadığı için gönderilmedi.</Alert>}
      {result?.status === 'failed' && (
        <Alert tone="error">
          Gönderilemedi: {smtpFailureText(result.error_code)} <span className="mono">({result.error_code})</span>
        </Alert>
      )}
    </div>
  );
}

function CheckRow({ok, label, children}: {ok: boolean; label: string; children: ReactNode}) {
  return (
    <li className="check-row">
      <Badge tone={ok ? 'success' : 'warning'}>{ok ? 'Hazır' : 'Eksik'}</Badge>
      <strong>{label}</strong>
      <span className="subtle wrap-anywhere">{children}</span>
    </li>
  );
}

function SettingsForm({initial, onSaved}: {initial: number; onSaved: (value: number) => void}) {
  const [value, setValue] = useState(String(initial));
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const number = Number(value);
  const invalid = !Number.isInteger(number) || number < MIN || number > MAX;

  async function save() {
    if (invalid) return;
    setSaving(true);
    setSaved(false);
    setFailure(null);
    try {
      const answer = await ScheduledReviewService.saveSettings({max_concurrent_runs: number});
      setSaved(true);
      onSaved(answer.max_concurrent_runs);
    } catch (error) {
      setFailure(describeError(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card
      title="Eşzamanlılık"
      footer={
        <Button variant="primary" onClick={save} disabled={saving || invalid} busy={saving}>
          Kaydet
        </Button>
      }
    >
      <div className="stack">
        {saved && failure === null && <Alert tone="success">Ayar kaydedildi.</Alert>}
        {failure && <Alert tone="error">{failure}</Alert>}
        <Field
          id="max-concurrent-runs"
          label="Aynı anda çalışacak zamanlanmış koşum"
          hint={`${MIN}-${MAX} arası; fazlası sırada bekler.`}
          error={invalid ? `Değer ${MIN}-${MAX} arasında olmalıdır.` : null}
        >
          <input
            id="max-concurrent-runs"
            type="number"
            className="input"
            min={MIN}
            max={MAX}
            value={value}
            aria-invalid={invalid}
            onChange={(event) => {
              setValue(event.target.value);
              setSaved(false);
            }}
          />
        </Field>
      </div>
    </Card>
  );
}
