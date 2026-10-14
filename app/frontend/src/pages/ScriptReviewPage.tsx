import {useState, type FormEvent} from 'react';
import {RuleSelectionPicker} from '@/components/review/RuleSelectionPicker';
import {LastReviewBanner} from '@/components/review/LastReviewBanner';
import {Alert} from '@/components/ui/Alert';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {PageHeader} from '@/components/ui/PageHeader';
import {useReviewSession} from '@/contexts/ReviewSessionContext';

export const SQL_TEXT_LIMIT = 120_000;
export const LABEL_LIMIT = 200;
export const DATA_NOTE =
  "Metin kurum içi LLM'e gönderilir ve inceleme geçmişinde saklanır; kişisel veri ve parola içermemelidir.";
export const TOO_LONG_MESSAGE = 'SQL metni en çok 120.000 karakter olabilir.';

/**
 * Pasted SQL review (sql-review script-review Requirement 1–3, 11). The text stays in this page's
 * memory; it is never written to browser storage.
 */
export default function ScriptReviewPage() {
  const {session, startScriptReview} = useReviewSession();
  const [label, setLabel] = useState('');
  const [sql, setSql] = useState('');
  const [ruleCodes, setRuleCodes] = useState<string[]>([]);
  const running = session.phase === 'running';
  const length = sql.trim().length;
  const tooLong = length > SQL_TEXT_LIMIT;
  const canSubmit = length > 0 && !tooLong && !running;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canSubmit) startScriptReview(sql.trim(), label, ruleCodes);
  }

  return (
    <div className="page">
      <PageHeader
        title="SQL betiği incelemesi"
        description="Veritabanından nesne seçmeden elinizdeki SQL metnini yapıştırın; yayımlanmış kurallara göre inceleyin. Sonuçlar açılır pencerede gösterilir."
      />
      <LastReviewBanner kind="script" />
      <Card title="SQL betiği">
        <form className="stack" onSubmit={submit}>
          <div className="field">
            <label className="field-label" htmlFor="script-label">
              Sonuçlarda görünecek ad (isteğe bağlı)
            </label>
            <input
              id="script-label"
              className="input"
              value={label}
              maxLength={LABEL_LIMIT}
              disabled={running}
              placeholder="Örn. staging_load_customer"
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="script-sql">
              SQL
            </label>
            <Alert tone="warning">
              <p id="script-note">{DATA_NOTE}</p>
            </Alert>
            <textarea
              id="script-sql"
              className="textarea"
              rows={18}
              value={sql}
              disabled={running}
              spellCheck={false}
              placeholder="CREATE PROCEDURE … veya SELECT …"
              aria-invalid={tooLong || undefined}
              aria-describedby="script-note script-counter"
              onChange={(event) => setSql(event.target.value)}
            />
            <p id="script-counter" className={`counter${tooLong ? ' is-over' : ''}`} aria-live="polite">
              {length === 0
                ? 'Metin yok'
                : `${length.toLocaleString('tr-TR')} / ${SQL_TEXT_LIMIT.toLocaleString('tr-TR')} karakter`}
            </p>
            {tooLong && (
              <p className="field-error" role="alert">
                {TOO_LONG_MESSAGE}
              </p>
            )}
          </div>
          <RuleSelectionPicker value={ruleCodes} disabled={running} onChange={setRuleCodes} />
          <div className="row">
            <Button type="submit" variant="primary" disabled={!canSubmit}>
              {running ? 'İnceleniyor…' : 'Kurallara göre incele'}
            </Button>
            {running && <span className="subtle">LLM yanıtı bekleniyor…</span>}
          </div>
        </form>
      </Card>
    </div>
  );
}
