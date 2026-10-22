import {useId, useState} from 'react';
import {Button} from '@/components/ui/Button';
import {RULE_GROUP_NAME_LIMIT, RULE_GROUPS_LIMIT} from '@/lib/rules';
import type {RuleGroupItem} from '@/types/sqlReview';

/**
 * The named rule groups of the draft (sql-review rule-group-selection Requirement 1, 8): add,
 * rename and remove; each group shows how many rules it holds. Removing a group removes only its
 * memberships; the page owns that change. The list folds to one line of names so the rules stay in
 * view; it opens for editing, on its own when a group is added or a name is invalid.
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
  const bodyId = useId();
  const [opened, setOpened] = useState(false);
  const open = opened || problem !== null;
  return (
    <section className="card group-manager" aria-labelledby={headingId}>
      <header className="card-header">
        <h2 id={headingId}>
          Kural grupları <span className="subtle">({groups.length})</span>
        </h2>
        {!open && groups.length === 0 && (
          <span className="subtle group-manager-names">Grup yok. Kuralları gruplamak isterseniz “+ Grup” ile adını siz verin.</span>
        )}
        {!open && groups.length > 0 && (
          <ul className="list chip-row group-manager-names" aria-label="Gruplar">
            {groups.map((group) => (
              <li key={group.id} className="chip">
                {group.name.trim() || 'Adsız grup'}
                <span className="subtle tabular">{counts.get(group.id) ?? 0}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="page-actions">
          {groups.length > 0 && problem === null && (
            <Button size="sm" variant="ghost" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpened(!open)}>
              {open ? 'Grupları kapat' : 'Grupları düzenle'}
            </Button>
          )}
          <Button
            size="sm"
            onClick={() => {
              setOpened(true);
              onAdd();
            }}
            disabled={disabled || groups.length >= RULE_GROUPS_LIMIT}
            aria-label="Kural grubu ekle"
          >
            + Grup
          </Button>
        </div>
      </header>
      {open && (
      <div className="card-body stack" id={bodyId}>
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
      </div>
      )}
    </section>
  );
}
