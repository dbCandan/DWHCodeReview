import {useId, useState} from 'react';
import {Badge} from '@/components/ui/Badge';
import {PageHeader} from '@/components/ui/PageHeader';
import {EmptyState, ErrorState, LoadingState} from '@/components/ui/States';
import {useAuth} from '@/contexts/AuthContext';
import {useResource} from '@/hooks/useResource';
import {describeError, errorCode} from '@/lib/errorMessages';
import {formatDateTime} from '@/lib/format';
import {displaySummary, publisherName, ruleMatchesSearch} from '@/lib/rules';
import {RuleSetService} from '@/services/ruleSet';
import type {RuleGroupItem, RuleItem, RuleSetVersionDetail} from '@/types/sqlReview';

/** "Tüm kurallar", one group, or the rules in no group. */
type Shelf = {kind: 'all'} | {kind: 'group'; id: string} | {kind: 'ungrouped'};

/**
 * Read-only published rules for both roles (sql-review rule-management Requirement 8, 11, 12):
 * the latest version by default, any older version from the list, search by id, summary or text.
 * Groups are a list on the left; the chosen group's rules run top to bottom on the right, critical
 * first. Everyone but the super admin sees each rule as one sentence; the super admin can also open
 * the detailed text the LLM receives. This is a view choice, not an access boundary.
 */
export default function PublishedRulesPage() {
  const [selected, setSelected] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const versions = useResource('rule-set-versions', (signal) => RuleSetService.versions(1, 100, signal));
  const detail = useResource(`rule-set-version:${selected ?? 'latest'}`, (signal) =>
    selected === null ? RuleSetService.latest(signal) : RuleSetService.version(selected, signal),
  );
  const noVersion = detail.status === 'error' && errorCode(detail.error) === 'no_published_rule_set';

  return (
    <div className="page page-fill">
      <PageHeader
        title="Yayımlanmış kurallar"
        description="İncelemeler en son yayımlanmış sürümü kullanır; her kural tek cümlelik özetiyle."
        actions={
          !noVersion && (
            <div className="field field-inline">
              <label className="field-label" htmlFor="version-select">
                Sürüm
              </label>
              <select
                id="version-select"
                className="select"
                value={selected ?? ''}
                disabled={versions.data === undefined}
                onChange={(event) => setSelected(event.target.value === '' ? null : Number(event.target.value))}
              >
                <option value="">En son sürüm</option>
                {versions.data?.items.map((version) => (
                  <option key={version.number} value={version.number}>
                    {`Sürüm ${version.number} · ${formatDateTime(version.published_at)} · ${publisherName(version)} · ${version.critical_count} kritik, ${version.normal_count} normal`}
                  </option>
                ))}
              </select>
            </div>
          )
        }
      />
      {noVersion && <EmptyState title="Henüz yayımlanmış kural yok" icon="book" />}
      {detail.status === 'error' && !noVersion && (
        <ErrorState message={describeError(detail.error)} onRetry={detail.reload} />
      )}
      {versions.status === 'error' && <ErrorState message={describeError(versions.error)} onRetry={versions.reload} />}
      {detail.status === 'loading' && detail.data === undefined && <LoadingState label="Kurallar yükleniyor…" />}
      {detail.data && !noVersion && (
        <Library key={detail.data.number} version={detail.data} search={search} onSearch={setSearch} />
      )}
    </div>
  );
}

function inShelf(rule: RuleItem, shelf: Shelf, known: Set<string>): boolean {
  const groups = (rule.rule_group_ids ?? []).filter((id) => known.has(id));
  if (shelf.kind === 'all') return true;
  if (shelf.kind === 'ungrouped') return groups.length === 0;
  return groups.includes(shelf.id);
}

function Library({
  version,
  search,
  onSearch,
}: {
  version: RuleSetVersionDetail;
  search: string;
  onSearch: (value: string) => void;
}) {
  const {user} = useAuth();
  const detailed = Boolean(user?.is_super_admin);
  const [shelf, setShelf] = useState<Shelf>({kind: 'all'});
  const searchId = useId();
  const critical = new Set(version.critical.map((rule) => rule.id));
  const rules = [...version.critical, ...version.normal];
  const known = new Set(version.groups.map((group) => group.id));
  const names = new Map(version.groups.map((group) => [group.id, group.name]));
  const count = (target: Shelf) => rules.filter((rule) => inShelf(rule, target, known)).length;
  const ungrouped = count({kind: 'ungrouped'});
  const visible = rules.filter((rule) => inShelf(rule, shelf, known) && ruleMatchesSearch(rule, search));
  const group: RuleGroupItem | undefined =
    shelf.kind === 'group' ? version.groups.find((item) => item.id === shelf.id) : undefined;
  const title = shelf.kind === 'all' ? 'Tüm kurallar' : shelf.kind === 'ungrouped' ? 'Grupsuz kurallar' : group?.name;
  const same = (target: Shelf) =>
    target.kind === shelf.kind && (target.kind !== 'group' || (shelf.kind === 'group' && shelf.id === target.id));

  const grouped = version.groups.length > 0;
  const searchBox = (
    <>
      <label className="sr-only" htmlFor={searchId}>
        Kural ara
      </label>
      <input
        id={searchId}
        className="input"
        type="search"
        value={search}
        placeholder="Kural01 veya kural metni…"
        onChange={(event) => onSearch(event.target.value)}
      />
    </>
  );
  const versionLine = (
    <>
      Sürüm {version.number} · {formatDateTime(version.published_at)} · yayımlayan: {publisherName(version)}
    </>
  );

  return (
    <div className={grouped ? 'workspace workspace-library' : 'workspace workspace-single'}>
      {grouped && (
      <nav className="pane" aria-label="Kural grupları">
        <div className="pane-head">{searchBox}</div>
        <ul className="pane-body list shelf-list">
          <ShelfButton pressed={same({kind: 'all'})} onSelect={() => setShelf({kind: 'all'})} label="Tüm kurallar" total={rules.length} />
          {version.groups.map((item) => (
            <ShelfButton
              key={item.id}
              pressed={same({kind: 'group', id: item.id})}
              onSelect={() => setShelf({kind: 'group', id: item.id})}
              label={item.name}
              total={count({kind: 'group', id: item.id})}
              hint={item.description}
            />
          ))}
          {ungrouped > 0 && version.groups.length > 0 && (
            <ShelfButton pressed={same({kind: 'ungrouped'})} onSelect={() => setShelf({kind: 'ungrouped'})} label="Grupsuz" total={ungrouped} />
          )}
        </ul>
        <div className="pane-foot subtle">{versionLine}</div>
      </nav>
      )}

      <section className="pane" aria-label={title ?? 'Kurallar'}>
        <div className="pane-head shelf-head">
          <div className="grow">
            <h2 className="section-title">{title}</h2>
            {group?.description && <p className="subtle">{group.description}</p>}
            {!grouped && <p className="subtle">{versionLine}</p>}
          </div>
          {!grouped && <div className="shelf-search">{searchBox}</div>}
          <span className="row">
            <Badge tone="danger">{visible.filter((rule) => critical.has(rule.id)).length} kritik</Badge>
            <Badge tone="info">{visible.filter((rule) => !critical.has(rule.id)).length} normal</Badge>
          </span>
        </div>
        <div className="pane-body">
          {visible.length === 0 ? (
            <EmptyState title={search ? 'Bu grupta eşleşme yok.' : 'Bu grupta kural yok.'} icon="search" />
          ) : (
            <ol className="list rule-list">
              {visible.map((rule) => (
                <li key={rule.id} className="rule-row">
                  <div className="rule-row-head">
                    <strong className="mono">{rule.id}</strong>
                    <Badge tone={critical.has(rule.id) ? 'danger' : 'info'}>
                      {critical.has(rule.id) ? 'Kritik' : 'Normal'}
                    </Badge>
                    {rule.requires_metadata && <Badge tone="primary">Nesne meta verisi gerekir</Badge>}
                    {(rule.rule_group_ids ?? [])
                      .filter((id) => names.has(id))
                      .map((id) => (
                        <Badge key={id} tone="neutral">
                          {names.get(id)}
                        </Badge>
                      ))}
                  </div>
                  <p className="rule-row-summary">{displaySummary(rule)}</p>
                  {/* rule-management Requirement 12: only the super admin reads the detailed text. */}
                  {detailed && (
                    <details className="rule-details">
                      <summary>Ayrıntılı metni göster</summary>
                      <p className="rule-text">{rule.text}</p>
                    </details>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      </section>
    </div>
  );
}

function ShelfButton({
  pressed,
  onSelect,
  label,
  total,
  hint,
}: {
  pressed: boolean;
  onSelect: () => void;
  label: string;
  total: number;
  hint?: string;
}) {
  return (
    <li>
      <button type="button" className="shelf" aria-pressed={pressed} onClick={onSelect} title={hint || undefined}>
        <span className="grow stack-tight">
          <span className="truncate">{label}</span>
          {hint && <span className="shelf-hint clamp-2">{hint}</span>}
        </span>
        <span className="shelf-count tabular">{total}</span>
      </button>
    </li>
  );
}
