import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import RuleProposalsPage from './RuleProposalsPage';
import {RuleProposalService} from '@/services/ruleProposals';
import {RuleSetService} from '@/services/ruleSet';
import {renderWithSession} from '@/test/render';
import type {RuleProposalDetail, RuleProposalItem, RuleSetVersionDetail} from '@/types/sqlReview';

const VERSION: RuleSetVersionDetail = {
  number: 4,
  published_at: '2026-10-14T09:00:00Z',
  published_by_name: 'Uygulama Yöneticisi',
  source: 'arayuz',
  critical: [
    {id: 'Kural01', text: 'NOLOCK kullanılmamalıdır. Kirli okuma yapar.', summary: '', requires_metadata: false, rule_group_ids: []},
  ],
  normal: [{id: 'Kural05', text: 'Uzun metin.', summary: 'Adlandırma kuralı.', requires_metadata: false, rule_group_ids: ['grp-perf']}],
  groups: [{id: 'grp-perf', name: 'Performans', description: ''}],
  critical_count: 1,
  normal_count: 1,
};

function item(overrides: Partial<RuleProposalItem> = {}): RuleProposalItem {
  return {
    id: 'p-1',
    kind: 'rule',
    status: 'bekliyor',
    proposer_name: 'Ayşe İnceleyici',
    created_at: '2026-10-14T10:00:00Z',
    summary: 'Geçici tablolar silinmelidir.',
    group_name: '',
    decided_by_name: null,
    decided_at: null,
    rejection_reason: null,
    published_version_number: null,
    new_rule_id: null,
    owned: true,
    ...overrides,
  };
}

function detail(): RuleProposalDetail {
  return {
    ...item(),
    text: 'x',
    priority: 'normal',
    requires_metadata: false,
    rule_group_ids: [],
    group_description: '',
    rule_codes: [],
    rationale: '',
  };
}

function page(items: RuleProposalItem[]) {
  return {items, page: 1, page_size: 100, total: items.length};
}

describe('rule proposals page (rule-proposals Requirement 2-4, 7)', () => {
  beforeEach(() => {
    vi.spyOn(RuleProposalService, 'capabilities').mockResolvedValue({can_propose: true, can_decide: false});
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(VERSION);
    vi.spyOn(RuleProposalService, 'list').mockResolvedValue(page([]));
  });

  it('tells a user without the permission whom to ask', async () => {
    vi.mocked(RuleProposalService.capabilities).mockResolvedValue({can_propose: false, can_decide: false});
    renderWithSession(<RuleProposalsPage />);
    expect(await screen.findByText('Kural önerme yetkiniz yok')).toBeInTheDocument();
  });

  it('needs a one-sentence summary and the detailed text before sending a rule', async () => {
    const create = vi.spyOn(RuleProposalService, 'create').mockResolvedValue(detail());
    renderWithSession(<RuleProposalsPage />);
    const form = await screen.findByRole('form', {name: 'Yeni kural önerisi'});
    const send = within(form).getByRole('button', {name: 'Öneriyi gönder'});
    fireEvent.change(within(form).getByLabelText('Ayrıntılı kural metni (zorunlu)'), {
      target: {value: 'Geçici tablolar işlem sonunda DROP edilmelidir.'},
    });
    expect(send).toBeDisabled();
    fireEvent.change(within(form).getByLabelText('Özet (tek cümle, zorunlu)'), {target: {value: 'x'.repeat(201)}});
    expect(within(form).getByText('Kural özeti en çok 200 karakter olabilir.')).toBeInTheDocument();
    expect(send).toBeDisabled();
    fireEvent.change(within(form).getByLabelText('Özet (tek cümle, zorunlu)'), {
      target: {value: 'Geçici tablolar silinmelidir.'},
    });
    fireEvent.change(within(form).getByLabelText('Öncelik'), {target: {value: 'critical'}});
    fireEvent.click(within(form).getByLabelText('Performans'));
    fireEvent.click(send);
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0]).toMatchObject({
      kind: 'rule',
      summary: 'Geçici tablolar silinmelidir.',
      text: 'Geçici tablolar işlem sonunda DROP edilmelidir.',
      priority: 'critical',
      rule_group_ids: ['grp-perf'],
    });
    // After sending, the page shows the proposal history.
    expect(await screen.findByText('Henüz öneriniz yok')).toBeInTheDocument();
  });

  it('proposes a group of published rules chosen by their summaries, in version order', async () => {
    const create = vi.spyOn(RuleProposalService, 'create').mockResolvedValue(detail());
    renderWithSession(<RuleProposalsPage />);
    fireEvent.click(await screen.findByRole('tab', {name: 'Grup öner'}));
    const form = await screen.findByRole('form', {name: 'Yeni grup önerisi'});
    expect(within(form).getByText('NOLOCK kullanılmamalıdır.')).toBeInTheDocument();
    expect(within(form).getByText('Adlandırma kuralı.')).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText('Grup adı (zorunlu)'), {target: {value: 'Veri kalitesi'}});
    fireEvent.click(within(form).getByRole('checkbox', {name: /Kural05/}));
    fireEvent.click(within(form).getByRole('checkbox', {name: /Kural01/}));
    fireEvent.click(within(form).getByRole('button', {name: 'Öneriyi gönder'}));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0]).toMatchObject({
      kind: 'group',
      group_name: 'Veri kalitesi',
      rule_codes: ['Kural01', 'Kural05'],
    });
  });

  it('lists the proposals with their state and reason and withdraws a pending one', async () => {
    vi.mocked(RuleProposalService.list).mockResolvedValue(
      page([
        item(),
        item({
          id: 'p-2',
          kind: 'group',
          status: 'reddedildi',
          summary: '',
          group_name: 'Veri kalitesi',
          decided_by_name: 'Uygulama Yöneticisi',
          rejection_reason: 'Mevcut grupla aynı.',
        }),
        item({id: 'p-3', status: 'onaylandi', published_version_number: 5, new_rule_id: 'Kural13'}),
      ]),
    );
    const withdraw = vi.spyOn(RuleProposalService, 'withdraw').mockResolvedValue(detail());
    renderWithSession(<RuleProposalsPage />);
    fireEvent.click(await screen.findByRole('tab', {name: 'Önerilerim'}));
    const history = await screen.findByRole('region', {name: 'Önerilerim'});
    expect(within(history).getByText('Ret gerekçesi: Mevcut grupla aynı.')).toBeInTheDocument();
    expect(within(history).getByText(/sürüm 5 · Kural13/)).toBeInTheDocument();
    expect(within(history).getAllByRole('button', {name: 'Geri çek'})).toHaveLength(1);
    fireEvent.click(within(history).getByRole('button', {name: 'Geri çek'}));
    await waitFor(() => expect(withdraw).toHaveBeenCalledWith('p-1'));
  });
});
