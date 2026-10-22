import {useState} from 'react';
import {RuleEditorColumn, type RuleEditorActions} from '@/components/rules/RuleEditorColumn';
import {RuleGroupManager} from '@/components/rules/RuleGroupManager';
import {Alert} from '@/components/ui/Alert';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {PageHeader} from '@/components/ui/PageHeader';
import {ErrorState, LoadingState} from '@/components/ui/States';
import {useResource} from '@/hooks/useResource';
import {describeError, errorCode} from '@/lib/errorMessages';
import {
  RULE_TEXT_LIMIT,
  draftsEqual,
  formatRuleId,
  groupProblem,
  groupRuleCounts,
  latestVersionLine,
  moveRule,
  newGroupId,
  ruleNumber,
  summaryProblem,
  withGroupMembership,
  withoutGroup,
  type RuleDraft,
  type Tier,
} from '@/lib/rules';
import {RuleSetService} from '@/services/ruleSet';
import type {RuleSetWorkspace} from '@/types/sqlReview';

type Notice = {tone: 'success' | 'error' | 'info'; text: string; conflict?: boolean};

/**
 * The super admin's draft editor (sql-review rule-management Requirement 1–6, 10, 12): two priority
 * groups, search, move within a group, delete, add with the next free identifier, each rule's
 * one-sentence summary, and save with the revision the page last saw. Named rule groups and the
 * rules' memberships are edited here too (rule-group-selection Requirement 1, 8). The super admin
 * publishes directly; users propose changes instead (directory-login Decision 14).
 */
export default function RulesPage() {
  const workspace = useResource('rule-set', (signal) => RuleSetService.workspace(signal));
  const [notice, setNotice] = useState<Notice | null>(null);

  return (
    <div className="page">
      {workspace.status === 'error' && (
        <>
          <PageHeader title="Kurallar" />
          <ErrorState message={describeError(workspace.error)} onRetry={workspace.reload} />
        </>
      )}
      {workspace.status === 'loading' && workspace.data === undefined && (
        <>
          <PageHeader title="Kurallar" />
          <LoadingState label="Kurallar yükleniyor…" />
        </>
      )}
      {workspace.data && (
        <RulesEditor
          key={workspace.data.revision}
          workspace={workspace.data}
          notice={notice}
          onNotice={setNotice}
          onSaved={workspace.replace}
          onReload={() => {
            setNotice(null);
            workspace.reload();
          }}
        />
      )}
    </div>
  );
}

function RulesEditor({
  workspace,
  notice,
  onNotice,
  onSaved,
  onReload,
}: {
  workspace: RuleSetWorkspace;
  notice: Notice | null;
  onNotice: (notice: Notice | null) => void;
  onSaved: (workspace: RuleSetWorkspace) => void;
  onReload: () => void;
}) {
  const saved: RuleDraft = {critical: workspace.critical, normal: workspace.normal, groups: workspace.groups};
  const [draft, setDraft] = useState<RuleDraft>(saved);
  const [nextNumber, setNextNumber] = useState(() => ruleNumber(workspace.next_rule_id) ?? 1);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState<'save' | 'publish' | null>(null);
  const dirty = !draftsEqual(draft, saved);
  const rules = [...draft.critical, ...draft.normal];
  const tooLong = rules.some((rule) => rule.text.length > RULE_TEXT_LIMIT);
  const badSummary = rules.some((rule) => summaryProblem(rule.summary ?? '') !== null);
  const invalidGroups = groupProblem(draft.groups);
  const blocked = tooLong || badSummary || invalidGroups !== null;

  function update(tier: Tier, change: (rules: RuleDraft[Tier]) => RuleDraft[Tier]) {
    setDraft((current) => ({...current, [tier]: change(current[tier])}));
  }

  function actionsFor(tier: Tier): RuleEditorActions {
    return {
      onText: (id, text) => update(tier, (rules) => rules.map((rule) => (rule.id === id ? {...rule, text} : rule))),
      onSummary: (id, summary) =>
        update(tier, (rules) => rules.map((rule) => (rule.id === id ? {...rule, summary} : rule))),
      onRequiresMetadata: (id, value) =>
        update(tier, (rules) => rules.map((rule) => (rule.id === id ? {...rule, requires_metadata: value} : rule))),
      onMove: (index, delta) => update(tier, (rules) => moveRule(rules, index, delta)),
      onRemove: (id) => update(tier, (rules) => rules.filter((rule) => rule.id !== id)),
      onGroup: (id, groupId, member) =>
        update(tier, (rules) => rules.map((rule) => (rule.id === id ? withGroupMembership(rule, groupId, member) : rule))),
      onAdd: () => {
        const id = formatRuleId(nextNumber);
        setNextNumber(nextNumber + 1);
        update(tier, (rules) => [...rules, {id, text: '', summary: '', requires_metadata: false, rule_group_ids: []}]);
      },
    };
  }

  function addGroup() {
    setDraft((current) => ({
      ...current,
      groups: [...current.groups, {id: newGroupId(), name: 'Yeni grup', description: ''}],
    }));
  }

  function renameGroup(id: string, name: string) {
    setDraft((current) => ({
      ...current,
      groups: current.groups.map((group) => (group.id === id ? {...group, name} : group)),
    }));
  }

  function removeGroup(id: string) {
    setDraft((current) => ({
      critical: withoutGroup(current.critical, id),
      normal: withoutGroup(current.normal, id),
      groups: current.groups.filter((group) => group.id !== id),
    }));
  }

  function failure(error: unknown) {
    const conflict = errorCode(error) === 'rule_set_draft_conflict';
    onNotice({tone: 'error', text: describeError(error), conflict});
  }

  async function save() {
    setBusy('save');
    onNotice(null);
    try {
      const next = await RuleSetService.saveDraft(workspace.revision, draft.critical, draft.normal, draft.groups);
      onNotice({tone: 'success', text: 'Taslak kaydedildi.'});
      onSaved(next);
    } catch (error) {
      failure(error);
    } finally {
      setBusy(null);
    }
  }

  async function publish() {
    setBusy('publish');
    onNotice(null);
    let base = workspace;
    try {
      // "Yayınla" saves unsaved changes first, then publishes the saved revision.
      if (dirty)
        base = await RuleSetService.saveDraft(workspace.revision, draft.critical, draft.normal, draft.groups);
      const version = await RuleSetService.publish(base.revision);
      const unchanged = workspace.latest_version?.number === version.number;
      const next = await RuleSetService.workspace();
      onNotice({
        tone: 'success',
        text: unchanged
          ? `Taslak son sürümle aynı; yeni sürüm oluşmadı (sürüm ${version.number}).`
          : `Sürüm ${version.number} yayımlandı. Bundan sonra başlayan incelemeler bu sürümü kullanır.`,
      });
      onSaved(next);
    } catch (error) {
      failure(error);
      // Keep the saved revision when only the publish step failed.
      if (base !== workspace) onSaved(base);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Kurallar"
        description={'Taslakta yaptığınız değişiklik yalnız “Yayınla” ile incelemelere uygulanır.'}
        actions={
          <div className="stack-tight">
            <span className="subtle">{latestVersionLine(workspace.latest_version)}</span>
            {workspace.draft_differs && <Badge tone="warning">Taslakta yayımlanmamış değişiklik var</Badge>}
          </div>
        }
      />
      {notice && (
        <Alert tone={notice.tone}>
          <div className="row">
            <p className="grow">{notice.text}</p>
            {notice.conflict && (
              <Button size="sm" onClick={onReload}>
                Sayfayı yenile
              </Button>
            )}
          </div>
        </Alert>
      )}
      <div className="field">
        <label className="field-label" htmlFor="rule-search">
          Kural ara
        </label>
        <input
          id="rule-search"
          className="input"
          type="search"
          value={search}
          placeholder="Kural01 veya kural metni…"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      <RuleGroupManager
        groups={draft.groups}
        counts={groupRuleCounts(draft.critical, draft.normal)}
        problem={invalidGroups}
        disabled={busy !== null}
        onRename={renameGroup}
        onRemove={removeGroup}
        onAdd={addGroup}
      />
      <div className="split">
        <RuleEditorColumn
          tier="critical"
          rules={draft.critical}
          groups={draft.groups}
          search={search}
          disabled={busy !== null}
          actions={actionsFor('critical')}
        />
        <RuleEditorColumn
          tier="normal"
          rules={draft.normal}
          groups={draft.groups}
          search={search}
          disabled={busy !== null}
          actions={actionsFor('normal')}
        />
      </div>
      <div className="card card-footer sticky-footer">
        <Button variant="secondary" onClick={() => void save()} disabled={busy !== null || !dirty || blocked} busy={busy === 'save'}>
          {busy === 'save' ? 'Kaydediliyor…' : 'Taslağı kaydet'}
        </Button>
        <Button variant="primary" onClick={() => void publish()} disabled={busy !== null || blocked} busy={busy === 'publish'}>
          {busy === 'publish' ? 'Yayınlanıyor…' : 'Yayınla'}
        </Button>
        {dirty && <Badge tone="warning">Kaydedilmedi</Badge>}
        {tooLong && <span className="field-error">Kural metni en çok 8.000 karakter olabilir.</span>}
        {badSummary && <span className="field-error">Bir kuralın özeti geçersiz; özet tek satırda en çok 200 karakter olabilir.</span>}
      </div>
    </>
  );
}
