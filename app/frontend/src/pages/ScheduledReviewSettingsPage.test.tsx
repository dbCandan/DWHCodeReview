import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import ScheduledReviewSettingsPage from './ScheduledReviewSettingsPage';
import {ScheduledReviewService} from '@/services/scheduledReviews';
import {apiError, renderWithSession} from '@/test/render';

const LABEL = 'Aynı anda çalışacak zamanlanmış koşum';

const READY = {
  scheduler_enabled: true,
  smtp_configured: true,
  smtp_security: 'starttls' as const,
  allowed_domains: ['kurum.example'],
  suggested_recipient: 'ayse@kurum.example',
};

beforeEach(() => {
  vi.spyOn(ScheduledReviewService, 'emailStatus').mockResolvedValue(READY);
});

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
  });});

describe('summary e-mail readiness (scheduled-review-email Requirement 10)', () => {
  it('names what is missing when no SMTP relay is configured', async () => {
    vi.spyOn(ScheduledReviewService, 'settings').mockResolvedValue({max_concurrent_runs: 2});
    vi.spyOn(ScheduledReviewService, 'emailStatus').mockResolvedValue({
      ...READY,
      smtp_configured: false,
      suggested_recipient: null,
    });
    renderWithSession(<ScheduledReviewSettingsPage />, {role: 'super_admin'});
    const checks = await screen.findByRole('list', {name: 'E-posta hazırlığı'});
    expect(within(checks).getByText(/Yapılandırılmadı: SMTP sunucu adresi/)).toBeInTheDocument();
    expect(screen.getByText(/Bu ortamda özet e-posta gönderilemez/)).toBeInTheDocument();
    expect(screen.getByLabelText('Deneme e-postası alıcısı')).toHaveValue('');
  });

  it('sends a test to the suggested address and explains a relay failure', async () => {
    vi.spyOn(ScheduledReviewService, 'settings').mockResolvedValue({max_concurrent_runs: 2});
    const send = vi
      .spyOn(ScheduledReviewService, 'sendTestEmail')
      .mockResolvedValueOnce({status: 'sent', error_code: null})
      .mockResolvedValueOnce({status: 'failed', error_code: 'smtp_tls_failed'});
    renderWithSession(<ScheduledReviewSettingsPage />, {role: 'super_admin'});
    expect(await screen.findByLabelText('Deneme e-postası alıcısı')).toHaveValue('ayse@kurum.example');
    fireEvent.click(screen.getByRole('button', {name: 'Deneme gönder'}));
    await waitFor(() => expect(send).toHaveBeenCalledWith('ayse@kurum.example'));
    expect(await screen.findByText('Deneme e-postası SMTP sunucusuna teslim edildi.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Deneme gönder'}));
    expect(await screen.findByText(/TLS kurulamadı/)).toBeInTheDocument();
  });
});
