import {classes} from '@/lib/utils';

/**
 * The product mark: a reviewed data-warehouse table (a database drum with a check) on the brand
 * tile. Decorative; the product name beside it is the accessible name.
 */
export function BrandMark({className}: {className?: string}) {
  return (
    <svg className={classes('brand-mark', className)} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect className="brand-mark-tile" width="32" height="32" rx="8" />
      <g className="brand-mark-glyph">
        <ellipse cx="14" cy="9.5" rx="6.5" ry="2.5" />
        <path d="M7.5 9.5v12c0 1.4 2.9 2.5 6.5 2.5" />
        <path d="M20.5 9.5v5" />
        <path d="M7.5 15.5c0 1.4 2.9 2.5 6.5 2.5" />
        <path d="m18 22 2.5 2.5 5-5.5" />
      </g>
    </svg>
  );
}
