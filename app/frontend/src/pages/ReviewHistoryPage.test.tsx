import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import ReviewHistoryPage from './ReviewHistoryPage';
import * as download from '@/lib/download';
import {ReviewService} from '@/services/reviews';
import {apiError, renderWithSession} from '@/test/render';
import {storedResult} from '@/test/reviewEvents';
import type {ReviewRunDetail, ReviewRunSummary} from '@/types/sqlReview';

function summary(overrides: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    id: 'run-1',
    kind: 'object',
    status: 'completed',
    started_at: '2026-09-26T09:00:00Z',
    finished_at: '2026-09-26T09:05:00Z',
    title: 'DWH · 1 nesne',
    subtitle: '[DWH] dbo.usp_load (P)',
    error_code: null,
    error_message: null,
    rule_version: 2,
    object_count: 1,
    finding_count: 1,
    owner_display_name: 'Ayşe İnceleyici',
    owned: true,
    ...overrides,
  };
}

function detail(overrides: Partial<ReviewRunDetail> = {}): ReviewRunDetail {
  return {
    ...summary(),
    label: null,
    results: [storedResult()],
    results_page: 1,
    results_page_size: 50,
    all_rules: true,
    selected_rule_groups: [],
    ...overrides,
  };
}

const cancelled = summary({
  id: 'run-2',
  kind: 'script',
  status: 'cancelled',
  title: 'Yapıştırılan SQL',
  subtitle: null,
  finding_count: 0,
});

describe('review history page', () => {
  beforeEach(() => {
    vi.spyOn(ReviewService, 'runs').mockResolvedValue({items: [summary(), cancelled], page: 1, page_size: 50, total: 2});
    vi.spyOn(ReviewService, 'run').mockImplementation(async (id) =>
      id === 'run-1' ? detail() : detail({...cancelled, results: []}),
    );
  });

  it('lists own runs with status, version and counts; a reviewer has no scope choice', async () => {
    renderWithSession(<ReviewHistoryPage />);
    expect(await screen.findByText('DWH · 1 nesne')).toBeInTheDocument();
    expect(screen.getByText('Kural sürümü 2 · 1 nesne · 1 bulgu')).toBeInTheDocument();
    expect(screen.getByText('Durduruldu')).toBeInTheDocument();
    expect(screen.queryByLabelText('Tüm incelemeler')).toBeNull();
    expect(ReviewService.runs).toHaveBeenCalledWith('mine', 1, 50, expect.any(AbortSignal));
    expect(localStorage.length).toBe(0);
  });

  it('lets the rule manager switch to all runs, which are read-only when owned by others', async () => {
    vi.mocked(ReviewService.run).mockResolvedValue(detail({owned: false, owner_display_name: 'Başka Kişi'}));
    renderWithSession(<ReviewHistoryPage />, {role: 'super_admin'});
    await screen.findByText('DWH · 1 nesne');
    fireEvent.click(screen.getByLabelText('Tüm incelemeler'));
    await waitFor(() => expect(ReviewService.runs).toHaveBeenLastCalledWith('all', 1, 50, expect.any(AbortSignal)));
    fireEvent.click(screen.getByText('DWH · 1 nesne').closest('button')!);
    expect(await screen.findByText('Bu inceleme başka bir kullanıcıya ait; yalnız okunabilir.')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', {name: /yanlış pozitif/})).toBeNull();
    expect(screen.getByRole('button', {name: 'SQL indir'})).toBeEnabled();
  });

  it('opens a run with its results, marks a finding and downloads the CSV', async () => {
    const mark = vi.spyOn(ReviewService, 'markFinding').mockResolvedValue({id: 'f-1', false_positive: true, changed_at: null});
    const exportRun = vi
      .spyOn(ReviewService, 'exportRun')
      .mockResolvedValue({blob: new Blob(['a']), filename: 'sql-review-1.csv'});
    const save = vi.spyOn(download, 'saveFile').mockImplementation(() => undefined);
    renderWithSession(<ReviewHistoryPage />);
    fireEvent.click((await screen.findByText('DWH · 1 nesne')).closest('button')!);
    const finding = await screen.findByRole('checkbox', {name: 'Kural01 bulgu 1 yanlış pozitif'});
    fireEvent.click(finding);
    await waitFor(() => expect(finding).toBeChecked());
    expect(mark).toHaveBeenCalledWith('run-1', 'f-1', true);

    fireEvent.click(screen.getByRole('button', {name: 'CSV indir'}));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(exportRun).toHaveBeenCalledWith('run-1', 'csv');
    expect(save.mock.calls[0][1]).toBe('sql-review-1.csv');
  });

  it('opens the run named in the address, as a large review asks it to', async () => {
    renderWithSession(<ReviewHistoryPage />, {path: '/gecmis?run=run-1'});
    expect(await screen.findByRole('checkbox', {name: 'Kural01 bulgu 1 yanlış pozitif'})).toBeInTheDocument();
    expect(ReviewService.run).toHaveBeenCalledWith('run-1', 1, 50, expect.any(AbortSignal), true);
  });

  it('reads a large run page by page and keeps the downloads for the whole run', async () => {
    const pageOf = (page: number) =>
      detail({
        title: 'DWH · 120 nesne',
        object_count: 120,
        results_page: page,
        results: Array.from({length: page === 3 ? 20 : 50}, (_, index) =>
          storedResult({name: `usp_${(page - 1) * 50 + index + 1}`, error_code: 'object_not_found', rule_results: [], findings: []}),
        ),
      });
    vi.mocked(ReviewService.run).mockImplementation(async (_id, page) => pageOf(page));
    renderWithSession(<ReviewHistoryPage />, {path: '/gecmis?run=run-1'});

    expect(await screen.findByText('1–50 / 120')).toBeInTheDocument();
    expect(screen.getByText(/sayfa başına 50 nesne gösterilir/)).toBeInTheDocument();
    expect(screen.getByText(/usp_50\b/)).toBeInTheDocument();
    expect(screen.queryByText(/usp_51\b/)).toBeNull();
    // Every object of this page failed; other pages may still hold SQL text, so the button stays on.
    expect(screen.getByRole('button', {name: 'SQL indir'})).toBeEnabled();

    const detailCard = screen.getByText('1–50 / 120').closest('nav')!;
    fireEvent.click(within(detailCard).getByRole('button', {name: 'Sonraki'}));
    expect(await screen.findByText('51–100 / 120')).toBeInTheDocument();
    expect(ReviewService.run).toHaveBeenLastCalledWith('run-1', 2, 50, expect.any(AbortSignal), true);
    expect(screen.getByText(/usp_51\b/)).toBeInTheDocument();
  });

  it('disables SQL download for a run without stored SQL and explains a stopped run', async () => {
    renderWithSession(<ReviewHistoryPage />);
    fireEvent.click((await screen.findByText('Yapıştırılan SQL')).closest('button')!);
    expect(await screen.findByText('Bu inceleme durduruldu; kısmi sonuç saklanmaz.')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'SQL indir'})).toBeDisabled();
    expect(screen.getByText(/SQL indirme kapalı/)).toBeInTheDocument();
  });

  it('asks before deleting one run and reloads the list', async () => {
    const remove = vi.spyOn(ReviewService, 'deleteRun').mockResolvedValue(undefined);
    renderWithSession(<ReviewHistoryPage />);
    fireEvent.click(await screen.findByRole('button', {name: 'DWH · 1 nesne incelemesini sil'}));
    const dialog = screen.getByRole('dialog', {name: 'Bu inceleme silinsin mi?'});
    fireEvent.click(within(dialog).getByRole('button', {name: 'Vazgeç'}));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', {name: 'DWH · 1 nesne incelemesini sil'}));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', {name: 'Sil'}));
    await screen.findByText('İnceleme silindi.');
    expect(remove).toHaveBeenCalledWith('run-1');
    await waitFor(() => expect(ReviewService.runs).toHaveBeenCalledTimes(2));
  });

  it('deletes all own runs after confirmation and reports the count', async () => {
    vi.spyOn(ReviewService, 'deleteOwnRuns').mockResolvedValue({deleted_count: 2});
    renderWithSession(<ReviewHistoryPage />);
    await screen.findByText('DWH · 1 nesne');
    fireEvent.click(screen.getByRole('button', {name: 'Tümünü sil'}));
    const dialog = screen.getByRole('dialog', {name: 'Tüm incelemeleriniz silinsin mi?'});
    expect(within(dialog).getByText(/Başkalarının incelemelerine dokunulmaz/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', {name: 'Sil'}));
    expect(await screen.findByText('2 inceleme silindi.')).toBeInTheDocument();
  });

  it('shows why a running run cannot be deleted', async () => {
    vi.spyOn(ReviewService, 'deleteRun').mockRejectedValue(apiError(409, 'review_run_in_progress'));
    renderWithSession(<ReviewHistoryPage />);
    fireEvent.click(await screen.findByRole('button', {name: 'DWH · 1 nesne incelemesini sil'}));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', {name: 'Sil'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Süren bir inceleme silinemez.');
  });
});

describe('review history page — rule groups (rule-group-selection Requirement 6)', () => {
  beforeEach(() => {
    vi.spyOn(ReviewService, 'runs').mockResolvedValue({items: [summary()], page: 1, page_size: 50, total: 1});
  });

  it('shows the groups the run used', async () => {
    vi.spyOn(ReviewService, 'run').mockResolvedValue(
      detail({
        all_rules: false,
        selected_rule_groups: [
          {id: 'grp-perf', name: 'Performans'},
          {id: 'grp-sec', name: 'Güvenlik'},
        ],
      }),
    );
    renderWithSession(<ReviewHistoryPage />);
    fireEvent.click((await screen.findByText('DWH · 1 nesne')).closest('button')!);
    expect(await screen.findByText('Kural grupları: Performans, Güvenlik')).toBeInTheDocument();
  });

  it('says every rule ran when no group was selected', async () => {
    vi.spyOn(ReviewService, 'run').mockResolvedValue(detail());
    renderWithSession(<ReviewHistoryPage />);
    fireEvent.click((await screen.findByText('DWH · 1 nesne')).closest('button')!);
    expect(await screen.findByText('Kurallar: Tüm kurallar')).toBeInTheDocument();
  });

  it('shows the single rules the run used (Decision 6)', async () => {
    vi.spyOn(ReviewService, 'run').mockResolvedValue(
      detail({all_rules: false, selected_rule_codes: ['Kural03', 'Kural07']}),
    );
    renderWithSession(<ReviewHistoryPage />);
    fireEvent.click((await screen.findByText('DWH · 1 nesne')).closest('button')!);
    expect(await screen.findByText('Seçilen kurallar: Kural03, Kural07')).toBeInTheDocument();
  });
});

describe('review history page — scheduled runs (scheduled-review-email Requirement 6, Decision 12)', () => {
  it('marks a scheduled run in the list', async () => {
    vi.spyOn(ReviewService, 'runs').mockResolvedValue({
      items: [summary({kind: 'scheduled'})],
      page: 1,
      page_size: 50,
      total: 1,
    });
    vi.spyOn(ReviewService, 'run').mockResolvedValue(detail({kind: 'scheduled'}));
    renderWithSession(<ReviewHistoryPage />);
    expect(await screen.findByText('Zamanlanmış', {selector: '.badge'})).toBeInTheDocument();
  });

  it('opens a recipient run from the e-mail link although it is not in the list, read-only', async () => {
    vi.spyOn(ReviewService, 'runs').mockResolvedValue({items: [], page: 1, page_size: 50, total: 0});
    const read = vi
      .spyOn(ReviewService, 'run')
      .mockResolvedValue(detail({id: 'run-mail', kind: 'scheduled', owned: false, owner_display_name: 'Tanım Sahibi'}));
    renderWithSession(<ReviewHistoryPage />, {path: '/gecmis?run=run-mail'});
    expect(await screen.findByText('Bu inceleme başka bir kullanıcıya ait; yalnız okunabilir.')).toBeInTheDocument();
    expect(read).toHaveBeenCalledWith('run-mail', 1, 50, expect.any(AbortSignal), true);
    expect(screen.queryByRole('checkbox', {name: /yanlış pozitif/})).toBeNull();
    expect(screen.getByRole('button', {name: 'CSV indir'})).toBeEnabled();
  });
});
