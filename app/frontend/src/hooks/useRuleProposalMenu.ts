import {useEffect, useState} from 'react';
import {useResource} from '@/hooks/useResource';
import {RuleProposalService} from '@/services/ruleProposals';

const CHANGED = 'rule-approvals-changed';

/** Tell the menu that a proposal or publish request was decided, so its count is read again. */
export function notifyRuleApprovalsChanged(): void {
  window.dispatchEvent(new Event(CHANGED));
}

/**
 * Whether "Kural önerilerim" and "Kural onayları" belong in the menu, and how many decisions wait
 * (sql-review rule-proposals Requirement 7). The count is the pending proposals plus the pending
 * publish requests; it is read again when `refreshKey` changes, such as on navigation, and after
 * every decision.
 */
export function useRuleProposalMenu(
  enabled: boolean,
  refreshKey: string,
): {canPropose: boolean; canDecide: boolean; pending: number} {
  const [decisions, setDecisions] = useState(0);
  useEffect(() => {
    const bump = () => setDecisions((value) => value + 1);
    window.addEventListener(CHANGED, bump);
    return () => window.removeEventListener(CHANGED, bump);
  }, []);
  const capabilities = useResource(enabled ? 'rule-proposals:capabilities' : null, (signal) =>
    RuleProposalService.capabilities(signal),
  );
  const canDecide = capabilities.data?.can_decide === true;
  const key = `${refreshKey}:${decisions}`;
  const proposals = useResource(canDecide ? `rule-proposals:pending-count:${key}` : null, (signal) =>
    RuleProposalService.list('pending', 1, 1, signal),
  );
  const requests = useResource(canDecide ? `publish-requests:pending-count:${key}` : null, (signal) =>
    RuleProposalService.publishRequests('bekliyor', 1, 1, signal),
  );
  return {
    canPropose: capabilities.data?.can_propose === true,
    canDecide,
    pending: (proposals.data?.total ?? 0) + (requests.data?.total ?? 0),
  };
}
