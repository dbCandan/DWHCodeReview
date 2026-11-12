import type {HTMLAttributes, ReactNode} from 'react';
import {cn} from '@/lib/utils';

export function Card({className, children, ...rest}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('rounded-xl border border-line bg-surface shadow-card', className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  description,
  actions,
  icon,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex items-start justify-between gap-3 border-b border-line px-4 py-3', className)}>
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && <span className="mt-0.5 flex text-fg-subtle">{icon}</span>}
        <div className="min-w-0">
          <h3 className="truncate text-[13px] font-semibold tracking-[-0.005em] text-fg">{title}</h3>
          {description && <p className="mt-0.5 text-xs text-fg-subtle">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </div>
  );
}

export function CardBody({className, children}: {className?: string; children: ReactNode}) {
  return <div className={cn('p-4', className)}>{children}</div>;
}

export function Section({title, description, children, actions}: {title: ReactNode; description?: ReactNode; children: ReactNode; actions?: ReactNode}) {
  return (
    <Card>
      <CardHeader title={title} description={description} actions={actions} />
      <CardBody>{children}</CardBody>
    </Card>
  );
}
