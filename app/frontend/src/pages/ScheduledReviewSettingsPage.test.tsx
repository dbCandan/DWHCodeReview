import {fireEvent, screen, waitFor} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import ScheduledReviewSettingsPage from './ScheduledReviewSettingsPage';
import {ScheduledReviewService} from '@/services/scheduledReviews';
import {apiError, renderWithSession} from '@/test/render';

const LABEL = 'Aynı anda çalışacak zamanlanmış koşum';

describe('scheduled review setting (scheduled-review-email Requirement 7, Decision 8)', () => {
  it('shows the stored limit and saves a value from 1 to 10', async () => {
    vi.spyOn(ScheduledReviewService, 'settings').mockResolvedValue({max_concurrent_runs: 2});
    const save = vi.spyOn(ScheduledReviewService, 'saveSettings').mockResolvedValue({max_concurrent_runs: 4});
    renderWithSession(<ScheduledReviewSettingsPage />, {role: 'super_admin'});
    const input = await screen.findByLabelText(LABEL);
    expect(input).toHaveValue(2);

    fireEvent.change(input, {target: {value: '11'}});
    expect(screen.getByText('Değer 1-10 arasında olmalıdır.')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Kaydet'})).toBeDisabled();

    fireEvent.change(input, {target: {value: '4'}});
    fireEvent.click(screen.getByRole('button', {name: 'Kaydet'}));
    await waitFor(() => expect(save).toHaveBeenCalledWith({max_concurrent_runs: 4}));
    expect(await screen.findByText('Ayar kaydedildi.')).toBeInTheDocument();
  });

  it('shows the refusal of an out-of-range value from the server', async () => {
    vi.spyOn(ScheduledReviewService, 'settings').mockResolvedValue({max_concurrent_runs: 2});
    vi.spyOn(ScheduledReviewService, 'saveSettings').mockRejectedValue(apiError(422, 'setting_out_of_range'));
    renderWithSession(<ScheduledReviewSettingsPage />, {role: 'super_admin'});
    fireEvent.change(await screen.findByLabelText(LABEL), {target: {value: '3'}});
    fireEvent.click(screen.getByRole('button', {name: 'Kaydet'}));
    expect(
      await screen.findByText('Aynı anda çalışacak zamanlanmış koşum sayısı 1-10 arasında olmalıdır.'),
    ).toBeInTheDocument();
  });
});
