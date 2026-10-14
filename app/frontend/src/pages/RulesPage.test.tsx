import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import RulesPage from './RulesPage';
import {RuleProposalService} from '@/services/ruleProposals';
import {RuleSetService} from '@/services/ruleSet';
import {apiError, renderWithSession} from '@/test/render';
import type {RuleSetVersionDetail, RuleSetWorkspace} from '@/types/sqlReview';

function workspace(overrides: Partial<RuleSetWorkspace> = {}): RuleSetWorkspace {
  return {
    revision: 4,
    next_rule_id: 'Kural12',
    draft_differs: false,
    critical: [
      {id: 'Kural01', text: 'NOLOCK kullanılmamalıdır.', summary: '', requires_metadata: false},
      {id: 'Kural05', text: 'Geçici tablolar açıkça silinmelidir.', summary: '', requires_metadata: true},
    ],
    normal: [{id: 'Kural11', text: 'Yorum satırı bulunmalıdır.', summary: '', requires_metadata: false}],
    groups: [],
    latest_version: {
      number: 1,
      published_at: '2026-04-10T14:05:15Z',
      published_by_name: null,
      source: 'ice-aktarim',
      critical_count: 2,
      normal_count: 1,
    },
    ...overrides,
  };
}

function version(number: number): RuleSetVersionDetail {
  return {
    number,
    published_at: '2026-09-26T10:00:00Z',
    published_by_name: 'Mehmet Kural',
    source: 'arayuz',
    critical: [],
    normal: [],
    groups: [],
    critical_count: 0,
    normal_count: 0,
  };
}

async function renderPage(role: 'kural-yoneticisi' | 'super_admin' = 'kural-yoneticisi') {
  renderWithSession(<RulesPage />, {role});
  await screen.findByRole('heading', {name: /Kritik/});
}

const NO_REQUESTS = {items: [], page: 1, page_size: 1, total: 0};

function column(name: RegExp) {
  return screen.getByRole('region', {name});
}

describe('rules page', () => {
  beforeEach(() => {
    vi.spyOn(RuleSetService, 'workspace').mockResolvedValue(workspace());
    vi.spyOn(RuleProposalService, 'publishRequests').mockResolvedValue(NO_REQUESTS);
  });

  it('shows both groups, the latest version line and the first 100 characters of each rule', async () => {
    vi.mocked(RuleSetService.workspace).mockResolvedValue(
      workspace({draft_differs: true, normal: [{id: 'Kural11', text: 'x'.repeat(150), summary: '', requires_metadata: false}]}),
    );
    await renderPage();
    expect(screen.getByText(/Son yayın: sürüm 1 · .* · içe aktarım/)).toBeInTheDocument();
    expect(screen.getByText('Taslakta yayımlanmamış değişiklik var')).toBeInTheDocument();
    expect(within(column(/Kritik/)).getByText('NOLOCK kullanılmamalıdır.')).toBeInTheDocument();
    expect(within(column(/Normal/)).getByText(`${'x'.repeat(100)}…`)).toBeInTheDocument();
  });

  it('filters by identifier or text', async () => {
    await renderPage();
    fireEvent.change(screen.getByLabelText('Kural ara'), {target: {value: 'geçici'}});
    expect(screen.getByText('Kural05')).toBeInTheDocument();
    expect(screen.queryByText('Kural01')).toBeNull();
    expect(within(column(/Normal/)).getByText('Bu grupta eşleşme yok.')).toBeInTheDocument();
  });

  it('moves, deletes and adds rules inside a group and marks the draft unsaved', async () => {
    await renderPage();
    expect(screen.queryByText('Kaydedilmedi')).toBeNull();
    fireEvent.click(within(column(/Kritik/)).getByText('Kural05'));
    fireEvent.click(screen.getByRole('button', {name: 'Kural05 yukarı taşı'}));
    const ids = within(column(/Kritik/)).getAllByText(/^Kural\d+$/).map((node) => node.textContent);
    expect(ids).toEqual(['Kural05', 'Kural01']);
    expect(screen.getByText('Kaydedilmedi')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Kural05 sil'}));
    expect(within(column(/Kritik/)).queryByText('Kural05')).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: 'Normal grubuna kural ekle'}));
    fireEvent.click(screen.getByRole('button', {name: 'Kritik grubuna kural ekle'}));
    expect(within(column(/Normal/)).getByText('Kural12')).toBeInTheDocument();
    expect(within(column(/Kritik/)).getByText('Kural13')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Kural12 kural metni'), {target: {value: 'Yeni kural'}});
    const metadata = screen.getByLabelText(/Kural12: Nesne meta verisi gerekir/);
    fireEvent.click(metadata);
    expect(metadata).toBeChecked();
  });

  it('saves the draft with the revision it last saw', async () => {
    const save = vi.spyOn(RuleSetService, 'saveDraft').mockResolvedValue(workspace({revision: 5}));
    await renderPage();
    fireEvent.click(screen.getByRole('button', {name: 'Normal grubuna kural ekle'}));
    fireEvent.change(screen.getByLabelText('Kural12 kural metni'), {target: {value: 'Yeni kural'}});
    fireEvent.click(screen.getByRole('button', {name: 'Taslağı kaydet'}));
    await screen.findByText('Taslak kaydedildi.');
    expect(save).toHaveBeenCalledWith(4, workspace().critical, [
      ...workspace().normal,
      {id: 'Kural12', text: 'Yeni kural', summary: '', requires_metadata: false, rule_group_ids: []},
    ], []);
  });

  it('lets the super admin save unsaved changes before publishing and report the new version', async () => {
    const save = vi.spyOn(RuleSetService, 'saveDraft').mockResolvedValue(workspace({revision: 5}));
    const publish = vi.spyOn(RuleSetService, 'publish').mockResolvedValue(version(2));
    await renderPage('super_admin');
    fireEvent.click(screen.getByRole('button', {name: 'Kritik grubuna kural ekle'}));
    fireEvent.change(screen.getByLabelText('Kural12 kural metni'), {target: {value: 'Yeni'}});
    vi.mocked(RuleSetService.workspace).mockResolvedValue(workspace({revision: 5}));
    fireEvent.click(screen.getByRole('button', {name: 'Yayınla'}));
    await screen.findByText(/Sürüm 2 yayımlandı/);
    expect(save).toHaveBeenCalledTimes(1);
    expect(publish).toHaveBeenCalledWith(5);
    expect(save.mock.invocationCallOrder[0]).toBeLessThan(publish.mock.invocationCallOrder[0]);
  });

  it('lets the super admin publish directly when nothing is unsaved', async () => {
    const save = vi.spyOn(RuleSetService, 'saveDraft');
    vi.spyOn(RuleSetService, 'publish').mockResolvedValue(version(1));
    await renderPage('super_admin');
    fireEvent.click(screen.getByRole('button', {name: 'Yayınla'}));
    await screen.findByText('Taslak son sürümle aynı; yeni sürüm oluşmadı (sürüm 1).');
    expect(save).not.toHaveBeenCalled();
  });

  it('shows the 409 message with a reload button when someone else changed the rules', async () => {
    vi.spyOn(RuleSetService, 'saveDraft').mockRejectedValue(apiError(409, 'rule_set_draft_conflict'));
    await renderPage();
    fireEvent.click(screen.getByRole('button', {name: 'Normal grubuna kural ekle'}));
    fireEvent.change(screen.getByLabelText('Kural12 kural metni'), {target: {value: 'x'}});
    fireEvent.click(screen.getByRole('button', {name: 'Taslağı kaydet'}));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Kurallar başka biri tarafından değiştirildi; sayfayı yenileyin.',
    );
    fireEvent.click(screen.getByRole('button', {name: 'Sayfayı yenile'}));
    await waitFor(() => expect(RuleSetService.workspace).toHaveBeenCalledTimes(2));
  });

  it('refuses a rule text over 8,000 characters before sending it', async () => {
    await renderPage();
    fireEvent.click(within(column(/Normal/)).getByText('Kural11'));
    fireEvent.change(screen.getByLabelText('Kural11 kural metni'), {target: {value: 'a'.repeat(8001)}});
    expect(screen.getByRole('button', {name: 'Taslağı kaydet'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Onaya gönder'})).toBeDisabled();
  });
});

describe('rules page — summaries and approval (rule-management Requirement 12, rule-proposals Requirement 6)', () => {
  beforeEach(() => {
    vi.spyOn(RuleSetService, 'workspace').mockResolvedValue(workspace());
    vi.spyOn(RuleProposalService, 'publishRequests').mockResolvedValue(NO_REQUESTS);
  });

  it('edits a rule summary and refuses one over 200 characters or on two lines', async () => {
    const save = vi.spyOn(RuleSetService, 'saveDraft').mockResolvedValue(workspace({revision: 5}));
    await renderPage();
    fireEvent.click(within(column(/Kritik/)).getByText('Kural01'));
    const summary = screen.getByLabelText('Kural01: Özet (tek cümle)');
    expect(summary).toHaveAttribute('placeholder', 'NOLOCK kullanılmamalıdır.');
    fireEvent.change(summary, {target: {value: 'x'.repeat(201)}});
    expect(screen.getByText('Kural özeti en çok 200 karakter olabilir.')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Taslağı kaydet'})).toBeDisabled();
    fireEvent.change(summary, {target: {value: 'Kirli okuma yapılmaz.'}});
    fireEvent.click(screen.getByRole('button', {name: 'Taslağı kaydet'}));
    await screen.findByText('Taslak kaydedildi.');
    expect(save.mock.calls[0][1][0].summary).toBe('Kirli okuma yapılmaz.');
  });

  it('offers the rule manager "Onaya gönder" instead of publishing; it saves first', async () => {
    const save = vi.spyOn(RuleSetService, 'saveDraft').mockResolvedValue(workspace({revision: 5}));
    const publish = vi.spyOn(RuleSetService, 'publish');
    const request = vi.spyOn(RuleProposalService, 'requestPublish').mockResolvedValue({
      id: 'req-1',
      status: 'bekliyor',
      requester_name: 'Mehmet Kural',
      created_at: '2026-10-14T10:00:00Z',
      draft_revision: 5,
      draft_changed: false,
      decided_by_name: null,
      decided_at: null,
      rejection_reason: null,
      published_version_number: null,
      owned: true,
      diff: null,
    });
    await renderPage();
    expect(screen.queryByRole('button', {name: 'Yayınla'})).toBeNull();
    fireEvent.click(screen.getByRole('button', {name: 'Normal grubuna kural ekle'}));
    fireEvent.change(screen.getByLabelText('Kural12 kural metni'), {target: {value: 'Yeni'}});
    fireEvent.click(screen.getByRole('button', {name: 'Onaya gönder'}));
    await screen.findByText('Taslak onaya gönderildi. Süper yönetici onaylayınca yeni sürüm yayımlanır.');
    expect(request).toHaveBeenCalledWith(5);
    expect(save.mock.invocationCallOrder[0]).toBeLessThan(request.mock.invocationCallOrder[0]);
    expect(publish).not.toHaveBeenCalled();
  });

  it('shows the rejection reason of the latest publish request', async () => {
    vi.mocked(RuleProposalService.publishRequests).mockResolvedValue({
      items: [
        {
          id: 'req-1',
          status: 'reddedildi',
          requester_name: 'Mehmet Kural',
          created_at: '2026-10-14T10:00:00Z',
          draft_revision: 4,
          draft_changed: false,
          decided_by_name: 'Uygulama Yöneticisi',
          decided_at: '2026-10-14T11:00:00Z',
          rejection_reason: 'Kural metni belirsiz.',
          published_version_number: null,
          owned: true,
        },
      ],
      page: 1,
      page_size: 1,
      total: 1,
    });
    await renderPage();
    expect(await screen.findByText('Son yayın isteği: reddedildi · gerekçe: Kural metni belirsiz.')).toBeInTheDocument();
  });
});

describe('rules page — named rule groups (rule-group-selection Requirement 1, 8)', () => {
  const performance = {id: 'grp-perf', name: 'Performans', description: ''};

  function grouped() {
    const base = workspace();
    return workspace({
      groups: [performance],
      critical: [{...base.critical[0], rule_group_ids: ['grp-perf']}, base.critical[1]],
    });
  }

  beforeEach(() => {
    vi.spyOn(RuleSetService, 'workspace').mockResolvedValue(grouped());
    vi.spyOn(RuleProposalService, 'publishRequests').mockResolvedValue(NO_REQUESTS);
  });

  it('shows each group with its rule count and each rule with its group', async () => {
    await renderPage();
    const groups = screen.getByRole('region', {name: /Kural grupları/});
    expect(within(groups).getByLabelText('Kural grubu 1 adı')).toHaveValue('Performans');
    expect(within(groups).getByText('1 kural')).toBeInTheDocument();
    expect(within(column(/Kritik/)).getByText('Performans')).toBeInTheDocument();
  });

  it('adds, renames and assigns groups, a rule to several, then saves them with the draft', async () => {
    const save = vi.spyOn(RuleSetService, 'saveDraft').mockResolvedValue(workspace({revision: 5}));
    await renderPage();
    fireEvent.click(screen.getByRole('button', {name: 'Kural grubu ekle'}));
    fireEvent.change(screen.getByLabelText('Kural grubu 2 adı'), {target: {value: 'Güvenlik'}});
    fireEvent.click(within(column(/Kritik/)).getByText('Kural05'));
    const kural05 = screen.getByRole('group', {name: 'Kural05: Kural grupları'});
    fireEvent.click(within(kural05).getByLabelText('Güvenlik'));
    fireEvent.click(within(kural05).getByLabelText('Performans'));
    expect(screen.getByText('Kaydedilmedi')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Taslağı kaydet'}));
    await screen.findByText('Taslak kaydedildi.');

    const [, critical, , groups] = save.mock.calls[0];
    expect(groups.map((group) => group.name)).toEqual(['Performans', 'Güvenlik']);
    const security = groups[1].id;
    expect(security).toMatch(/^[0-9a-f-]{36}$/);
    expect(critical.map((rule) => rule.rule_group_ids)).toEqual([['grp-perf'], [security, 'grp-perf']]);
  });

  it('removes the memberships of a removed group', async () => {
    const save = vi.spyOn(RuleSetService, 'saveDraft').mockResolvedValue(workspace({revision: 5}));
    await renderPage();
    fireEvent.click(screen.getByRole('button', {name: 'Performans grubunu sil'}));
    expect(within(column(/Kritik/)).queryByText('Performans')).toBeNull();
    fireEvent.click(screen.getByRole('button', {name: 'Taslağı kaydet'}));
    await screen.findByText('Taslak kaydedildi.');
    const [, critical, , groups] = save.mock.calls[0];
    expect(groups).toEqual([]);
    expect(critical.map((rule) => rule.rule_group_ids ?? [])).toEqual([[], []]);
  });

  it('blocks saving while a group name is empty or repeated', async () => {
    await renderPage();
    fireEvent.click(screen.getByRole('button', {name: 'Kural grubu ekle'}));
    fireEvent.change(screen.getByLabelText('Kural grubu 2 adı'), {target: {value: 'PERFORMANS'}});
    expect(screen.getByText('Aynı adla iki kural grubu tanımlanamaz.')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Taslağı kaydet'})).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Kural grubu 2 adı'), {target: {value: '  '}});
    expect(screen.getByText('Kural grubu adı boş olamaz.')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Onaya gönder'})).toBeDisabled();
  });
});
