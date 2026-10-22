import {useId, useState} from 'react';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {Icon} from '@/components/ui/Icon';
import {useResource} from '@/hooks/useResource';
import {displaySummary, groupNamesOf, ruleMatchesSearch} from '@/lib/rules';
import {RuleSetService} from '@/services/ruleSet';
import type {RuleItem} from '@/types/sqlReview';

const UNGROUPED = '__ungrouped__';

interface Shelf {
  key: string;
  name: string;
  description: string;
  rules: RuleItem[];
}

/**
 * Rules of the latest published version for starting a review (sql-review rule-group-selection
 * Requirement 4, 8 and Decision 6). Groups are listed one under another: a group's box selects or
 * clears all of its rules, and opening the group shows its rules beneath it to pick one by one.
 * Typing in the search shows the matching rules as one list. Nothing ticked runs every rule. The
 * value is the selected rule codes in version order; the server pins the version again and rejects
 * a code it no longer has.
 */
export function RuleSelectionPicker({
  value,
  disabled,
  onChange,
  plain = false,
}: {
  value: string[];
  disabled: boolean;
  onChange: (ruleCodes: string[]) => void;
  /** Without its own card, for a side panel that frames it. */
  plain?: boolean;
}) {
  const latest = useResource('rule-set-version:latest', (signal) => RuleSetService.latest(signal));
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState<Set<string>>(new Set());
  const legendId = useId();
  const searchId = useId();
  const rules: RuleItem[] = [...(latest.data?.critical ?? []), ...(latest.data?.normal ?? [])];
  const groups = latest.data?.groups ?? [];
  if (rules.length === 0) return null;
  const critical = new Set((latest.data?.critical ?? []).map((rule) => rule.id));
  const selected = new Set(value);
  const known = new Set(groups.map((group) => group.id));
  const shelves: Shelf[] = groups.map((group) => ({
    key: group.id,
    name: group.name,
    description: group.description,
    rules: rules.filter((rule) => (rule.rule_group_ids ?? []).includes(group.id)),
  }));
  const ungrouped = rules.filter((rule) => !(rule.rule_group_ids ?? []).some((id) => known.has(id)));
  if (groups.length > 0 && ungrouped.length > 0)
    shelves.push({key: UNGROUPED, name: 'Grupsuz', description: 'Hiçbir gruba bağlı olmayan kurallar', rules: ungrouped});
  const searching = search.trim() !== '';
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

  function toggleShelf(members: RuleItem[], checked: boolean) {
    const next = new Set(selected);
    for (const rule of members) {
      if (checked) next.add(rule.id);
      else next.delete(rule.id);
    }
    emit(next);
  }

  function toggleOpen(key: string) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const ruleRow = (rule: RuleItem, showGroups: boolean) => (
    <li key={rule.id}>
      <label className="option-row">
        <input
          type="checkbox"
          checked={selected.has(rule.id)}
          disabled={disabled}
          onChange={(event) => toggleRule(rule.id, event.target.checked)}
        />
        <span className="option-main">
          <span className="option-title">
            <span className="mono">{rule.id}</span>
            {critical.has(rule.id) && <Badge tone="danger">Kritik</Badge>}
            {showGroups &&
              groupNamesOf(rule, groups).map((name) => (
                <Badge key={name} tone="neutral">
                  {name}
                </Badge>
              ))}
          </span>
          {/* rule-management Requirement 12: one sentence, not the detailed text. */}
          <span className="option-text">{displaySummary(rule)}</span>
        </span>
      </label>
    </li>
  );

  return (
    <fieldset className={plain ? 'picker' : 'card card-body picker'} role="group" aria-labelledby={legendId}>
      <div className="picker-head">
        <legend id={legendId} className="picker-title">
          Kurallar
        </legend>
        <span className="row">
          <Badge tone={selected.size === 0 ? 'neutral' : 'primary'}>
            {selected.size === 0 ? 'Tüm kurallar' : `${selected.size} / ${rules.length} seçili`}
          </Badge>
          {selected.size > 0 && (
            <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onChange([])}>
              Seçimi temizle
            </Button>
          )}
        </span>
      </div>
      <p className="field-hint">
        <span>
          {selected.size === 0
            ? 'Hiçbir kural seçilmezse tüm kurallar çalışır.'
            : `${selected.size} / ${rules.length} kural seçildi.`}
        </span>{' '}
        {shelves.length > 0 && <span>Grubun kutusu o gruptaki bütün kuralları seçer; grubu açıp tek tek de seçebilirsiniz.</span>}
      </p>
      <div>
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
      <div className="picker-body">
        {searching || shelves.length === 0 ? (
          visible.length === 0 ? (
            <p className="muted">Eşleşen kural yok.</p>
          ) : (
            <ul className="option-list">{visible.map((rule) => ruleRow(rule, true))}</ul>
          )
        ) : (
          <ul className="list group-list" role="group" aria-label="Grupla seç">
            {shelves.map((shelf) => {
              const chosen = shelf.rules.filter((rule) => selected.has(rule.id)).length;
              const expanded = open.has(shelf.key);
              const bodyId = `${legendId}-${shelf.key}`;
              return (
                <li key={shelf.key} className={`group-section${chosen > 0 ? ' has-choice' : ''}`}>
                  <div className="group-head">
                    <input
                      type="checkbox"
                      aria-label={`${shelf.name} (${shelf.rules.length} kural)`}
                      checked={shelf.rules.length > 0 && chosen === shelf.rules.length}
                      ref={(input) => {
                        if (input) input.indeterminate = chosen > 0 && chosen < shelf.rules.length;
                      }}
                      disabled={disabled || shelf.rules.length === 0}
                      onChange={(event) => toggleShelf(shelf.rules, event.target.checked)}
                    />
                    <button
                      type="button"
                      className="group-toggle"
                      aria-expanded={expanded}
                      aria-controls={bodyId}
                      onClick={() => toggleOpen(shelf.key)}
                    >
                      <span className="grow stack-tight">
                        <span className="group-name truncate">{shelf.name}</span>
                        {shelf.description && <span className="group-desc truncate">{shelf.description}</span>}
                      </span>
                      <span className="group-count tabular">
                        {chosen > 0 ? `${chosen}/${shelf.rules.length}` : shelf.rules.length}
                      </span>
                      <Icon name="arrowRight" className="group-chevron" />
                    </button>
                  </div>
                  {expanded && (
                    <ul id={bodyId} className="option-list nested">
                      {shelf.rules.map((rule) => ruleRow(rule, false))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </fieldset>
  );
}
