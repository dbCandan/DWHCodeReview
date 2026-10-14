import {useId, useState} from 'react';
import {RuleSetDiff} from '@/components/rules/RuleSetDiff';
import {Alert} from '@/components/ui/Alert';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {PageHeader} from '@/components/ui/PageHeader';
import {EmptyState, ErrorState, LoadingState} from '@/components/ui/States';
import {useResource} from '@/hooks/useResource';
import {notifyRuleApprovalsChanged} from '@/hooks/useRuleProposalMenu';
import {describeError} from '@/lib/errorMessages';
import {formatDateTime} from '@/lib/format';
import {displaySummary} from '@/lib/rules';
import {RuleProposalService} from '@/services/ruleProposals';
import {RuleSetService} from '@/services/ruleSet';
import {UserAdminService} from '@/services/userAdmin';
import type {
  PublishRequestItem,
  RuleProposalItem,
  RuleSetVersionDetail,
  UserSummary,
} from '@/types/sqlReview';

type Tab = 'rule' | 'group' | 'publish' | 'proposers';
const REASON_LIMIT = 500;

/**
 * "Kural onayları" (sql-review rule-proposals Requirement 1, 5-7): the super admin reads every
 * pending rule proposal, group proposal and publish request in detail, approves it — which
 * publishes a new version at once — or rejects it with a reason the requester sees, and manages
 * who may propose. The backend checks the super admin on every request.
 */
export default function RuleApprovalsPage() {
  const [tab, setTab] = useState<Tab>('rule');
  const [generation, setGeneration] = useState(0);
  const proposals = useResource(`rule-proposals:pending:${generation}`, (signal) =>
    RuleProposalService.list('pending', 1, 100, signal),
  );
  const requests = useResource(`publish-requests:pending:${generation}`, (signal) =>
    RuleProposalService.publishRequests('bekliyor', 1, 100, signal),
  );
  const latest = useResource(`rule-set-version:latest:${generation}`, (signal) => RuleSetService.latest(signal));
  const ruleItems = proposals.data?.items.filter((item) => item.kind === 'rule') ?? [];
  const groupItems = proposals.data?.items.filter((item) => item.kind === 'group') ?? [];
  const tabs: {id: Tab; label: string}[] = [
    {id: 'rule', label: `Kural önerileri (${ruleItems.length})`},
    {id: 'group', label: `Grup önerileri (${groupItems.length})`},
    {id: 'publish', label: `Yayın istekleri (${requests.data?.items.length ?? 0})`},
    {id: 'proposers', label: 'Öneri yetkisi'},
  ];
  const refresh = () => {
    setGeneration((value) => value + 1);
    notifyRuleApprovalsChanged();
  };

  return (
    <div className="page">
      <PageHeader
        title="Kural onayları"
        description="Onayladığınız öneri veya yayın isteği hemen yeni sürüm olarak yayımlanır; ret gerekçesi isteyene görünür."
      />
      <div className="row" role="tablist" aria-label="Kural onayları">
        {tabs.map((item) => (
          <Button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            variant={tab === item.id ? 'primary' : 'secondary'}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </Button>
        ))}
      </div>
      {(tab === 'rule' || tab === 'group') && proposals.status === 'error' && (
        <ErrorState message={describeError(proposals.error)} onRetry={proposals.reload} />
      )}
      {(tab === 'rule' || tab === 'group') && proposals.data === undefined && proposals.status !== 'error' && (
        <LoadingState />
      )}
      {tab === 'rule' && proposals.data && (
        <ProposalQueue items={ruleItems} version={latest.data} empty="Bekleyen kural önerisi yok" onDecided={refresh} />
      )}
      {tab === 'group' && proposals.data && (
        <ProposalQueue items={groupItems} version={latest.data} empty="Bekleyen grup önerisi yok" onDecided={refresh} />
      )}
      {tab === 'publish' && requests.status === 'error' && (
        <ErrorState message={describeError(requests.error)} onRetry={requests.reload} />
      )}
      {tab === 'publish' && requests.data && <RequestQueue items={requests.data.items} onDecided={refresh} />}
      {tab === 'proposers' && <ProposerAdmin />}
    </div>
  );
}

function ProposalQueue({
  items,
  version,
  empty,
  onDecided,
}: {
  items: RuleProposalItem[];
  version: RuleSetVersionDetail | undefined;
  empty: string;
  onDecided: () => void;
}) {
  if (items.length === 0) return <EmptyState title={empty} />;
  return (
    <ul className="list stack">
      {items.map((item) => (
        <ProposalCard key={item.id} item={item} version={version} onDecided={onDecided} />
      ))}
    </ul>
  );
}

function ProposalCard({
  item,
  version,
  onDecided,
}: {
  item: RuleProposalItem;
  version: RuleSetVersionDetail | undefined;
  onDecided: () => void;
}) {
  const detail = useResource(`rule-proposal:${item.id}`, (signal) => RuleProposalService.get(item.id, signal));
  const rules = [...(version?.critical ?? []), ...(version?.normal ?? [])];
  const groupNames = new Map((version?.groups ?? []).map((group) => [group.id, group.name]));
  const title = item.kind === 'rule' ? item.summary : item.group_name;
  return (
    <li className="card card-body stack-tight" aria-label={title}>
      <div className="row">
        <Badge tone="neutral">{item.kind === 'rule' ? 'Kural' : 'Grup'}</Badge>
        <strong className="grow">{title}</strong>
        <span className="subtle">
          {item.proposer_name} · {formatDateTime(item.created_at)}
        </span>
      </div>
      {detail.status === 'error' && <Alert tone="error">{describeError(detail.error)}</Alert>}
      {detail.data && item.kind === 'rule' && (
        <div className="stack-tight">
          <div className="row">
            <Badge tone={detail.data.priority === 'critical' ? 'danger' : 'info'}>
              {detail.data.priority === 'critical' ? 'Kritik' : 'Normal'}
            </Badge>
            {detail.data.requires_metadata && <Badge tone="primary">Nesne meta verisi gerekir</Badge>}
            {detail.data.rule_group_ids.map((id) => (
              <Badge key={id} tone="neutral">
                {groupNames.get(id) ?? 'Artık olmayan grup'}
              </Badge>
            ))}
          </div>
          <p className="subtle">Ayrıntılı kural metni:</p>
          <p className="rule-text">{detail.data.text}</p>
        </div>
      )}
      {detail.data && item.kind === 'group' && (
        <div className="stack-tight">
          {detail.data.group_description && <p>{detail.data.group_description}</p>}
          <ul className="list stack-tight">
            {detail.data.rule_codes.map((code) => {
              const rule = rules.find((candidate) => candidate.id === code);
              return (
                <li key={code}>
                  <span className="mono">{code}</span>{' '}
                  <span className="subtle">{rule ? displaySummary(rule) : 'yayımlanmış sürümde artık yok'}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {detail.data?.rationale && <p className="subtle">Gerekçe: {detail.data.rationale}</p>}
      <Decision
        label={title}
        onApprove={() => RuleProposalService.approve(item.id)}
        onReject={(reason) => RuleProposalService.reject(item.id, reason)}
        onDecided={onDecided}
      />
    </li>
  );
}

function RequestQueue({items, onDecided}: {items: PublishRequestItem[]; onDecided: () => void}) {
  if (items.length === 0) return <EmptyState title="Bekleyen yayın isteği yok" />;
  return (
    <ul className="list stack">
      {items.map((item) => (
        <RequestCard key={item.id} item={item} onDecided={onDecided} />
      ))}
    </ul>
  );
}

function RequestCard({item, onDecided}: {item: PublishRequestItem; onDecided: () => void}) {
  const detail = useResource(`publish-request:${item.id}`, (signal) =>
    RuleProposalService.publishRequest(item.id, signal),
  );
  const title = `${item.requester_name} · ${formatDateTime(item.created_at)}`;
  return (
    <li className="card card-body stack" aria-label={`Yayın isteği: ${title}`}>
      <div className="row">
        <strong className="grow">Yayın isteği · {title}</strong>
        <span className="subtle">taslak değişiklik no {item.draft_revision}</span>
      </div>
      {item.draft_changed && (
        <Alert tone="warning">Taslak bu istekten sonra değişti; onaylanamaz. Kural yöneticisi yeniden göndermelidir.</Alert>
      )}
      {detail.status === 'error' && <Alert tone="error">{describeError(detail.error)}</Alert>}
      {detail.data?.diff && <RuleSetDiff diff={detail.data.diff} />}
      <Decision
        label="Yayın isteği"
        onApprove={() => RuleProposalService.approveRequest(item.id)}
        onReject={(reason) => RuleProposalService.rejectRequest(item.id, reason)}
        onDecided={onDecided}
      />
    </li>
  );
}

/** Approve, or reject with a 1–500 character reason the requester sees. */
function Decision({
  label,
  onApprove,
  onReject,
  onDecided,
}: {
  label: string;
  onApprove: () => Promise<unknown>;
  onReject: (reason: string) => Promise<unknown>;
  onDecided: () => void;
}) {
  const reasonId = useId();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onDecided();
    } catch (failure) {
      setError(describeError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack-tight">
      {error && <Alert tone="error">{error}</Alert>}
      {rejecting && (
        <div className="field">
          <label className="field-label" htmlFor={reasonId}>
            Ret gerekçesi ({label})
          </label>
          <textarea
            id={reasonId}
            className="textarea"
            rows={2}
            maxLength={REASON_LIMIT}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
      )}
      <div className="row">
        {!rejecting && (
          <Button variant="primary" busy={busy} disabled={busy} onClick={() => void run(onApprove)} aria-label={`${label} onayla`}>
            Onayla ve yayımla
          </Button>
        )}
        {rejecting ? (
          <>
            <Button
              variant="danger-outline"
              busy={busy}
              disabled={busy || reason.trim() === ''}
              onClick={() => void run(() => onReject(reason))}
            >
              Reddi gönder
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => setRejecting(false)}>
              Vazgeç
            </Button>
          </>
        ) : (
          <Button variant="danger-outline" disabled={busy} onClick={() => setRejecting(true)} aria-label={`${label} reddet`}>
            Reddet
          </Button>
        )}
      </div>
    </div>
  );
}

function ProposerAdmin() {
  const searchId = useId();
  const [generation, setGeneration] = useState(0);
  const proposers = useResource(`rule-proposers:${generation}`, (signal) => RuleProposalService.proposers(signal));
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<UserSummary[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const holders = new Set(proposers.data?.items.map((item) => item.user_id) ?? []);

  async function search() {
    setError(null);
    try {
      const page = await UserAdminService.list({page: 1, size: 20, q: query.trim() || undefined});
      setFound(page.items.filter((user) => user.is_active && !user.is_super_admin));
    } catch (failure) {
      setError(describeError(failure));
    }
  }

  async function change(userId: string, grant: boolean) {
    setBusy(userId);
    setError(null);
    try {
      await (grant ? RuleProposalService.grant(userId) : RuleProposalService.revoke(userId));
      setGeneration((value) => value + 1);
    } catch (failure) {
      setError(describeError(failure));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card card-body stack" aria-label="Öneri yetkisi">
      <p className="subtle">Yetki verilen kullanıcılar yeni kural ve grup önerebilir; öneriler bu sayfaya düşer.</p>
      {error && <Alert tone="error">{error}</Alert>}
      {proposers.status === 'error' && <ErrorState message={describeError(proposers.error)} onRetry={proposers.reload} />}
      {proposers.data && proposers.data.items.length === 0 && <p className="muted">Henüz yetki verilmiş kullanıcı yok.</p>}
      {proposers.data && proposers.data.items.length > 0 && (
        <ul className="list stack-tight" aria-label="Yetkili kullanıcılar">
          {proposers.data.items.map((item) => (
            <li key={item.user_id} className="row">
              <span className="grow">
                {item.display_name} <span className="subtle">({item.username})</span>
              </span>
              <Button
                size="sm"
                variant="danger-outline"
                busy={busy === item.user_id}
                onClick={() => void change(item.user_id, false)}
                aria-label={`${item.display_name} yetkisini kaldır`}
              >
                Yetkiyi kaldır
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="row">
        <div className="field grow">
          <label className="field-label" htmlFor={searchId}>
            Kullanıcı ara
          </label>
          <input
            id={searchId}
            className="input"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void search();
            }}
          />
        </div>
        <Button onClick={() => void search()}>Ara</Button>
      </div>
      {found !== null && found.length === 0 && <p className="muted">Eşleşen etkin kullanıcı yok.</p>}
      {found !== null && found.length > 0 && (
        <ul className="list stack-tight" aria-label="Arama sonuçları">
          {found.map((user) => (
            <li key={user.public_id} className="row">
              <span className="grow">
                {user.display_name} <span className="subtle">({user.username})</span>
              </span>
              {holders.has(user.public_id) ? (
                <Badge tone="success">Yetkili</Badge>
              ) : (
                <Button
                  size="sm"
                  busy={busy === user.public_id}
                  onClick={() => void change(user.public_id, true)}
                  aria-label={`${user.display_name} kullanıcısına yetki ver`}
                >
                  Yetki ver
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
