import {useId} from 'react';
import {Button} from '@/components/ui/Button';
import {RULE_GROUP_NAME_LIMIT, RULE_GROUPS_LIMIT} from '@/lib/rules';
import type {RuleGroupItem} from '@/types/sqlReview';

/**
 * The named rule groups of the draft (sql-review rule-group-selection Requirement 1, 8): add,
 * rename and remove; each group shows how many rules it holds. Removing a group removes only its
 * memberships; the page owns that change.
 */
export function RuleGroupManager({
  groups,
  counts,
  problem,
  disabled,
  onRename,
  onRemove,
  onAdd,
}: {
  groups: RuleGroupItem[];
  counts: Map<string, number>;
  problem: string | null;
  disabled: boolean;
  onRename: (id: string, name: string) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
}) {
  const headingId = useId();
  const problemId = useId();
  return (
    <section className="card" aria-labelledby={headingId}>
      <header className="card-header">
        <h2 id={headingId}>
          Kural grupları <span className="subtle">({groups.length})</span>
        </h2>
      </header>
      <div className="card-body stack">
        <p className="muted">
          İnceleyiciler bir grubun kurallarını tek tıkla seçebilir, ayrıca tek tek kural da seçebilir. Bir kural
          birden çok grupta olabilir; grubu olmayan kural da tek başına seçilebilir.
        </p>
        {groups.length === 0 && <p className="muted">Henüz kural grubu yok.</p>}
        <ol className="list stack-tight">
          {groups.map((group, index) => (
            <li key={group.id} className="row">
              <input
                className="input grow"
                aria-label={`Kural grubu ${index + 1} adı`}
                aria-invalid={problem !== null || undefined}
                aria-describedby={problem ? problemId : undefined}
                value={group.name}
                maxLength={RULE_GROUP_NAME_LIMIT * 2}
                disabled={disabled}
                onChange={(event) => onRename(group.id, event.target.value)}
              />
              <span className="subtle nowrap tabular">{counts.get(group.id) ?? 0} kural</span>
              <Button
                size="sm"
                variant="danger-outline"
                aria-label={`${group.name.trim() || `Kural grubu ${index + 1}`} grubunu sil`}
                disabled={disabled}
                onClick={() => onRemove(group.id)}
              >
                Sil
              </Button>
            </li>
          ))}
        </ol>
        {problem && (
          <p id={problemId} className="field-error" role="alert">
            {problem}
          </p>
        )}
        <Button
          onClick={onAdd}
          disabled={disabled || groups.length >= RULE_GROUPS_LIMIT}
          aria-label="Kural grubu ekle"
        >
          + Grup
        </Button>
      </div>
    </section>
  );
}
