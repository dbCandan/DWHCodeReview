import {cn} from '@/lib/utils';

export function BrandMark({className}: {className?: string}) {
  return (
    <span
      className={cn(
        'relative flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-[linear-gradient(140deg,#93a3ff_0%,#6366f1_55%,#4f3fd0_100%)] shadow-[inset_0_1px_0_rgb(255_255_255/0.35),0_0_0_1px_rgb(99_102_241/0.6),0_4px_14px_-4px_rgb(99_102_241/0.7)]',
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="size-[17px]" fill="none" stroke="white" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <ellipse cx="11" cy="6" rx="6" ry="2.4" />
        <path d="M5 6v8.5c0 1.3 2.7 2.4 6 2.4" />
        <path d="M17 6v3.2" />
        <path d="m13.5 15.5 2.2 2.2 4.3-4.6" strokeWidth="2.2" />
      </svg>
    </span>
  );
}
