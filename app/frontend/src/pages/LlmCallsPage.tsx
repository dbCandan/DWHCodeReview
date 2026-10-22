import {useState} from 'react';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {Dialog} from '@/components/ui/Dialog';
import {PageHeader} from '@/components/ui/PageHeader';
import {EmptyState, ErrorState, LoadingState} from '@/components/ui/States';
import {useResource} from '@/hooks/useResource';
import {describeError} from '@/lib/errorMessages';
import {formatDateTime, formatNumber} from '@/lib/format';
import {ConnectionService} from '@/services/connections';
import type {LlmCallSummary} from '@/types/sqlReview';

const OUTCOME_LABELS: Record<LlmCallSummary['outcome'], string> = {
  ok: 'Başarılı',
  timeout: 'Zaman aşımı',
  connect_error: 'Bağlanamadı',
  tls_error: 'Güvenli bağlantı hatası',
  network_policy_denied: 'Ağ politikası reddetti',
  upstream_status: 'Sunucu hata kodu',
  invalid_response: 'Geçersiz yanıt',
  response_too_large: 'Yanıt çok büyük',
  cancelled: 'İptal edildi',
};

function part(call: LlmCallSummary): string {
  return call.part_index === null ? 'Tek' : `${call.part_index}/2`;
}

function count(value: number | null): string {
  return value === null ? '—' : formatNumber(value);
}

/**
 * LLM call summaries for the super admin (sql-review llm-connection Requirement 10, 11): only
 * metadata such as model, duration and token counts; never prompts, SQL or model answers.
 */
export default function LlmCallsPage() {
  const [limit, setLimit] = useState(100);
  const [openId, setOpenId] = useState<string | null>(null);
  const calls = useResource(`llm-calls:${limit}`, (signal) => ConnectionService.llmCalls(limit, signal));
  const data = calls.data;
  return (
    <div className="page">
      <PageHeader
        title="LLM çağrıları"
        description="Her LLM çağrısının özeti 90 gün saklanır. İstem, SQL metni ve model yanıtı saklanmaz."
        actions={
          <>
            <label className="field-label" htmlFor="llm-call-limit">
              Gösterilen
            </label>
            <select
              id="llm-call-limit"
              className="select"
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
            >
              <option value={100}>Son 100</option>
              <option value={250}>Son 250</option>
              <option value={500}>Son 500</option>
            </select>
            <Button onClick={calls.reload}>Yenile</Button>
          </>
        }
      />
      {calls.status === 'error' && <ErrorState message={describeError(calls.error)} onRetry={calls.reload} />}
      {calls.status === 'loading' && data === undefined && <LoadingState label="Çağrı özetleri yükleniyor…" />}
      {data && (
        <Card title={`Çağrı özetleri (${data.items.length} / ${data.total})`} bodyClassName="table-wrap">
          {data.items.length === 0 ? (
            <EmptyState title="Henüz LLM çağrısı yok." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Başlangıç</th>
                  <th scope="col">Nesne veya etiket</th>
                  <th scope="col">Kural</th>
                  <th scope="col">Model</th>
                  <th scope="col">Sonuç</th>
                  <th scope="col">Süre</th>
                  <th scope="col">Belirteç</th>
                  <th scope="col">
                    <span className="sr-only">Ayrıntı</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((call) => (
                  <tr key={call.public_id}>
                    <td className="nowrap">{formatDateTime(call.started_at)}</td>
                    <td className="mono">{call.object_label}</td>
                    <td className="mono nowrap">
                      {call.rule_id} · {part(call)} · deneme {call.attempt}
                    </td>
                    <td className="mono">{call.model}</td>
                    <td>
                      <Badge tone={call.outcome === 'ok' ? 'success' : 'danger'}>{OUTCOME_LABELS[call.outcome]}</Badge>
                      {call.http_status !== null && <span className="subtle nowrap"> HTTP {call.http_status}</span>}
                    </td>
                    <td className="tabular nowrap">{formatNumber(call.duration_ms)} ms</td>
                    <td className="tabular">{count(call.completion_tokens)}</td>
                    <td>
                      <Button size="sm" onClick={() => setOpenId(call.public_id)} aria-label={`${call.rule_id} çağrısının ayrıntısı`}>
                        Ayrıntı
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
      {openId !== null && <LlmCallDialog publicId={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}

function LlmCallDialog({publicId, onClose}: {publicId: string; onClose: () => void}) {
  const call = useResource(`llm-call:${publicId}`, (signal) => ConnectionService.llmCall(publicId, signal));
  const data = call.data;
  return (
    <Dialog title="LLM çağrı özeti" size="sm" onClose={onClose} footer={<Button onClick={onClose}>Kapat</Button>}>
      {call.status === 'error' && <ErrorState message={describeError(call.error)} onRetry={call.reload} />}
      {call.status === 'loading' && <LoadingState />}
      {data && (
        <dl className="facts">
          <Fact label="Başlangıç" value={formatDateTime(data.started_at)} />
          <Fact label="Nesne veya etiket" value={data.object_label} />
          <Fact label="Kural" value={`${data.rule_id} (${part(data)})`} />
          <Fact label="Deneme" value={String(data.attempt)} />
          <Fact label="İstek biçimi" value={data.chat_api} />
          <Fact label="Model" value={data.model} />
          <Fact label="Uç" value={data.endpoint_host} />
          <Fact label="Akışlı" value={data.streamed ? 'Evet' : 'Hayır'} />
          <Fact label="Sonuç" value={OUTCOME_LABELS[data.outcome]} />
          <Fact label="HTTP kodu" value={data.http_status === null ? '—' : String(data.http_status)} />
          <Fact label="Süre" value={`${formatNumber(data.duration_ms)} ms`} />
          <Fact label="Üretilen belirteç" value={count(data.completion_tokens)} />
          <Fact label="İstem belirteci" value={count(data.prompt_tokens)} />
          <Fact label="Yanıt karakteri" value={count(data.response_chars)} />
          <Fact label="İnceleme kimliği" value={data.review_run_id ?? '—'} />
        </dl>
      )}
    </Dialog>
  );
}

function Fact({label, value}: {label: string; value: string}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
