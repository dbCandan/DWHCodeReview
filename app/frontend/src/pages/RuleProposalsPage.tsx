import {useId, useState, type FormEvent} from 'react';
import {Alert} from '@/components/ui/Alert';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {Field} from '@/components/ui/Field';
import {PageHeader} from '@/components/ui/PageHeader';
import {EmptyState, ErrorState, LoadingState} from '@/components/ui/States';
import {useResource} from '@/hooks/useResource';
import {describeError} from '@/lib/errorMessages';
import {formatDateTime} from '@/lib/format';
import {PROPOSAL_STATUS, proposalStatusTone} from '@/lib/ruleProposals';
import {RULE_SUMMARY_LIMIT, RULE_TEXT_LIMIT, displaySummary, ruleMatchesSearch, summaryProblem} from '@/lib/rules';
import {RuleProposalService} from '@/services/ruleProposals';
import {RuleSetService} from '@/services/ruleSet';
import type {RuleProposalItem, RuleSetVersionDetail} from '@/types/sqlReview';

type Tab = 'rule' | 'group' | 'history';

const TABS: {id: Tab; label: string}[] = [
  {id: 'rule', label: 'Kural öner'},
  {id: 'group', label: 'Grup öner'},
  {id: 'history', label: 'Önerilerim'},
];
const GROUP_NAME_LIMIT = 80;
const REASON_LIMIT = 500;
const PRIVACY_HINT = 'Kişisel veri, müşteri bilgisi veya parola yazmayın.';

/**
 * "Kural önerilerim" (sql-review rule-proposals Requirement 2-4, 7): a user the super admin gave
 * the permission proposes a new rule — with a one-sentence summary and the detailed text — or a
 * new group of published rules, and follows the decisions. Nothing is published until the super
 * admin approves; the backend checks the permission on every request.
 */
export default function RuleProposalsPage() {
  const capabilities = useResource('rule-proposals:capabilities', (signal) => RuleProposalService.capabilities(signal));
  const latest = useResource('rule-set-version:latest', (signal) => RuleSetService.latest(signal));
  const [tab, setTab] = useState<Tab>('rule');
  const [sent, setSent] = useState(0);

  if (capabilities.status === 'error')
    return (
      <div className="page">
        <PageHeader title="Kural önerilerim" />
        <ErrorState message={describeError(capabilities.error)} onRetry={capabilities.reload} />
      </div>
    );
  if (capabilities.data === undefined)
    return (
      <div className="page">
        <PageHeader title="Kural önerilerim" />
        <LoadingState />
      </div>
    );
  if (!capabilities.data.can_propose)
    return (
      <div className="page">
        <PageHeader title="Kural önerilerim" />
        <EmptyState title="Kural önerme yetkiniz yok">Yetki için süper yöneticiye başvurun.</EmptyState>
      </div>
    );

  function proposed() {
    setSent((value) => value + 1);
    setTab('history');
  }

  return (
    <div className="page">
      <PageHeader
        title="Kural önerilerim"
        description="Önerdiğiniz kural veya grup, süper yönetici onaylayınca yeni sürümle herkesin kullanımına açılır."
      />
      <div className="row" role="tablist" aria-label="Kural önerileri">
        {TABS.map((item) => (
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
      {tab === 'rule' && <RuleProposalForm version={latest.data} onSent={proposed} />}
      {tab === 'group' && <GroupProposalForm version={latest.data} onSent={proposed} />}
      {tab === 'history' && <ProposalHistory key={sent} />}
    </div>
  );
}

function RuleProposalForm({version, onSent}: {version: RuleSetVersionDetail | undefined; onSent: () => void}) {
  const id = useId();
  const [summary, setSummary] = useState('');
  const [text, setText] = useState('');
  const [priority, setPriority] = useState<'critical' | 'normal'>('normal');
  const [metadata, setMetadata] = useState(false);
  const [groups, setGroups] = useState<string[]>([]);
  const [rationale, setRationale] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const summaryError = summary.trim() ? summaryProblem(summary) : null;
  const tooLong = text.trim().length > RULE_TEXT_LIMIT;
  const ready = summary.trim() !== '' && summaryError === null && text.trim() !== '' && !tooLong;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await RuleProposalService.create({
        kind: 'rule',
        summary,
        text,
        priority,
        requires_metadata: metadata,
        rule_group_ids: groups,
        group_name: '',
        group_description: '',
        rule_codes: [],
        rationale,
      });
      onSent();
    } catch (failure) {
      setError(describeError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card card-body stack" aria-label="Yeni kural önerisi" onSubmit={(event) => void submit(event)}>
      <Field
        id={`${id}-summary`}
        label="Özet (tek cümle, zorunlu)"
        hint={`Süper yönetici dışındaki kullanıcılar kuralı bu cümleyle görür; en çok ${RULE_SUMMARY_LIMIT} karakter.`}
        error={summaryError}
      >
        <input
          id={`${id}-summary`}
          className="input"
          value={summary}
          required
          aria-invalid={summaryError !== null || undefined}
          onChange={(event) => setSummary(event.target.value)}
        />
      </Field>
      <Field
        id={`${id}-text`}
        label="Ayrıntılı kural metni (zorunlu)"
        hint={`İncelemede modele giden metin budur. ${text.length.toLocaleString('tr-TR')} / ${RULE_TEXT_LIMIT.toLocaleString('tr-TR')} karakter. ${PRIVACY_HINT}`}
        error={tooLong ? 'Kural metni en çok 8.000 karakter olabilir.' : null}
      >
        <textarea
          id={`${id}-text`}
          className="textarea"
          rows={8}
          value={text}
          required
          onChange={(event) => setText(event.target.value)}
        />
      </Field>
      <div className="row">
        <Field id={`${id}-priority`} label="Öncelik">
          <select
            id={`${id}-priority`}
            className="select"
            value={priority}
            onChange={(event) => setPriority(event.target.value as 'critical' | 'normal')}
          >
            <option value="normal">Normal</option>
            <option value="critical">Kritik</option>
          </select>
        </Field>
        <label className="check">
          <input type="checkbox" checked={metadata} onChange={(event) => setMetadata(event.target.checked)} />
          <span>Nesne meta verisi gerekir</span>
        </label>
      </div>
      {(version?.groups.length ?? 0) > 0 && (
        <fieldset className="field" role="group" aria-labelledby={`${id}-groups`}>
          <legend id={`${id}-groups`} className="field-label">
            Katılacağı kural grupları (isteğe bağlı)
          </legend>
          <div className="row">
            {version?.groups.map((group) => (
              <label key={group.id} className="check">
                <input
                  type="checkbox"
                  checked={groups.includes(group.id)}
                  onChange={(event) =>
                    setGroups((current) =>
                      event.target.checked ? [...current, group.id] : current.filter((value) => value !== group.id),
                    )
                  }
                />
                <span>{group.name}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <RationaleField id={`${id}-rationale`} value={rationale} onChange={setRationale} />
      {error && <Alert tone="error">{error}</Alert>}
      <div className="row">
        <Button type="submit" variant="primary" disabled={!ready || busy} busy={busy}>
          {busy ? 'Gönderiliyor…' : 'Öneriyi gönder'}
        </Button>
      </div>
    </form>
  );
}

function GroupProposalForm({version, onSent}: {version: RuleSetVersionDetail | undefined; onSent: () => void}) {
  const id = useId();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [codes, setCodes] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [rationale, setRationale] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rules = [...(version?.critical ?? []), ...(version?.normal ?? [])];
  const nameError = name.trim().length > GROUP_NAME_LIMIT ? `Grup adı en çok ${GROUP_NAME_LIMIT} karakter olabilir.` : null;
  const ready = name.trim() !== '' && nameError === null && codes.length > 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      // Version order keeps the proposal stable whatever order the rules were ticked in.
      const ordered = rules.filter((rule) => codes.includes(rule.id)).map((rule) => rule.id);
      await RuleProposalService.create({
        kind: 'group',
        summary: '',
        text: '',
        priority: 'normal',
        requires_metadata: false,
        rule_group_ids: [],
        group_name: name,
        group_description: description,
        rule_codes: ordered,
        rationale,
      });
      onSent();
    } catch (failure) {
      setError(describeError(failure));
    } finally {
      setBusy(false);
    }
  }

  if (version === undefined) return <EmptyState title="Henüz yayımlanmış kural yok" />;
  return (
    <form className="card card-body stack" aria-label="Yeni grup önerisi" onSubmit={(event) => void submit(event)}>
      <Field id={`${id}-name`} label="Grup adı (zorunlu)" error={nameError}>
        <input id={`${id}-name`} className="input" value={name} required onChange={(event) => setName(event.target.value)} />
      </Field>
      <Field id={`${id}-description`} label="Açıklama (isteğe bağlı)">
        <input
          id={`${id}-description`}
          className="input"
          value={description}
          maxLength={500}
          onChange={(event) => setDescription(event.target.value)}
        />
      </Field>
      <fieldset className="field" role="group" aria-labelledby={`${id}-rules`}>
        <legend id={`${id}-rules`} className="field-label">
          Gruptaki kurallar ({codes.length} seçildi)
        </legend>
        <label className="sr-only" htmlFor={`${id}-search`}>
          Kural ara
        </label>
        <input
          id={`${id}-search`}
          className="input"
          type="search"
          value={search}
          placeholder="Kural kimliği veya özet ara…"
          onChange={(event) => setSearch(event.target.value)}
        />
        <ul className="list stack-tight rule-pick-list">
          {rules
            .filter((rule) => ruleMatchesSearch(rule, search))
            .map((rule) => (
              <li key={rule.id}>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={codes.includes(rule.id)}
                    onChange={(event) =>
                      setCodes((current) =>
                        event.target.checked ? [...current, rule.id] : current.filter((value) => value !== rule.id),
                      )
                    }
                  />
                  <span>
                    <span className="mono">{rule.id}</span> <span className="subtle">{displaySummary(rule)}</span>
                  </span>
                </label>
              </li>
            ))}
        </ul>
      </fieldset>
      <RationaleField id={`${id}-rationale`} value={rationale} onChange={setRationale} />
      {error && <Alert tone="error">{error}</Alert>}
      <div className="row">
        <Button type="submit" variant="primary" disabled={!ready || busy} busy={busy}>
          {busy ? 'Gönderiliyor…' : 'Öneriyi gönder'}
        </Button>
      </div>
    </form>
  );
}

function RationaleField({id, value, onChange}: {id: string; value: string; onChange: (value: string) => void}) {
  return (
    <Field id={id} label="Gerekçe (isteğe bağlı)" hint={`En çok ${REASON_LIMIT} karakter. ${PRIVACY_HINT}`}>
      <textarea
        id={id}
        className="textarea"
        rows={2}
        value={value}
        maxLength={REASON_LIMIT}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  );
}

function ProposalHistory() {
  const history = useResource('rule-proposals:mine', (signal) => RuleProposalService.list('mine', 1, 100, signal));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function withdraw(item: RuleProposalItem) {
    setBusy(item.id);
    setError(null);
    try {
      await RuleProposalService.withdraw(item.id);
      history.reload();
    } catch (failure) {
      setError(describeError(failure));
    } finally {
      setBusy(null);
    }
  }

  if (history.status === 'error') return <ErrorState message={describeError(history.error)} onRetry={history.reload} />;
  if (history.data === undefined) return <LoadingState />;
  if (history.data.items.length === 0) return <EmptyState title="Henüz öneriniz yok" />;
  return (
    <section className="card" aria-label="Önerilerim">
      {error && <Alert tone="error">{error}</Alert>}
      <ul className="list">
        {history.data.items.map((item) => (
          <li key={item.id} className="list-item card-body stack-tight">
            <div className="row">
              <Badge tone="neutral">{item.kind === 'rule' ? 'Kural' : 'Grup'}</Badge>
              <Badge tone={proposalStatusTone(item.status)}>{PROPOSAL_STATUS[item.status]}</Badge>
              <strong className="grow">{item.kind === 'rule' ? item.summary : item.group_name}</strong>
              {item.status === 'bekliyor' && (
                <Button size="sm" variant="danger-outline" busy={busy === item.id} onClick={() => void withdraw(item)}>
                  Geri çek
                </Button>
              )}
            </div>
            <span className="subtle">
              {formatDateTime(item.created_at)}
              {item.decided_by_name && ` · karar: ${item.decided_by_name}`}
              {item.published_version_number !== null && ` · sürüm ${item.published_version_number}`}
              {item.new_rule_id && ` · ${item.new_rule_id}`}
            </span>
            {item.rejection_reason && <p className="rule-text">Ret gerekçesi: {item.rejection_reason}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
