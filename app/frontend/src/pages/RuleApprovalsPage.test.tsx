import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import RuleApprovalsPage from './RuleApprovalsPage';
import {RuleProposalService} from '@/services/ruleProposals';
import {RuleSetService} from '@/services/ruleSet';
import {UserAdminService} from '@/services/userAdmin';
import {apiError, renderWithSession} from '@/test/render';
import type {
  PublishRequestDetail,
  PublishRequestItem,
  RuleProposalDetail,
  RuleProposalItem,
  RuleSetVersionDetail,
} from '@/types/sqlReview';

const VERSION: RuleSetVersionDetail = {
  number: 4,
  published_at: '2026-10-14T09:00:00Z',
  published_by_name: 'Uygulama Yöneticisi',
  source: 'arayuz',
  critical: [{id: 'Kural01', text: 'NOLOCK kullanılmamalıdır. Kirli okuma yapar.', summary: '', requires_metadata: false, rule_group_ids: []}],
  normal: [],
  groups: [{id: 'grp-perf', name: 'Performans', description: ''}],
  critical_count: 1,
  normal_count: 0,
};

function proposal(overrides: Partial<RuleProposalItem> = {}): RuleProposalItem {
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
    owned: false,
    ...overrides,
  };
}

function proposalDetail(base: RuleProposalItem, overrides: Partial<RuleProposalDetail> = {}): RuleProposalDetail {
  return {
    ...base,
    text: 'Geçici tablolar işlem sonunda DROP edilmelidir; aksi halde tempdb dolar.',
    priority: 'critical',
    requires_metadata: true,
    rule_group_ids: ['grp-perf'],
    group_description: '',
    rule_codes: [],
    rationale: 'Gece işlerinde tempdb doldu.',
    ...overrides,
  };
}

const REQUEST: PublishRequestItem = {
  id: 'r-1',
  status: 'bekliyor',
  requester_name: 'Mehmet Kural',
  created_at: '2026-10-14T11:00:00Z',
  draft_revision: 9,
  draft_changed: false,
  decided_by_name: null,
  decided_at: null,
  rejection_reason: null,
  published_version_number: null,
  owned: false,
};

const REQUEST_DETAIL: PublishRequestDetail = {
  ...REQUEST,
  diff: {
    added_rules: [
      {id: 'Kural14', text: 'Yeni ayrıntılı metin.', summary: 'Yeni özet.', requires_metadata: false, rule_group_ids: [], priority: 'normal'},
    ],
    changed_rules: [
      {
        before: {id: 'Kural01', text: 'Eski metin.', summary: '', requires_metadata: false, rule_group_ids: [], priority: 'critical'},
        after: {id: 'Kural01', text: 'Değişen metin.', summary: '', requires_metadata: false, rule_group_ids: [], priority: 'critical'},
      },
    ],
    removed_rules: [],
    added_groups: [],
    changed_groups: [],
    removed_groups: [{id: 'grp-old', name: 'Eski grup', description: ''}],
  },
};

function pending(items: RuleProposalItem[]) {
  return {items, page: 1, page_size: 100, total: items.length};
}

describe('rule approvals page (rule-proposals Requirement 1, 5-7)', () => {
  beforeEach(() => {
    const rule = proposal();
    const group = proposal({id: 'p-2', kind: 'group', summary: '', group_name: 'Veri kalitesi'});
    vi.spyOn(RuleProposalService, 'list').mockResolvedValue(pending([rule, group]));
    vi.spyOn(RuleProposalService, 'get').mockImplementation(async (id) =>
      id === 'p-1'
        ? proposalDetail(rule)
        : proposalDetail(group, {priority: null, requires_metadata: false, rule_group_ids: [], rule_codes: ['Kural01', 'Kural77'], rationale: ''}),
    );
    vi.spyOn(RuleProposalService, 'publishRequests').mockResolvedValue({items: [REQUEST], page: 1, page_size: 100, total: 1});
    vi.spyOn(RuleProposalService, 'publishRequest').mockResolvedValue(REQUEST_DETAIL);
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(VERSION);
  });

  it('shows a rule proposal with its detailed text and approves it', async () => {
    const approve = vi.spyOn(RuleProposalService, 'approve').mockResolvedValue(proposalDetail(proposal({status: 'onaylandi'})));
    renderWithSession(<RuleApprovalsPage />, {role: 'super_admin'});
    expect(await screen.findByRole('tab', {name: 'Kural önerileri (1)'})).toHaveAttribute('aria-selected', 'true');
    const card = await screen.findByRole('listitem', {name: 'Geçici tablolar silinmelidir.'});
    expect(await within(card).findByText(/aksi halde tempdb dolar/)).toBeInTheDocument();
    expect(within(card).getByText('Kritik')).toBeInTheDocument();
    expect(within(card).getByText('Performans')).toBeInTheDocument();
    expect(within(card).getByText('Gerekçe: Gece işlerinde tempdb doldu.')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', {name: 'Geçici tablolar silinmelidir. onayla'}));
    await waitFor(() => expect(approve).toHaveBeenCalledWith('p-1'));
    await waitFor(() => expect(RuleProposalService.list).toHaveBeenCalledTimes(2));
  });

  it('rejects only with a reason and shows a conflict', async () => {
    const reject = vi.spyOn(RuleProposalService, 'reject').mockResolvedValue(proposalDetail(proposal({status: 'reddedildi'})));
    vi.spyOn(RuleProposalService, 'approve').mockRejectedValue(apiError(409, 'proposal_conflict'));
    renderWithSession(<RuleApprovalsPage />, {role: 'super_admin'});
    const card = await screen.findByRole('listitem', {name: 'Geçici tablolar silinmelidir.'});
    fireEvent.click(within(card).getByRole('button', {name: 'Geçici tablolar silinmelidir. onayla'}));
    expect(await within(card).findByText(/en son yayımlanmış sürüme artık uymuyor/)).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', {name: 'Geçici tablolar silinmelidir. reddet'}));
    const send = within(card).getByRole('button', {name: 'Reddi gönder'});
    expect(send).toBeDisabled();
    fireEvent.change(within(card).getByLabelText(/Ret gerekçesi/), {target: {value: 'Kural03 ile aynı.'}});
    fireEvent.click(send);
    await waitFor(() => expect(reject).toHaveBeenCalledWith('p-1', 'Kural03 ile aynı.'));
  });

  it('lists a group proposal with the summaries of its rules', async () => {
    renderWithSession(<RuleApprovalsPage />, {role: 'super_admin'});
    fireEvent.click(await screen.findByRole('tab', {name: 'Grup önerileri (1)'}));
    const card = await screen.findByRole('listitem', {name: 'Veri kalitesi'});
    expect(await within(card).findByText('NOLOCK kullanılmamalıdır.')).toBeInTheDocument();
    expect(within(card).getByText('yayımlanmış sürümde artık yok')).toBeInTheDocument();
  });

  it('shows the difference of a publish request and approves it', async () => {
    const approve = vi.spyOn(RuleProposalService, 'approveRequest').mockResolvedValue({...REQUEST_DETAIL, status: 'onaylandi', diff: null});
    renderWithSession(<RuleApprovalsPage />, {role: 'super_admin'});
    fireEvent.click(await screen.findByRole('tab', {name: 'Yayın istekleri (1)'}));
    const added = await screen.findByRole('region', {name: 'Eklenen kurallar'});
    expect(within(added).getByText('Yeni özet.')).toBeInTheDocument();
    expect(within(added).getByText('Yeni ayrıntılı metin.')).toBeInTheDocument();
    const changed = screen.getByRole('region', {name: 'Değişen kurallar'});
    expect(within(changed).getByText('Eski metin.')).toBeInTheDocument();
    expect(within(changed).getAllByText('Değişen metin.').length).toBeGreaterThan(0);
    expect(within(screen.getByRole('region', {name: 'Silinen gruplar'})).getByText('Eski grup')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Yayın isteği onayla'}));
    await waitFor(() => expect(approve).toHaveBeenCalledWith('r-1'));
  });

  it('warns that a request whose draft changed cannot be approved', async () => {
    vi.mocked(RuleProposalService.publishRequests).mockResolvedValue({
      items: [{...REQUEST, draft_changed: true}],
      page: 1,
      page_size: 100,
      total: 1,
    });
    renderWithSession(<RuleApprovalsPage />, {role: 'super_admin'});
    fireEvent.click(await screen.findByRole('tab', {name: 'Yayın istekleri (1)'}));
    expect(await screen.findByText(/Taslak bu istekten sonra değişti/)).toBeInTheDocument();
  });

  it('grants and revokes the proposal permission', async () => {
    vi.spyOn(RuleProposalService, 'proposers').mockResolvedValue({
      items: [
        {user_id: 'u-1', username: 'ayse', display_name: 'Ayşe İnceleyici', granted_by_name: 'Yönetici', granted_at: '2026-10-14T08:00:00Z'},
      ],
    });
    vi.spyOn(UserAdminService, 'list').mockResolvedValue({
      items: [
        {public_id: 'u-1', username: 'ayse', display_name: 'Ayşe İnceleyici', email: 'a@x', role: 'inceleyici', is_active: true, is_super_admin: false, account_type: 'directory', last_login_at: null},
        {public_id: 'u-2', username: 'can', display_name: 'Can Kural', email: 'c@x', role: 'kural-yoneticisi', is_active: true, is_super_admin: false, account_type: 'directory', last_login_at: null},
      ],
      page: 1,
      size: 20,
      total: 2,
    } as Awaited<ReturnType<typeof UserAdminService.list>>);
    const grant = vi.spyOn(RuleProposalService, 'grant').mockResolvedValue(undefined);
    const revoke = vi.spyOn(RuleProposalService, 'revoke').mockResolvedValue(undefined);
    renderWithSession(<RuleApprovalsPage />, {role: 'super_admin'});
    fireEvent.click(await screen.findByRole('tab', {name: 'Öneri yetkisi'}));
    fireEvent.click(await screen.findByRole('button', {name: 'Ayşe İnceleyici yetkisini kaldır'}));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith('u-1'));
    fireEvent.change(screen.getByLabelText('Kullanıcı ara'), {target: {value: 'a'}});
    fireEvent.click(screen.getByRole('button', {name: 'Ara'}));
    const results = await screen.findByRole('list', {name: 'Arama sonuçları'});
    expect(within(results).getByText('Yetkili')).toBeInTheDocument();
    fireEvent.click(within(results).getByRole('button', {name: 'Can Kural kullanıcısına yetki ver'}));
    await waitFor(() => expect(grant).toHaveBeenCalledWith('u-2'));
  });
});
