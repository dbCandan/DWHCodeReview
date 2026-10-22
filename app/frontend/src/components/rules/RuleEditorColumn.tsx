import {useId, useState} from 'react';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {
  PREVIEW_CHARS,
  RULE_SUMMARY_LIMIT,
  RULE_TEXT_LIMIT,
  displaySummary,
  groupNamesOf,
  previewText,
  ruleMatchesSearch,
  summaryProblem,
  type Tier,
} from '@/lib/rules';
import type {RuleGroupItem, RuleItem} from '@/types/sqlReview';

export interface RuleEditorActions {
  onText: (id: string, text: string) => void;
  /** rule-management Requirement 12: the one-sentence summary others see. */
  onSummary: (id: string, summary: string) => void;
  onRequiresMetadata: (id: string, value: boolean) => void;
  onMove: (index: number, delta: -1 | 1) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
  /** rule-group-selection Decision 1: a rule joins or leaves one of its several named groups. */
  onGroup: (id: string, groupId: string, member: boolean) => void;
}

const TITLES: Record<Tier, {title: string; hint: string}> = {
  critical: {title: 'Kritik', hint: 'HIGH'},
  normal: {title: 'Normal', hint: 'LOW / MEDIUM'},
};

/** One priority group of the draft; rules move only inside their own group. */
export function RuleEditorColumn({
  tier,
  rules,
  groups,
  search,
  disabled,
  actions,
}: {
  tier: Tier;
  rules: RuleItem[];
  groups: RuleGroupItem[];
  search: string;
  disabled: boolean;
  actions: RuleEditorActions;
}) {
  const headingId = useId();
  const visible = rules.filter((rule) => ruleMatchesSearch(rule, search));
  return (
    <section className={`card card-${tier}`} aria-labelledby={headingId}>
      <header className="card-header">
        <h2 id={headingId}>
          {TITLES[tier].title} <span className="subtle">({rules.length})</span>
        </h2>
        <Badge tone={tier === 'critical' ? 'danger' : 'info'}>{TITLES[tier].hint}</Badge>
      </header>
      <div className="card-body stack">
        {rules.length === 0 && <p className="muted">Bu grupta kural yok.</p>}
        {rules.length > 0 && visible.length === 0 && <p className="muted">Bu grupta eşleşme yok.</p>}
        <ol className="list stack-tight">
          {rules.map((rule, index) =>
            ruleMatchesSearch(rule, search) ? (
              <RuleRow
                key={rule.id}
                rule={rule}
                groups={groups}
                index={index}
                total={rules.length}
                disabled={disabled}
                actions={actions}
              />
            ) : null,
          )}
        </ol>
        <Button onClick={actions.onAdd} disabled={disabled} aria-label={`${TITLES[tier].title} grubuna kural ekle`}>
          + Kural
        </Button>
      </div>
    </section>
  );
}

function RuleRow({
  rule,
  groups,
  index,
  total,
  disabled,
  actions,
}: {
  rule: RuleItem;
  groups: RuleGroupItem[];
  index: number;
  total: number;
  disabled: boolean;
  actions: RuleEditorActions;
}) {
  const [open, setOpen] = useState(rule.text === '');
  const textId = useId();
  const summaryId = useId();
  const groupLegendId = useId();
  const tooLong = rule.text.length > RULE_TEXT_LIMIT;
  const summaryError = summaryProblem(rule.summary ?? '');
  const memberships = new Set(rule.rule_group_ids ?? []);
  if (!open)
    return (
      <li className="disclosure">
        <button type="button" aria-expanded={false} onClick={() => setOpen(true)} title={`İlk ${PREVIEW_CHARS} karakter`}>
          <span className="row">
            <span className="subtle tabular">{index + 1}</span>
            <span className="mono">{rule.id}</span>
            {rule.requires_metadata && <Badge tone="primary">Meta veri</Badge>}
            {groupNamesOf(rule, groups).map((name, position) => (
              <Badge key={`${name}-${position}`} tone="neutral">
                {name}
              </Badge>
            ))}
          </span>
          <span className="grow subtle clamp-2">{previewText(displaySummary(rule) || rule.text)}</span>
        </button>
      </li>
    );
  return (
    <li className="rule-line">
      <div className="row">
        <span className="subtle tabular">{index + 1}</span>
        <strong className="mono">{rule.id}</strong>
        <span className="row push-end">
          <Button
            size="sm"
            variant="ghost"
            className="icon-btn"
            aria-label={`${rule.id} yukarı taşı`}
            disabled={disabled || index === 0}
            onClick={() => actions.onMove(index, -1)}
          >
            ↑
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="icon-btn"
            aria-label={`${rule.id} aşağı taşı`}
            disabled={disabled || index === total - 1}
            onClick={() => actions.onMove(index, 1)}
          >
            ↓
          </Button>
          <Button
            size="sm"
            variant="danger-outline"
            aria-label={`${rule.id} sil`}
            disabled={disabled}
            onClick={() => actions.onRemove(rule.id)}
          >
            Sil
          </Button>
          <Button size="sm" variant="ghost" aria-expanded={true} aria-label={`${rule.id} daralt`} onClick={() => setOpen(false)}>
            Daralt
          </Button>
        </span>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={Boolean(rule.requires_metadata)}
          disabled={disabled}
          onChange={(event) => actions.onRequiresMetadata(rule.id, event.target.checked)}
        />
        <span>
          <span className="sr-only">{rule.id}: </span>Nesne meta verisi gerekir (bağımlılık ve sütun özeti yalnız veritabanından okunan nesnelerin
          incelemesine eklenir)
        </span>
      </label>
      {groups.length > 0 && (
        <fieldset className="field" role="group" aria-labelledby={groupLegendId}>
          <legend id={groupLegendId} className="field-label">
            <span className="sr-only">{rule.id}: </span>Kural grupları
          </legend>
          <div className="row">
            {groups.map((item, index) => (
              <label key={item.id} className="check">
                <input
                  type="checkbox"
                  checked={memberships.has(item.id)}
                  disabled={disabled}
                  onChange={(event) => actions.onGroup(rule.id, item.id, event.target.checked)}
                />
                <span>{item.name.trim() || `Kural grubu ${index + 1}`}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <div className="field">
        <label className="field-label" htmlFor={summaryId}>
          <span className="sr-only">{rule.id}: </span>Özet (tek cümle)
        </label>
        <input
          id={summaryId}
          className="input"
          value={rule.summary ?? ''}
          disabled={disabled}
          placeholder={displaySummary({text: rule.text, summary: ''}) || 'Kuralı tek cümleyle anlatın…'}
          aria-invalid={summaryError !== null || undefined}
          aria-describedby={`${summaryId}-hint`}
          onChange={(event) => actions.onSummary(rule.id, event.target.value)}
        />
        <p id={`${summaryId}-hint`} className={summaryError ? 'field-error' : 'field-hint'}>
          {summaryError ??
            `Süper yönetici dışındaki kullanıcılar kuralı bu cümleyle görür; boş bırakılırsa metnin ilk cümlesi gösterilir (en çok ${RULE_SUMMARY_LIMIT} karakter).`}
        </p>
      </div>
      <div className="field">
        <label className="sr-only" htmlFor={textId}>
          {rule.id} kural metni
        </label>
        <textarea
          id={textId}
          className="textarea"
          rows={5}
          value={rule.text}
          disabled={disabled}
          placeholder="Kural metni…"
          aria-invalid={tooLong || undefined}
          aria-describedby={`${textId}-count`}
          onChange={(event) => actions.onText(rule.id, event.target.value)}
        />
        <p id={`${textId}-count`} className={`counter${tooLong ? ' is-over' : ''}`}>
          {rule.text.length.toLocaleString('tr-TR')} / {RULE_TEXT_LIMIT.toLocaleString('tr-TR')} karakter
          {tooLong ? ' — kural metni en çok 8.000 karakter olabilir.' : ''}
        </p>
      </div>
    </li>
  );
}
