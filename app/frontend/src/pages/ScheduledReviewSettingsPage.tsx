import {useState} from 'react';
import {Alert} from '@/components/ui/Alert';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {Field} from '@/components/ui/Field';
import {PageHeader} from '@/components/ui/PageHeader';
import {ErrorState, LoadingState} from '@/components/ui/States';
import {useResource} from '@/hooks/useResource';
import {describeError} from '@/lib/errorMessages';
import {ScheduledReviewService} from '@/services/scheduledReviews';

const MIN = 1;
const MAX = 10;

/**
 * The super admin's scheduled review setting (sql-review scheduled-review-email Requirement 7,
 * Decision 8): how many scheduled runs may run at the same time in the tenant; more wait in turn.
 */
export default function ScheduledReviewSettingsPage() {
  const settings = useResource('scheduled-review-settings', (signal) => ScheduledReviewService.settings(signal));
  return (
    <div className="page">
      <PageHeader
        title="Zamanlanmış inceleme ayarı"
        description="Zamanlanmış koşumlar elle başlatılan incelemelerle aynı LLM sınırını paylaşır; bu sınır bunlardan aynı anda kaçının çalışacağını belirler."
      />
      {settings.status === 'error' && <ErrorState message={describeError(settings.error)} onRetry={settings.reload} />}
      {settings.data === undefined && settings.status !== 'error' && <LoadingState label="Ayar yükleniyor…" />}
      {settings.data && (
        <SettingsForm
          initial={settings.data.max_concurrent_runs}
          onSaved={(value) => settings.replace({max_concurrent_runs: value})}
        />
      )}
    </div>
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
