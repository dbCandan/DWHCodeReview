import {createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {CircleAlert, CircleCheck, Info, TriangleAlert, X} from 'lucide-react';
import {cn} from '@/lib/utils';
import {errorMessage} from '@/lib/api';
import {Button} from './Button';
import {Dialog} from './Overlay';

type ToastTone = 'success' | 'error' | 'info';
interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
}

interface ConfirmOptions {
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  tone?: 'danger' | 'primary';
}

interface FeedbackApi {
  success: (title: string, description?: string) => void;
  error: (title: string, error?: unknown) => void;
  info: (title: string, description?: string) => void;
  confirm: (options: ConfirmOptions) => Promise<boolean>;
}

const FeedbackContext = createContext<FeedbackApi | null>(null);

export function FeedbackProvider({children}: {children: ReactNode}) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [confirmState, setConfirmState] = useState<(ConfirmOptions & {resolve: (v: boolean) => void}) | null>(null);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => setToasts((list) => list.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (tone: ToastTone, title: string, description?: string) => {
      const id = ++seq.current;
      setToasts((list) => [...list.slice(-3), {id, tone, title, description}]);
      window.setTimeout(() => dismiss(id), tone === 'error' ? 7000 : 4000);
    },
    [dismiss],
  );

  const api = useMemo<FeedbackApi>(
    () => ({
      success: (title, description) => push('success', title, description),
      info: (title, description) => push('info', title, description),
      error: (title, error) => push('error', title, error === undefined ? undefined : errorMessage(error)),
      confirm: (options) => new Promise<boolean>((resolve) => setConfirmState({...options, resolve})),
    }),
    [push],
  );

  const closeConfirm = (value: boolean) => {
    confirmState?.resolve(value);
    setConfirmState(null);
  };

  return (
    <FeedbackContext.Provider value={api}>
      {children}
      <Dialog
        open={!!confirmState}
        onClose={() => closeConfirm(false)}
        size="sm"
        icon={<TriangleAlert className={cn('size-4', confirmState?.tone === 'primary' ? 'text-accent' : 'text-bad')} />}
        title={confirmState?.title ?? ''}
        description={confirmState?.description}
        footer={
          <>
            <Button variant="ghost" onClick={() => closeConfirm(false)}>
              Vazgeç
            </Button>
            <Button
              data-autofocus
              variant={confirmState?.tone === 'primary' ? 'primary' : 'danger'}
              onClick={() => closeConfirm(true)}
            >
              {confirmState?.confirmLabel ?? 'Sil'}
            </Button>
          </>
        }
      />
      {createPortal(
        <div className="pointer-events-none fixed right-4 bottom-20 z-[90] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
          {toasts.map((t) => (
            <div
              key={t.id}
              role="status"
              className="pointer-events-auto flex animate-pop-in items-start gap-2.5 rounded-xl border border-line-strong bg-elevated/95 px-3.5 py-3 shadow-pop backdrop-blur"
            >
              <span className="mt-px">
                {t.tone === 'success' ? (
                  <CircleCheck className="size-4 text-ok" />
                ) : t.tone === 'error' ? (
                  <CircleAlert className="size-4 text-bad" />
                ) : (
                  <Info className="size-4 text-accent" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium text-fg">{t.title}</p>
                {t.description && <p className="mt-0.5 break-words text-xs text-fg-muted">{t.description}</p>}
              </div>
              <button
                type="button"
                aria-label="Kapat"
                onClick={() => dismiss(t.id)}
                className="flex size-5 items-center justify-center rounded text-fg-subtle hover:bg-surface-3 hover:text-fg"
              >
                <X className="size-3.5" />
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </FeedbackContext.Provider>
  );
}

export function useFeedback(): FeedbackApi {
  const ctx = useContext(FeedbackContext);
  if (!ctx) throw new Error('useFeedback must be used inside FeedbackProvider');
  return ctx;
}
