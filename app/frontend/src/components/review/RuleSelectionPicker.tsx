import {useId, useState} from 'react';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {useResource} from '@/hooks/useResource';
import {displaySummary, groupNamesOf, ruleMatchesSearch} from '@/lib/rules';
import {RuleSetService} from '@/services/ruleSet';
import type {RuleItem} from '@/types/sqlReview';

/**
 * Rules of the latest published version for starting a review (sql-review rule-group-selection
 * Requirement 4, 8 and Decision 6): the reviewer ticks single rules, or ticks a group to add or
 * remove all of its rules at once; nothing ticked runs every rule. The value is the selected rule
 * codes in version order; the server pins the version again and rejects a code it no longer has.
 */
export function RuleSelectionPicker({
  value,
  disabled,
  onChange,
}: {
  value: string[];
  disabled: boolean;
  onChange: (ruleCodes: string[]) => void;
}) {
  const latest = useResource('rule-set-version:latest', (signal) => RuleSetService.latest(signal));
  const [search, setSearch] = useState('');
  const legendId = useId();
  const searchId = useId();
  const rules: RuleItem[] = [...(latest.data?.critical ?? []), ...(latest.data?.normal ?? [])];
  const groups = latest.data?.groups ?? [];
  if (rules.length === 0) return null;
  const critical = new Set((latest.data?.critical ?? []).map((rule) => rule.id));
  const selected = new Set(value);
  const visible = rules.filter((rule) => ruleMatchesSearch(rule, search));

  function emit(next: Set<string>) {
    // Version order keeps the request and the run's stored selection stable.
    onChange(rules.filter((rule) => next.has(rule.id)).map((rule) => rule.id));
  }

  function toggleRule(code: string, checked: boolean) {
    const next = new Set(selected);
    if (checked) next.add(code);
    else next.delete(code);
    emit(next);
  }

  function toggleGroup(groupId: string, checked: boolean) {
    const next = new Set(selected);
    for (const rule of rules) {
      if (!(rule.rule_group_ids ?? []).includes(groupId)) continue;
      if (checked) next.add(rule.id);
      else next.delete(rule.id);
    }
    emit(next);
  }

  return (
    <fieldset className="field" role="group" aria-labelledby={legendId}>
      <legend id={legendId} className="field-label">
        Kurallar
      </legend>
      <p className="field-hint">
        {selected.size === 0
          ? 'Hiçbir kural seçilmezse tüm kurallar çalışır.'
          : `${selected.size} / ${rules.length} kural seçildi.`}
      </p>
      {groups.length > 0 && (
        <div className="row" role="group" aria-label="Grupla seç">
          {groups.map((group) => {
            const members = rules.filter((rule) => (rule.rule_group_ids ?? []).includes(group.id));
            const chosen = members.filter((rule) => selected.has(rule.id)).length;
            return (
              <label key={group.id} className="check">
                <input
                  type="checkbox"
                  checked={members.length > 0 && chosen === members.length}
                  ref={(input) => {
                    if (input) input.indeterminate = chosen > 0 && chosen < members.length;
                  }}
                  disabled={disabled || members.length === 0}
                  onChange={(event) => toggleGroup(group.id, event.target.checked)}
                />
                <span>
                  {group.name} ({members.length} kural)
                </span>
              </label>
            );
          })}
        </div>
      )}
      <div className="row">
        <div className="field grow">
          <label className="sr-only" htmlFor={searchId}>
            Kural ara
          </label>
          <input
            id={searchId}
            className="input"
            type="search"
            value={search}
            placeholder="Kural kimliği veya metin ara…"
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        {selected.size > 0 && (
          <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onChange([])}>
            Seçimi temizle
          </Button>
        )}
      </div>
      {visible.length === 0 ? (
        <p className="muted">Eşleşen kural yok.</p>
      ) : (
        <ul className="list stack-tight rule-pick-list">
          {visible.map((rule) => (
            <li key={rule.id}>
              <label className="check">
                <input
                  type="checkbox"
                  checked={selected.has(rule.id)}
                  disabled={disabled}
                  onChange={(event) => toggleRule(rule.id, event.target.checked)}
                />
                <span className="stack-tight">
                  <span className="row">
                    <span className="mono">{rule.id}</span>
                    {critical.has(rule.id) && <Badge tone="danger">Kritik</Badge>}
                    {groupNamesOf(rule, groups).map((name) => (
                      <Badge key={name} tone="neutral">
                        {name}
                      </Badge>
                    ))}
                  </span>
                  {/* rule-management Requirement 12: one sentence, not the detailed text. */}
                  <span className="subtle">{displaySummary(rule)}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}
