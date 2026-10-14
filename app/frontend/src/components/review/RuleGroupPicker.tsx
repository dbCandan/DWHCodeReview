import {useId} from 'react';
import {useResource} from '@/hooks/useResource';
import {groupRuleCounts} from '@/lib/rules';
import {RuleSetService} from '@/services/ruleSet';

/**
 * Named rule groups of the latest published version for a scheduled review definition
 * (sql-review scheduled-review-email, rule-group-selection Requirement 4): one or more groups, or
 * none for every rule. A rule in several groups counts in each. The server rejects a group the
 * latest version no longer has.
 */
export function RuleGroupPicker({
  value,
  disabled,
  onChange,
}: {
  value: string[];
  disabled: boolean;
  onChange: (ruleGroupIds: string[]) => void;
}) {
  const latest = useResource('rule-set-version:latest', (signal) => RuleSetService.latest(signal));
  const legendId = useId();
  const groups = latest.data?.groups ?? [];
  if (groups.length === 0) return null;
  const counts = groupRuleCounts(latest.data?.critical ?? [], latest.data?.normal ?? []);
  const selected = new Set(value);

  function toggle(id: string, checked: boolean) {
    const next = new Set(selected);
    if (checked) next.add(id);
    else next.delete(id);
    // Version order keeps the request and the stored selection stable.
    onChange(groups.filter((group) => next.has(group.id)).map((group) => group.id));
  }

  return (
    <fieldset className="field" role="group" aria-labelledby={legendId}>
      <legend id={legendId} className="field-label">
        Kural grupları
      </legend>
      <p className="field-hint">Hiçbir grup seçilmezse tüm kurallar çalışır.</p>
      <div className="row">
        {groups.map((group) => (
          <label key={group.id} className="check">
            <input
              type="checkbox"
              checked={selected.has(group.id)}
              disabled={disabled}
              onChange={(event) => toggle(group.id, event.target.checked)}
            />
            <span>
              {group.name} ({counts.get(group.id) ?? 0} kural)
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
