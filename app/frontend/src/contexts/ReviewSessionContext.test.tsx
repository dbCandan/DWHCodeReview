import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {useLocation} from 'react-router';
import {describe, expect, it, vi} from 'vitest';
import {useReviewSession} from './ReviewSessionContext';
import {ReviewWindows} from '@/components/review/ReviewWindows';
import {ReviewService} from '@/services/reviews';
import {renderWithSession} from '@/test/render';
import {eventStreamResponse, liveResult, objectRunEvents} from '@/test/reviewEvents';
import type {ReviewStreamEvent} from '@/types/sqlReview';

function Starter() {
  const {session, startObjectReview, startScriptReview} = useReviewSession();
  const location = useLocation();
  return (
    <div>
      <p data-testid="phase">{session.phase}</p>
      <p data-testid="location">{`${location.pathname}${location.search}`}</p>
      <button
        onClick={() => startObjectReview([{database: 'DWH', schema: 'dbo', name: 'usp_load', type_code: 'P'}])}
      >
        start object
      </button>
      <button onClick={() => startScriptReview('SELECT 1', '  ')}>start script</button>
      <ReviewWindows />
    </div>
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
}

/** A stream that stays open until the request is aborted, like a long review. */
function openStream(events: ReviewStreamEvent[], signal: AbortSignal | null | undefined): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const event of events) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      signal?.addEventListener('abort', () =>
        controller.error(new DOMException('The operation was aborted.', 'AbortError')),
      );
    },
  });
  return new Response(body, {status: 200, headers: {'Content-Type': 'text/event-stream'}});
}

async function phase(expected: string) {
  await waitFor(() => expect(screen.getByTestId('phase').textContent).toBe(expected));
}

describe('review session', () => {
  it('streams with the bearer header, shows live progress, then results with export buttons', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(eventStreamResponse(objectRunEvents()));
    renderWithSession(<Starter />);
    fireEvent.click(screen.getByRole('button', {name: 'start object'}));
    await phase('completed');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/dwhcodereview/v1/object-reviews');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer test-token');
    expect(JSON.parse(String(init?.body))).toEqual({
      selections: [{database: 'DWH', schema: 'dbo', name: 'usp_load', type_code: 'P'}],
      rule_codes: [],
    });

    const live = screen.getByRole('dialog', {name: 'Canlı inceleme'});
    expect(within(live).getByText('İnceleme tamamlandı.')).toBeInTheDocument();
    expect(within(live).getByText('Kural sürümü 2')).toBeInTheDocument();
    expect(within(live).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
    expect(within(live).getByRole('button', {name: 'CSV indir'})).toBeEnabled();
    expect(within(live).getByRole('button', {name: 'SQL indir'})).toBeEnabled();

    fireEvent.click(within(live).getByRole('button', {name: 'Sonuçları göster'}));
    const results = screen.getByRole('dialog', {name: 'İnceleme sonuçları'});
    expect(within(results).getAllByText('Satır 12').length).toBeGreaterThan(0);
    fireEvent.click(within(results).getByRole('button', {name: '← Canlı pencereye dön'}));
    expect(screen.getByRole('dialog', {name: 'Canlı inceleme'})).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('points a run too large for the results window at the stored run instead', async () => {
    // object-review Requirement 14: a run of more objects than one result page sends no results.
    const events = objectRunEvents().slice(0, -1);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      eventStreamResponse([...events, {phase: 'complete', run_id: 'run-1', results: [], results_omitted: true}]),
    );
    renderWithSession(<Starter />);
    fireEvent.click(screen.getByRole('button', {name: 'start object'}));
    await phase('completed');

    const live = screen.getByRole('dialog', {name: 'Canlı inceleme'});
    expect(within(live).getByText(/sonuçlar bu pencerede gösterilmez/)).toBeInTheDocument();
    expect(within(live).queryByRole('button', {name: 'Sonuçları göster'})).toBeNull();
    expect(within(live).getByRole('button', {name: 'CSV indir'})).toBeEnabled();
    expect(within(live).getByRole('button', {name: 'SQL indir'})).toBeEnabled();

    fireEvent.click(within(live).getByRole('button', {name: 'Sonuçları geçmişte aç'}));
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/gecmis?run=run-1'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('lists only the objects in flight and the last finished ones in the live window', async () => {
    const total = 400;
    const fields = (index: number) => ({
      kind: 'object' as const,
      database: 'DWH',
      object_index: index,
      objects_total: total,
      object_label: `[DWH] dbo.p${index} (P)`,
      schema: 'dbo',
      name: `p${index}`,
      type_code: 'P',
    });
    const events: ReviewStreamEvent[] = [
      {phase: 'run_started', run_id: 'run-1', rule_version: 2, objects_total: total, kind: 'object', all_rules: true},
    ];
    for (let index = 0; index < 300; index += 1) {
      events.push({...fields(index), phase: 'object_start'});
      if (index < 297) {
        events.push(
          index === 7
            ? {...fields(index), phase: 'object_error', code: 'object_not_found', message: 'x'}
            : {...fields(index), phase: 'object_done'},
        );
      }
    }
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => openStream(events, init?.signal));
    renderWithSession(<Starter />);
    fireEvent.click(screen.getByRole('button', {name: 'start object'}));

    const live = await screen.findByRole('dialog', {name: 'Canlı inceleme'});
    expect(await within(live).findByText('296 / 400 nesne tamamlandı · 1 nesnede hata')).toBeInTheDocument();
    const inFlight = within(live).getByRole('region', {name: 'Şu an incelenen nesneler'});
    expect(within(inFlight).getAllByRole('region').map((card) => card.getAttribute('aria-label'))).toEqual([
      '[DWH] dbo.p297 (P)',
      '[DWH] dbo.p298 (P)',
      '[DWH] dbo.p299 (P)',
    ]);
    const recent = within(live).getByRole('region', {name: 'Son biten nesneler'});
    expect(within(recent).getAllByRole('region')).toHaveLength(20);
    expect(within(recent).getByText('Biten nesnelerden yalnız son 20 tanesi listelenir.')).toBeInTheDocument();
    vi.spyOn(ReviewService, 'cancelRun').mockResolvedValue({id: 'run-1', status: 'cancelling'});
    fireEvent.click(within(live).getByRole('button', {name: 'Analizi durdur'}));
    await phase('cancelled');
  });

  it('cannot be dismissed while running; stop aborts, shows "İnceleme durduruldu." and no results', async () => {
    let signal: AbortSignal | null | undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      signal = init?.signal;
      return openStream(objectRunEvents().slice(0, 6), signal);
    });
    renderWithSession(<Starter />);
    fireEvent.click(screen.getByRole('button', {name: 'start script'}));
    const live = await screen.findByRole('dialog', {name: 'Canlı inceleme'});
    await within(live).findByText('Kural 0 / 2');

    fireEvent.keyDown(live, {key: 'Escape'});
    expect(screen.getByRole('dialog', {name: 'Canlı inceleme'})).toBeInTheDocument();
    expect(within(live).queryByRole('button', {name: 'Kapat'})).toBeNull();

    // object-review Decision 9: the stop is a request to the server, then the stream closes.
    let confirm: (value: {id: string; status: 'cancelling'}) => void = () => undefined;
    const cancel = vi
      .spyOn(ReviewService, 'cancelRun')
      .mockReturnValue(new Promise((resolve) => (confirm = resolve)));
    fireEvent.click(within(live).getByRole('button', {name: 'Analizi durdur'}));
    expect(await within(live).findByRole('button', {name: 'Durduruluyor…'})).toBeDisabled();
    expect(within(live).getByText(/Durdurma isteği sunucuya gönderildi/)).toBeInTheDocument();
    const runId = cancel.mock.calls[0][0];
    confirm({id: runId, status: 'cancelling'});
    await phase('cancelled');
    expect(signal?.aborted).toBe(true);
    expect(within(live).getByText(/Sunucu durdurmayı doğruladı; LLM çağrıları kesildi/)).toBeInTheDocument();
    expect(within(live).getAllByText(/İnceleme durduruldu\./).length).toBeGreaterThan(0);
    expect(within(live).queryByRole('button', {name: 'Sonuçları göster'})).toBeNull();
    fireEvent.click(within(live).getByRole('button', {name: 'Kapat'}));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('sends a running review to the background, keeps it in a dock and stops it from there', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) =>
      openStream(objectRunEvents().slice(0, 6), init?.signal),
    );
    const cancel = vi.spyOn(ReviewService, 'cancelRun').mockResolvedValue({id: 'run-1', status: 'cancelling'});
    renderWithSession(<Starter />);
    fireEvent.click(screen.getByRole('button', {name: 'start script'}));
    const live = await screen.findByRole('dialog', {name: 'Canlı inceleme'});
    await within(live).findByText('Kural 0 / 2');
    fireEvent.click(within(live).getByRole('button', {name: 'Arka planda sürdür'}));
    expect(screen.queryByRole('dialog')).toBeNull();
    const dock = screen.getByRole('complementary', {name: 'Süren inceleme'});
    expect(within(dock).getByRole('progressbar', {name: 'İnceleme ilerlemesi'})).toBeInTheDocument();
    fireEvent.click(within(dock).getByRole('button', {name: 'Analizi durdur'}));
    await phase('cancelled');
    expect(cancel).toHaveBeenCalled();
    expect(screen.queryByRole('complementary', {name: 'Süren inceleme'})).toBeNull();
  });

  it('reports a lost connection when the stream ends without a final event', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(eventStreamResponse(objectRunEvents().slice(0, 5)));
    renderWithSession(<Starter />);
    fireEvent.click(screen.getByRole('button', {name: 'start object'}));
    await phase('failed');
    expect(screen.getByRole('alert')).toHaveTextContent('Sunucu bağlantısı koptu; inceleme tamamlanamadı.');
  });

  it('shows the error event of the stream with its mapped message', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      eventStreamResponse([
        {phase: 'run_started', run_id: 'run-9', rule_version: 1, objects_total: 1, kind: 'script', all_rules: true},
        {phase: 'error', code: 'review_failed', message: 'ham ileti gösterilmez'},
      ]),
    );
    renderWithSession(<Starter />);
    fireEvent.click(screen.getByRole('button', {name: 'start script'}));
    await phase('failed');
    expect(screen.getByRole('alert')).toHaveTextContent('İnceleme tamamlanamadı.');
    expect(screen.queryByText('ham ileti gösterilmez')).toBeNull();
  });

  it.each([
    [409, 'no_published_rule_set', 'Henüz yayımlanmış kural yok; inceleme başlatılamaz.'],
    [429, 'rate_limited', 'Çok fazla inceleme başlattınız; biraz sonra yeniden deneyin.'],
    [503, 'llm_not_configured', 'LLM bağlantısı yapılandırılmamış.'],
    [
      413,
      'unknown_code',
      'Seçim, sunucunun tek istekte kabul ettiği boyutu aşıyor; daha az nesne seçip yeniden deneyin.',
    ],
  ])('shows a %s %s refusal before the stream opens', async (status, code, text) => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(status, {detail: {code, message: 'x'}}));
    renderWithSession(<Starter />);
    fireEvent.click(screen.getByRole('button', {name: 'start object'}));
    await phase('failed');
    expect(screen.getByRole('alert')).toHaveTextContent(text);
  });

  it('sends the default label rule to the script endpoint and disables SQL export without stored text', async () => {
    const failedObject = liveResult({error_code: 'object_not_found', error_message: 'x', rule_results: [], findings: []});
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(eventStreamResponse([{phase: 'complete', run_id: 'run-2', results_omitted: false, results: [failedObject]}]));
    renderWithSession(<Starter />);
    fireEvent.click(screen.getByRole('button', {name: 'start script'}));
    await phase('completed');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/dwhcodereview/v1/script-reviews');
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({sql: 'SELECT 1', label: null, rule_codes: []});
    expect(screen.getByText(/Yapıştırılan SQL/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'SQL indir'})).toBeDisabled();
  });
});
