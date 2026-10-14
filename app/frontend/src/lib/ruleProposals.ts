import type {PublishRequestStatus, RuleProposalStatus} from '@/types/sqlReview';

type Tone = 'neutral' | 'success' | 'danger' | 'warning' | 'info';

/** Turkish labels of the proposal states (sql-review rule-proposals Requirement 4). */
export const PROPOSAL_STATUS: Record<RuleProposalStatus, string> = {
  bekliyor: 'Bekliyor',
  onaylandi: 'Onaylandı',
  reddedildi: 'Reddedildi',
  geri_cekildi: 'Geri çekildi',
};

/** Turkish labels of the publish request states (rule-proposals Requirement 6). */
export const REQUEST_STATUS: Record<PublishRequestStatus, string> = {
  bekliyor: 'onay bekliyor',
  onaylandi: 'onaylandı',
  reddedildi: 'reddedildi',
  gecersiz: 'geçersiz (taslak sonradan değişti veya yeni istek gönderildi)',
};

export function proposalStatusTone(status: RuleProposalStatus | PublishRequestStatus): Tone {
  if (status === 'onaylandi') return 'success';
  if (status === 'reddedildi') return 'danger';
  if (status === 'bekliyor') return 'warning';
  return 'neutral';
}
