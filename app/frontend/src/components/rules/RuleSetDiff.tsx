import {Badge} from '@/components/ui/Badge';
import {displaySummary} from '@/lib/rules';
import type {DiffRuleItem, RuleGroupItem, RuleSetDiffView} from '@/types/sqlReview';

const PRIORITY: Record<DiffRuleItem['priority'], string> = {critical: 'Kritik', normal: 'Normal'};

/**
 * What a publish request changes against the latest published version (sql-review rule-proposals
 * Requirement 6): added, changed and removed rules with their detailed text, and group changes.
 * Only the super admin sees it.
 */
export function RuleSetDiff({diff}: {diff: RuleSetDiffView}) {
  const empty =
    diff.added_rules.length +
      diff.changed_rules.length +
      diff.removed_rules.length +
      diff.added_groups.length +
      diff.changed_groups.length +
      diff.removed_groups.length ===
    0;
  if (empty) return <p className="muted">Taslak en son yayımlanmış sürümle aynı.</p>;
  return (
    <div className="stack">
      <RuleList title="Eklenen kurallar" rules={diff.added_rules} tone="success" />
      {diff.changed_rules.length > 0 && (
        <section className="stack-tight" aria-label="Değişen kurallar">
          <h3>Değişen kurallar ({diff.changed_rules.length})</h3>
          <ul className="list stack">
            {diff.changed_rules.map(({before, after}) => (
              <li key={after.id} className="rule-line stack-tight">
                <RuleLine rule={after} tone="warning" />
                <p className="subtle">Önceki hali:</p>
                <RuleBody rule={before} />
                <p className="subtle">Yeni hali:</p>
                <RuleBody rule={after} />
              </li>
            ))}
          </ul>
        </section>
      )}
      <RuleList title="Silinen kurallar" rules={diff.removed_rules} tone="danger" />
      <GroupList title="Eklenen gruplar" groups={diff.added_groups} />
      {diff.changed_groups.length > 0 && (
        <section className="stack-tight" aria-label="Değişen gruplar">
          <h3>Değişen gruplar ({diff.changed_groups.length})</h3>
          <ul className="list stack-tight">
            {diff.changed_groups.map(({before, after}) => (
              <li key={after.id}>
                {before.name} → {after.name}
                {before.description !== after.description && ` (açıklama: ${after.description || '—'})`}
              </li>
            ))}
          </ul>
        </section>
      )}
      <GroupList title="Silinen gruplar" groups={diff.removed_groups} />
    </div>
  );
}

function RuleList({title, rules, tone}: {title: string; rules: DiffRuleItem[]; tone: 'success' | 'danger'}) {
  if (rules.length === 0) return null;
  return (
    <section className="stack-tight" aria-label={title}>
      <h3>
        {title} ({rules.length})
      </h3>
      <ul className="list stack">
        {rules.map((rule) => (
          <li key={rule.id} className="rule-line stack-tight">
            <RuleLine rule={rule} tone={tone} />
            <RuleBody rule={rule} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function RuleLine({rule, tone}: {rule: DiffRuleItem; tone: 'success' | 'danger' | 'warning'}) {
  return (
    <div className="row">
      <Badge tone={tone}>{rule.id}</Badge>
      <Badge tone={rule.priority === 'critical' ? 'danger' : 'info'}>{PRIORITY[rule.priority]}</Badge>
      {rule.requires_metadata && <Badge tone="primary">Meta veri</Badge>}
      <strong>{displaySummary(rule)}</strong>
    </div>
  );
}

function RuleBody({rule}: {rule: DiffRuleItem}) {
  return <p className="rule-text">{rule.text}</p>;
}

function GroupList({title, groups}: {title: string; groups: RuleGroupItem[]}) {
  if (groups.length === 0) return null;
  return (
    <section className="stack-tight" aria-label={title}>
      <h3>
        {title} ({groups.length})
      </h3>
      <ul className="list stack-tight">
        {groups.map((group) => (
          <li key={group.id}>{group.description ? `${group.name}: ${group.description}` : group.name}</li>
        ))}
      </ul>
    </section>
  );
}
