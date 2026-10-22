import {useRef, type KeyboardEvent} from 'react';
import {classes} from '@/lib/utils';

export interface TabItem<T extends string> {
  id: T;
  label: string;
  /** Shown in a pill; the accessible name reads "label (count)". */
  count?: number;
  /** Highlights a non-zero count, such as decisions waiting. */
  attention?: boolean;
}

/**
 * An underlined tab strip with the WAI-ARIA tabs keyboard model: the selected tab is the single tab
 * stop and the arrow, Home and End keys move the selection.
 */
export function Tabs<T extends string>({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = items.length - 1;
    const target =
      event.key === 'ArrowRight' ? (index === last ? 0 : index + 1)
      : event.key === 'ArrowLeft' ? (index === 0 ? last : index - 1)
      : event.key === 'Home' ? 0
      : event.key === 'End' ? last
      : null;
    if (target === null) return;
    event.preventDefault();
    onChange(items[target].id);
    refs.current[target]?.focus();
  }

  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((item, index) => (
        <button
          key={item.id}
          ref={(node) => {
            refs.current[index] = node;
          }}
          type="button"
          role="tab"
          className="tab"
          aria-selected={value === item.id}
          aria-label={item.count === undefined ? undefined : `${item.label} (${item.count})`}
          tabIndex={value === item.id ? 0 : -1}
          onClick={() => onChange(item.id)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {item.label}
          {item.count !== undefined && (
            <span className={classes('tab-count', item.attention && item.count > 0 && 'is-attention')} aria-hidden="true">
              {item.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
