import type {ReactNode} from 'react';
import {Alert} from './Alert';
import {Button} from './Button';
import {Icon, type IconName} from './Icon';

export function LoadingState({label = 'Yükleniyor…'}: {label?: string}) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  );
}

export function EmptyState({title, icon, children}: {title: string; icon?: IconName; children?: ReactNode}) {
  return (
    <div className="state">
      {icon !== undefined && (
        <span className="state-icon">
          <Icon name={icon} />
        </span>
      )}
      <p className="state-title">{title}</p>
      {children !== undefined && <div className="state-body">{children}</div>}
    </div>
  );
}

export function ErrorState({message, onRetry}: {message: string; onRetry?: () => void}) {
  return (
    <Alert tone="error">
      <div className="row">
        <p className="grow">{message}</p>
        {onRetry && (
          <Button size="sm" onClick={onRetry}>
            Yeniden dene
          </Button>
        )}
      </div>
    </Alert>
  );
}
