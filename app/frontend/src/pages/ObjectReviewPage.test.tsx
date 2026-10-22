import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import ObjectReviewPage from './ObjectReviewPage';
import {CatalogService, type ObjectQuery} from '@/services/catalog';
import {ReviewService} from '@/services/reviews';
import {RuleSetService} from '@/services/ruleSet';
import {apiError, renderWithSession} from '@/test/render';
import type {CatalogObject, CatalogObjectPage} from '@/types/sqlReview';

function objects(prefix: string, count: number): CatalogObject[] {
  return Array.from({length: count}, (_, index) => ({
    schema: 'dbo',
    name: `${prefix}_${String(index + 1).padStart(2, '0')}`,
    type: 'PROCEDURE',
    type_code: 'P',
    created_at: '2026-01-02T10:00:00Z',
    last_modified: '2026-03-04T10:00:00Z',
  }));
}

function page(items: CatalogObject[]): CatalogObjectPage {
  return {items, page: 1, page_size: 100, total: items.length};
}

async function chooseDatabase(name: string) {
  const select = await screen.findByLabelText('Veritabanı');
  await waitFor(() => expect(select).toBeEnabled());
  fireEvent.change(select, {target: {value: name}});
}

const GROUPED_VERSION = {
  number: 3,
  published_at: '2026-10-06T10:00:00Z',
  published_by_name: 'Mehmet Kural',
  source: 'arayuz' as const,
  critical: [{id: 'Kural01', text: 'a', summary: '', requires_metadata: false, rule_group_ids: ['grp-sec']}],
  normal: [{id: 'Kural09', text: 'b', summary: '', requires_metadata: false, rule_group_ids: ['grp-perf']}],
  groups: [
    {id: 'grp-perf', name: 'Performans', description: ''},
    {id: 'grp-sec', name: 'Güvenlik', description: ''},
  ],
  critical_count: 1,
  normal_count: 1,
};

describe('object review page', () => {
  beforeEach(() => {
    // No published groups unless a test publishes some: the picker then stays hidden.
    vi.spyOn(RuleSetService, 'latest').mockRejectedValue(apiError(404, 'no_published_rule_set'));
    vi.spyOn(CatalogService, 'databases').mockResolvedValue({items: ['DWH', 'MART'], page: 1, page_size: 500, total: 2});
    vi.spyOn(CatalogService, 'objects').mockImplementation(async (database) =>
      page(objects(database === 'DWH' ? 'dwh' : 'mart', database === 'DWH' ? 40 : 30)),
    );
  });

  it('offers every database the server returns in the picker', async () => {
    // sql-server-connection Requirement 7: no list narrows what the account can access.
    const items = Array.from({length: 25}, (_, index) => `DB_${String(index + 1).padStart(2, '0')}`);
    vi.mocked(CatalogService.databases).mockResolvedValue({items, page: 1, page_size: 500, total: 25});
    renderWithSession(<ObjectReviewPage />);
    const select = await screen.findByLabelText('Veritabanı');
    await waitFor(() => expect(select).toBeEnabled());
    const offered = within(select)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(offered).toEqual(['— Veritabanı seçin —', ...items]);
  });

  it('says so when the account can access no database', async () => {
    vi.mocked(CatalogService.databases).mockResolvedValue({items: [], page: 1, page_size: 500, total: 0});
    renderWithSession(<ObjectReviewPage />);
    expect(await screen.findByText('Bağlantı hesabının erişebildiği çevrimiçi veritabanı yok.')).toBeInTheDocument();
    expect(screen.queryByText(/İzinli/)).toBeNull();
  });

  it('shows the fixed message when a system database is requested', async () => {
    vi.mocked(CatalogService.objects).mockRejectedValue(apiError(403, 'database_not_allowed'));
    renderWithSession(<ObjectReviewPage />);
    await chooseDatabase('DWH');
    expect(await screen.findByText('Sistem veritabanları incelenemez.')).toBeInTheDocument();
  });

  it('shows a Turkish error and a refresh button when SQL Server is unreachable', async () => {
    vi.mocked(CatalogService.databases).mockRejectedValue(apiError(503, 'sql_server_unreachable'));
    renderWithSession(<ObjectReviewPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent("SQL Server'a ulaşılamadı.");
    vi.mocked(CatalogService.databases).mockResolvedValue({items: ['DWH'], page: 1, page_size: 500, total: 1});
    fireEvent.click(screen.getByRole('button', {name: 'Listeyi yenile'}));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('sends the text, type and date filters to the server', async () => {
    renderWithSession(<ObjectReviewPage />);
    await chooseDatabase('DWH');
    await screen.findByText('dwh_01');
    fireEvent.change(screen.getByLabelText('Ara'), {target: {value: 'load'}});
    fireEvent.change(screen.getByLabelText('Tür'), {target: {value: 'V'}});
    fireEvent.change(screen.getByLabelText('Değişiklik tarihi (sonrası)'), {
      target: {value: '2026-02-01'},
    });
    await waitFor(() =>
      expect(vi.mocked(CatalogService.objects)).toHaveBeenLastCalledWith(
        'DWH',
        {q: 'load', type: 'V', fromDate: '2026-02-01', page: 1, pageSize: 100} satisfies ObjectQuery,
        expect.any(AbortSignal),
      ),
    );
  });

  it('keeps selections across databases, counts databases and has no object limit', async () => {
    const stream = vi.spyOn(ReviewService, 'streamObjectReview').mockResolvedValue(undefined);
    renderWithSession(<ObjectReviewPage />);
    await chooseDatabase('DWH');
    await screen.findByText('dwh_01');
    fireEvent.click(screen.getByLabelText('Görünen nesnelerin tümünü seç'));
    expect(screen.getByText('40 seçili · 1 veritabanı')).toBeInTheDocument();

    await chooseDatabase('MART');
    await screen.findByText('mart_01');
    fireEvent.click(screen.getByLabelText('Görünen nesnelerin tümünü seç'));
    // object-review Decision 3: the 51st and every later object is selected like the first.
    expect(screen.getByText('70 seçili · 2 veritabanı')).toBeInTheDocument();
    expect(screen.queryByText(/En çok/)).toBeNull();
    expect(screen.queryByText(/\/ 50/)).toBeNull();
    expect(screen.getByLabelText('dbo.mart_30 seç')).toBeChecked();
    expect(screen.getByLabelText('dbo.mart_30 seç')).toBeEnabled();
    fireEvent.click(screen.getByText('mart_12'));
    expect(screen.getByLabelText('dbo.mart_12 seç')).not.toBeChecked();
    expect(screen.getByText('69 seçili · 2 veritabanı')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Seçilen 69 nesneyi incele'}));
    await waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
    const selections = stream.mock.calls[0][0];
    expect(selections).toHaveLength(69);
    expect(selections[0]).toEqual({database: 'DWH', schema: 'dbo', name: 'dwh_01', type_code: 'P'});
    expect(selections.at(-1)).toEqual({database: 'MART', schema: 'dbo', name: 'mart_30', type_code: 'P'});
  });

  it('selects every object matching the filter across all pages without rendering them', async () => {
    const total = 1_234;
    const all = objects('big', total);
    vi.mocked(CatalogService.objects).mockImplementation(async (_database, query) => ({
      items: all.slice((query.page - 1) * query.pageSize, query.page * query.pageSize),
      page: query.page,
      page_size: query.pageSize,
      total,
    }));
    const stream = vi.spyOn(ReviewService, 'streamObjectReview').mockResolvedValue(undefined);
    renderWithSession(<ObjectReviewPage />);
    await chooseDatabase('DWH');
    await screen.findByText('big_01');
    fireEvent.change(screen.getByLabelText('Tür'), {target: {value: 'P'}});
    const selectAll = await screen.findByRole('button', {name: 'Süzgece uyan 1.234 nesnenin tümünü seç'});

    fireEvent.click(selectAll);

    expect(await screen.findByText('Süzgece uyan 1.234 nesne seçildi.')).toBeInTheDocument();
    expect(screen.getByText('1.234 seçili · 1 veritabanı')).toBeInTheDocument();
    // Pages of 500 with the filter of the list; the table still shows one page of 100 rows.
    const gathered = vi
      .mocked(CatalogService.objects)
      .mock.calls.filter(([, query]) => query.pageSize === 500)
      .map(([database, query]) => [database, query.page, query.type]);
    expect(gathered).toEqual([
      ['DWH', 1, 'P'],
      ['DWH', 2, 'P'],
      ['DWH', 3, 'P'],
    ]);
    expect(screen.getAllByRole('row')).toHaveLength(101);
    expect(screen.getByText(/Büyük seçim/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Seçilen 1234 nesneyi incele'}));
    await waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
    expect(stream.mock.calls[0][0]).toHaveLength(total);

    fireEvent.click(screen.getByRole('button', {name: 'Seçimi temizle'}));
    expect(screen.getByText('0 seçili · 0 veritabanı')).toBeInTheDocument();
    expect(screen.queryByText(/nesne seçildi\./)).toBeNull();
    expect(screen.queryByText(/Büyük seçim/)).toBeNull();
  });

  it('adds the matching objects to an existing selection and can be stopped', async () => {
    const total = 1_200;
    const all = objects('big', total);
    let release: (() => void) | null = null;
    vi.mocked(CatalogService.objects).mockImplementation(async (_database, query, signal) => {
      if (query.pageSize === 500 && query.page === 2) {
        await new Promise<void>((resolve, reject) => {
          release = resolve;
          signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        });
      }
      return {
        items: all.slice((query.page - 1) * query.pageSize, query.page * query.pageSize),
        page: query.page,
        page_size: query.pageSize,
        total,
      };
    });
    renderWithSession(<ObjectReviewPage />);
    await chooseDatabase('DWH');
    fireEvent.click(await screen.findByText('big_03'));
    expect(screen.getByText('1 seçili · 1 veritabanı')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Süzgece uyan 1.200 nesnenin tümünü seç'}));
    expect(await screen.findByText(/Süzgece uyan nesneler seçiliyor… 500 \/ 1\.200/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Seçilen 1 nesneyi incele'})).toBeDisabled();
    fireEvent.click(screen.getByRole('button', {name: 'Vazgeç'}));

    // Stopping keeps the earlier selection and adds nothing.
    expect(screen.getByText('1 seçili · 1 veritabanı')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Süzgece uyan 1.200 nesnenin tümünü seç'})).toBeEnabled();
    expect(release).not.toBeNull();
  });

  it('names the technical request bound instead of a product limit', async () => {
    const total = 10_001;
    const all = objects('big', total);
    vi.mocked(CatalogService.objects).mockImplementation(async (_database, query) => ({
      items: all.slice((query.page - 1) * query.pageSize, query.page * query.pageSize),
      page: query.page,
      page_size: query.pageSize,
      total,
    }));
    renderWithSession(<ObjectReviewPage />);
    await chooseDatabase('DWH');
    fireEvent.click(await screen.findByRole('button', {name: 'Süzgece uyan 10.001 nesnenin tümünü seç'}));
    expect(await screen.findByText('10.001 seçili · 1 veritabanı')).toBeInTheDocument();
    expect(screen.getByText(/teknik olarak en çok 10\.000 nesne/)).toBeInTheDocument();
    expect(screen.getByText(/Bu bir ürün sınırı değil/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Seçilen 10001 nesneyi incele'})).toBeDisabled();
  });

  it('toggles a row by clicking it and by its checkbox, and clears the selection', async () => {
    renderWithSession(<ObjectReviewPage />);
    await chooseDatabase('DWH');
    const row = (await screen.findByText('dwh_03')).closest('tr');
    fireEvent.click(row!);
    expect(within(row!).getByRole('checkbox')).toBeChecked();
    fireEvent.click(within(row!).getByRole('checkbox'));
    expect(within(row!).getByRole('checkbox')).not.toBeChecked();
    fireEvent.click(row!);
    fireEvent.click(screen.getByRole('button', {name: 'Seçimi temizle'}));
    expect(screen.getByText('0 seçili · 0 veritabanı')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'İnceleme için en az bir nesne seçin'})).toBeDisabled();
  });
});

describe('object review page — rule groups (rule-group-selection Requirement 4, 8)', () => {
  beforeEach(() => {
    vi.spyOn(CatalogService, 'databases').mockResolvedValue({items: ['DWH'], page: 1, page_size: 500, total: 1});
    vi.spyOn(CatalogService, 'objects').mockResolvedValue(page(objects('dwh', 2)));
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(GROUPED_VERSION);
  });

  it('starts the review with the rules of a selected group', async () => {
    const stream = vi.spyOn(ReviewService, 'streamObjectReview').mockResolvedValue(undefined);
    renderWithSession(<ObjectReviewPage />);
    fireEvent.click(await screen.findByLabelText('Güvenlik (1 kural)'));
    await chooseDatabase('DWH');
    await screen.findByText('dwh_01');
    fireEvent.click(screen.getByLabelText('Görünen nesnelerin tümünü seç'));
    fireEvent.click(screen.getByRole('button', {name: 'Seçilen 2 nesneyi incele'}));
    await waitFor(() => expect(stream).toHaveBeenCalled());
    expect(stream.mock.calls[0][3]).toEqual(['Kural01']);
  });
});
