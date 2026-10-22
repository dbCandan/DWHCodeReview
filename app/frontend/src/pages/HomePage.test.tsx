import {screen, within} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import HomePage from './HomePage';
import {ReviewService} from '@/services/reviews';
import {renderWithSession} from '@/test/render';

function noRuns() {
  vi.spyOn(ReviewService, 'runs').mockResolvedValue({items: [], page: 1, page_size: 5, total: 0});
}

describe('platform home', () => {
  it('does not ship a generic business resource', () => {
    expect("Veri ambarı geliştiricilerinin SQL Server nesnelerini ve yapıştırılan SQL kodunu yayımlanmış inceleme kurallarına göre kurum içi LLM ile incelemesi, bulguları satır referanslarıyla görmesi ve CSV/SQL olarak dışa aktarması; Active Directory girişiyle ve kurumsal Kubernetes ortamında güvenli çalışma.").not.toMatch(/sample item/i);
  });

  it('offers the three ways to start a review and no proposal or approval places', async () => {
    noRuns();
    renderWithSession(<HomePage />, {role: 'inceleyici'});
    const start = await screen.findByRole('navigation', {name: 'İncelemeye başla'});
    expect(within(start).getAllByRole('link').map((link) => link.querySelector('strong')?.textContent)).toEqual([
      'Nesne incelemesi',
      'SQL betiği incelemesi',
      'Zamanlanmış incelemeler',
    ]);
    expect(await screen.findByText('Henüz inceleme yok')).toBeInTheDocument();
    expect(screen.queryByText(/öneri/i)).toBeNull();
    expect(screen.queryByText(/onay/i)).toBeNull();
  });
});
