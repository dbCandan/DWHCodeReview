import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import ScheduledReviewsPage, {EMAIL_NOTE} from './ScheduledReviewsPage';
import {CatalogService} from '@/services/catalog';
import {RuleSetService} from '@/services/ruleSet';
import {ScheduledReviewService} from '@/services/scheduledReviews';
import {apiError, renderWithSession} from '@/test/render';
import type {ScheduledReviewDetail, ScheduledReviewItem, ScheduledRunItem} from '@/types/sqlReview';

function item(overrides: Partial<ScheduledReviewItem> = {}): ScheduledReviewItem {
  return {
    id: 'sch-1',
    name: 'Gece taraması',
    owner_display_name: 'Ayşe İnceleyici',
    owned: true,
    selection: {mode: 'filter', filter: {database: 'DWH', query: null, type_code: 'P', from_date: null}, items: []},
    selection_summary: 'DWH · tür: P',
    rule_groups: [{id: 'grp-sec', name: 'Güvenlik'}],
    period: {frequency: 'daily', hour: 7, minute: 30, timezone: 'Europe/Istanbul', weekday: null, day_of_month: null},
    recipient_count: 2,
    status: 'active',
    next_run_at: '2026-10-08T04:30:00Z',
    last_run: null,
    missed: false,
    email_failed: false,
    can_edit: true,
    can_run_now: false,
    ...overrides,
  };
}

function detail(overrides: Partial<ScheduledReviewDetail> = {}): ScheduledReviewDetail {
  return {...item(), recipients: ['ayse@kurum.example', 'ali@kurum.example'], ...overrides};
}

function page(items: ScheduledReviewItem[]) {
  return {items, page: 1, page_size: 50, total: items.length};
}

function run(overrides: Partial<ScheduledRunItem> = {}): ScheduledRunItem {
  return {
    id: 'rec-1',
    review_run_id: 'run-9',
    due_at: '2026-10-07T04:30:00Z',
    trigger: 'scheduled',
    triggered_by_name: null,
    state: 'completed',
    skip_reason: null,
    started_at: '2026-10-07T04:30:05Z',
    finished_at: '2026-10-07T04:35:00Z',
    finding_count: 3,
    email_status: 'sent',
    email_attempts: 1,
    ...overrides,
  };
}

describe('scheduled reviews page (scheduled-review-email Requirement 9)', () => {
  beforeEach(() => {
    vi.spyOn(RuleSetService, 'latest').mockRejectedValue(apiError(404, 'no_published_rule_set'));
    vi.spyOn(CatalogService, 'databases').mockResolvedValue({items: ['DWH', 'MART'], page: 1, page_size: 500, total: 2});
  });

  it('lists definitions with their period, groups, next run and warnings', async () => {
    vi.spyOn(ScheduledReviewService, 'list').mockResolvedValue(
      page([
        item(),
        item({
          id: 'sch-2',
          name: 'Haftalık rapor',
          owned: false,
          owner_display_name: 'Başka Kişi',
          rule_groups: [],
          status: 'paused',
          next_run_at: null,
          period: {frequency: 'weekly', hour: 9, minute: 0, timezone: 'Europe/Istanbul', weekday: 0, day_of_month: null},
          last_run: {
            due_at: '2026-10-05T06:00:00Z',
            trigger: 'missed',
            state: 'missed',
            email_status: null,
            finding_count: null,
            review_run_id: null,
          },
          missed: true,
          email_failed: true,
        }),
      ]),
    );
    renderWithSession(<ScheduledReviewsPage />);
    const first = await screen.findByRole('article', {name: 'Gece taraması'});
    expect(within(first).getByText('Her gün 07:30 (Europe/Istanbul)')).toBeInTheDocument();
    expect(within(first).getByText('Güvenlik')).toBeInTheDocument();
    expect(within(first).getByText('Etkin')).toBeInTheDocument();
    expect(within(first).getByText('Henüz çalışmadı')).toBeInTheDocument();
    expect(within(first).queryByRole('button', {name: /şimdi çalıştır/})).toBeNull();

    const second = screen.getByRole('article', {name: 'Haftalık rapor'});
    expect(within(second).getByText(/Başka Kişi/)).toBeInTheDocument();
    expect(within(second).getByText('Tüm kurallar')).toBeInTheDocument();
    expect(within(second).getByText('Her pazartesi 09:00 (Europe/Istanbul)')).toBeInTheDocument();
    expect(within(second).getByText('Duraklatıldı')).toBeInTheDocument();
    expect(within(second).getByText('Kaçırıldı', {selector: '.badge'})).toBeInTheDocument();
    expect(within(second).getByText('E-posta gönderilemedi', {selector: '.badge'})).toBeInTheDocument();
  });

  it('creates a definition with a filter, a period and recipients', async () => {
    const list = vi.spyOn(ScheduledReviewService, 'list').mockResolvedValue(page([]));
    const create = vi.spyOn(ScheduledReviewService, 'create').mockResolvedValue(detail());
    renderWithSession(<ScheduledReviewsPage />);
    fireEvent.click(await screen.findByRole('button', {name: 'Yeni zamanlanmış inceleme'}));
    const dialog = await screen.findByRole('dialog', {name: 'Yeni zamanlanmış inceleme'});
    expect(within(dialog).getByText(EMAIL_NOTE, {exact: false})).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText('Ad'), {target: {value: '  Gece taraması '}});
    await within(dialog).findByRole('option', {name: 'DWH'});
    fireEvent.change(within(dialog).getByLabelText('Veritabanı'), {target: {value: 'DWH'}});
    fireEvent.change(within(dialog).getByLabelText('Tür'), {target: {value: 'P'}});
    fireEvent.change(within(dialog).getByLabelText('Sıklık'), {target: {value: 'monthly'}});
    fireEvent.change(within(dialog).getByLabelText('Ayın günü'), {target: {value: '5'}});
    fireEvent.change(within(dialog).getByLabelText('Saat'), {target: {value: '06:15'}});
    fireEvent.change(within(dialog).getByLabelText('Alıcılar'), {
      target: {value: 'ayse@kurum.example\nali@kurum.example, '},
    });
    fireEvent.click(within(dialog).getByRole('button', {name: 'Kaydet'}));

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0]).toEqual({
      name: 'Gece taraması',
      selection: {
        mode: 'filter',
        filter: {database: 'DWH', query: null, type_code: 'P', from_date: null},
        items: [],
      },
      rule_group_ids: [],
      period: {frequency: 'monthly', hour: 6, minute: 15, timezone: 'Europe/Istanbul', weekday: null, day_of_month: 5},
      recipients: ['ayse@kurum.example', 'ali@kurum.example'],
    });
    expect(await screen.findByText('Zamanlanmış inceleme oluşturuldu.')).toBeInTheDocument();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('checks the form before sending and shows the server refusal', async () => {
    vi.spyOn(ScheduledReviewService, 'list').mockResolvedValue(page([]));
    const create = vi
      .spyOn(ScheduledReviewService, 'create')
      .mockRejectedValue(apiError(422, 'recipient_domain_not_allowed'));
    renderWithSession(<ScheduledReviewsPage />);
    fireEvent.click(await screen.findByRole('button', {name: 'Yeni zamanlanmış inceleme'}));
    const dialog = await screen.findByRole('dialog', {name: 'Yeni zamanlanmış inceleme'});
    fireEvent.click(within(dialog).getByRole('button', {name: 'Kaydet'}));
    expect(within(dialog).getByText('Ad 1-120 karakter olmalıdır.')).toBeInTheDocument();
    expect(within(dialog).getByText('Bir veritabanı seçin.')).toBeInTheDocument();
    expect(within(dialog).getByText('En az bir alıcı girin.')).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText('Ad'), {target: {value: 'Gece'}});
    await within(dialog).findByRole('option', {name: 'DWH'});
    fireEvent.change(within(dialog).getByLabelText('Veritabanı'), {target: {value: 'DWH'}});
    fireEvent.change(within(dialog).getByLabelText('Alıcılar'), {target: {value: 'ayse@gmail'}});
    fireEvent.click(within(dialog).getByRole('button', {name: 'Kaydet'}));
    expect(within(dialog).getByText('Alıcı e-posta adreslerinden biri geçersiz.')).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText('Alıcılar'), {target: {value: 'ayse@gmail.com'}});
    fireEvent.click(within(dialog).getByRole('button', {name: 'Kaydet'}));
    expect(await within(dialog).findByText('Alıcı yalnız kurum e-posta alan adlarından olabilir.')).toBeInTheDocument();
  });

  it('edits a definition into a weekly one from its stored values', async () => {
    vi.spyOn(ScheduledReviewService, 'list').mockResolvedValue(page([item()]));
    vi.spyOn(ScheduledReviewService, 'get').mockResolvedValue(detail());
    const update = vi.spyOn(ScheduledReviewService, 'update').mockResolvedValue(detail());
    renderWithSession(<ScheduledReviewsPage />);
    fireEvent.click(await screen.findByRole('button', {name: 'Gece taraması tanımını düzenle'}));
    // The dialog shows a loading state first, then the form with the stored values.
    expect(await screen.findByDisplayValue('Gece taraması')).toBeInTheDocument();
    const dialog = screen.getByRole('dialog', {name: 'Zamanlanmış incelemeyi düzenle'});
    expect(within(dialog).getByLabelText('Alıcılar')).toHaveValue('ayse@kurum.example\nali@kurum.example');
    fireEvent.change(within(dialog).getByLabelText('Sıklık'), {target: {value: 'weekly'}});
    fireEvent.change(within(dialog).getByLabelText('Gün'), {target: {value: '4'}});
    fireEvent.click(within(dialog).getByRole('button', {name: 'Kaydet'}));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][0]).toBe('sch-1');
    expect(update.mock.calls[0][1].period).toEqual({
      frequency: 'weekly',
      hour: 7,
      minute: 30,
      timezone: 'Europe/Istanbul',
      weekday: 4,
      day_of_month: null,
    });
    expect(update.mock.calls[0][1].rule_group_ids).toEqual(['grp-sec']);
  });

  it('pauses, runs now as the super admin and explains a running refusal', async () => {
    vi.spyOn(ScheduledReviewService, 'list').mockResolvedValue(page([item({can_run_now: true})]));
    const pause = vi.spyOn(ScheduledReviewService, 'pause').mockResolvedValue(detail({status: 'paused'}));
    const runNow = vi
      .spyOn(ScheduledReviewService, 'runNow')
      .mockResolvedValueOnce({id: 'rec-2', state: 'queued'})
      .mockRejectedValueOnce(apiError(409, 'scheduled_review_running'));
    renderWithSession(<ScheduledReviewsPage />, {role: 'super_admin'});
    fireEvent.click(await screen.findByRole('button', {name: 'Gece taraması tanımını duraklat'}));
    expect(await screen.findByText('Tanım duraklatıldı.')).toBeInTheDocument();
    expect(pause).toHaveBeenCalledWith('sch-1');

    fireEvent.click(screen.getByRole('button', {name: 'Gece taraması şimdi çalıştır'}));
    expect(await screen.findByText('Koşum sıraya alındı.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Gece taraması şimdi çalıştır'}));
    expect(await screen.findByText('Bu tanımın bir koşumu sırada bekliyor veya sürüyor.')).toBeInTheDocument();
    expect(runNow).toHaveBeenCalledTimes(2);
  });

  it('shows the run history with its warnings and the report link', async () => {
    vi.spyOn(ScheduledReviewService, 'list').mockResolvedValue(page([item()]));
    vi.spyOn(ScheduledReviewService, 'runs').mockResolvedValue({
      items: [
        run({email_status: 'failed', email_attempts: 4}),
        run({id: 'rec-0', review_run_id: null, trigger: 'missed', state: 'missed', started_at: null, finding_count: null, email_status: null}),
        run({id: 'rec-3', review_run_id: null, state: 'skipped', skip_reason: 'previous_running', finding_count: null, email_status: null}),
        run({id: 'rec-4', trigger: 'manual', triggered_by_name: 'Uygulama Yöneticisi', email_status: 'not_configured'}),
        run({id: 'rec-5', review_run_id: null, state: 'failed', error_code: 'sql_connection_not_configured', finding_count: null, email_status: null}),
      ],
      page: 1,
      page_size: 20,
      total: 5,
    });
    renderWithSession(<ScheduledReviewsPage />);
    fireEvent.click(await screen.findByRole('button', {name: 'Gece taraması çalışma geçmişi'}));
    const dialog = await screen.findByRole('dialog', {name: 'Gece taraması — çalışma geçmişi'});
    await within(dialog).findAllByRole('row');
    expect(within(dialog).getByText('E-posta gönderilemedi', {selector: '.badge'})).toBeInTheDocument();
    expect(within(dialog).getAllByText('Kaçırıldı').length).toBeGreaterThan(0);
    expect(within(dialog).getByText('Atlandı (önceki koşum sürüyor)')).toBeInTheDocument();
    expect(within(dialog).getByText('Elle tetiklendi (Uygulama Yöneticisi)')).toBeInTheDocument();
    expect(within(dialog).getByText('E-posta yapılandırılmadı')).toBeInTheDocument();
    expect(within(dialog).getByText('SQL Server bağlantısı yapılandırılmamış.')).toBeInTheDocument();
    expect(within(dialog).getAllByRole('link', {name: 'Raporu aç'})[0]).toHaveAttribute('href', '/gecmis?run=run-9');
  });

  it('asks before deleting a definition', async () => {
    vi.spyOn(ScheduledReviewService, 'list').mockResolvedValue(page([item()]));
    const remove = vi.spyOn(ScheduledReviewService, 'remove').mockResolvedValue(undefined);
    renderWithSession(<ScheduledReviewsPage />);
    fireEvent.click(await screen.findByRole('button', {name: 'Gece taraması tanımını sil'}));
    const confirm = await screen.findByRole('dialog', {name: 'Zamanlanmış inceleme silinsin mi?'});
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(within(confirm).getByRole('button', {name: 'Sil'}));
    expect(await screen.findByText('Zamanlanmış inceleme silindi.')).toBeInTheDocument();
    expect(remove).toHaveBeenCalledWith('sch-1');
  });
});
