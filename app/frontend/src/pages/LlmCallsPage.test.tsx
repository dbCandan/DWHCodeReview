import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import LlmCallsPage from './LlmCallsPage';
import {ConnectionService} from '@/services/connections';
import {renderWithSession} from '@/test/render';
import type {LlmCallSummary} from '@/types/sqlReview';

const call: LlmCallSummary = {
  public_id: 'call-1',
  started_at: '2026-09-26T09:00:00Z',
  review_run_id: 'run-1',
  object_label: '[DWH] dbo.usp_load (P)',
  rule_id: 'Kural01',
  part_index: null,
  attempt: 1,
  chat_api: 'openai',
  model: 'qwen',
  endpoint_host: 'llm.kurum.local',
  streamed: true,
  outcome: 'timeout',
  http_status: null,
  duration_ms: 900000,
  completion_tokens: null,
  prompt_tokens: null,
  response_chars: null,
};

describe('LLM calls page', () => {
  it('lists summaries with model, duration and outcome and opens one', async () => {
    vi.spyOn(ConnectionService, 'llmCalls').mockResolvedValue({items: [call], limit: 100, total: 1});
    const one = vi.spyOn(ConnectionService, 'llmCall').mockResolvedValue(call);
    renderWithSession(<LlmCallsPage />, {role: 'super_admin'});
    const table = await screen.findByRole('table');
    expect(within(table).getByText('qwen')).toBeInTheDocument();
    expect(within(table).getByText('Zaman aşımı')).toBeInTheDocument();
    expect(within(table).getByText('900.000 ms')).toBeInTheDocument();
    fireEvent.click(within(table).getByRole('button', {name: 'Kural01 çağrısının ayrıntısı'}));
    const dialog = await screen.findByRole('dialog', {name: 'LLM çağrı özeti'});
    await within(dialog).findByText('llm.kurum.local');
    expect(one).toHaveBeenCalledWith('call-1', expect.any(AbortSignal));
  });

  it('asks for more rows when the limit changes', async () => {
    vi.spyOn(ConnectionService, 'llmCalls').mockResolvedValue({items: [], limit: 100, total: 0});
    renderWithSession(<LlmCallsPage />, {role: 'super_admin'});
    expect(await screen.findByText('Henüz LLM çağrısı yok.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Gösterilen'), {target: {value: '500'}});
    await waitFor(() => expect(ConnectionService.llmCalls).toHaveBeenLastCalledWith(500, expect.any(AbortSignal)));
  });
});
