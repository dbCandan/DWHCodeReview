import {useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Plus, ShieldOff, Trash2} from 'lucide-react';
import {api, errorMessage} from '@/lib/api';
import {qk} from '@/hooks/queries';
import {formatDateTime} from '@/lib/format';
import {exceptionScopeLabel, sortExceptions} from '@/lib/exceptions';
import type {Rule, RuleException} from '@/types';
import {Button} from '@/components/ui/Button';
import {Tooltip} from '@/components/ui/Tooltip';
import {Skeleton} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';
import {ExceptionDialog} from './ExceptionDialog';

/** Exceptions (suppressions) of an existing rule, with add/delete. */
export function RuleExceptions({rule}: {rule: Rule}) {
  const client = useQueryClient();
  const feedback = useFeedback();
  const [adding, setAdding] = useState(0);
  const list = useQuery({queryKey: qk.exceptions(rule.id), queryFn: () => api.exceptions.list(rule.id), retry: false});

  const remove = useMutation({
    mutationFn: (e: RuleException) => api.exceptions.remove(e.id),
    onSuccess: () => {
      client.invalidateQueries({queryKey: qk.exceptions(rule.id)});
      client.invalidateQueries({queryKey: qk.rules});
      feedback.success('İstisna silindi', 'Bundan sonraki analizlerde bu bulgular yeniden raporlanır.');
    },
    onError: (e) => feedback.error('İstisna silinemedi', e),
  });

  const onDelete = async (e: RuleException) => {
    if (
      await feedback.confirm({
        title: 'İstisna silinsin mi?',
        description: `${exceptionScopeLabel(e)}${e.snippet_pattern ? ` · “${e.snippet_pattern}”` : ''} istisnası kaldırılacak. Bu işlem geri alınamaz.`,
      })
    )
      remove.mutate(e);
  };

  const items = sortExceptions(list.data ?? []);

  return (
    <div className="flex flex-col gap-3">
      {list.isPending ? (
        <Skeleton className="h-14 rounded-lg" />
      ) : list.isError ? (
        <p className="rounded-lg border border-line-strong bg-surface-2/40 px-3 py-2.5 text-xs text-fg-muted">
          İstisnalar yüklenemedi: {errorMessage(list.error)}
        </p>
      ) : items.length === 0 ? (
        <p className="flex items-center gap-2 rounded-lg border border-dashed border-line-strong px-3 py-3 text-xs text-fg-subtle">
          <ShieldOff className="size-3.5 shrink-0" />
          Bu kural için istisna yok. Analiz sonuçlarındaki bir bulgudan da “İstisna tanımla” ile ekleyebilirsiniz.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-line overflow-hidden rounded-lg border border-line-strong">
          {items.map((e) => (
            <li key={e.id} className="flex items-start gap-3 bg-surface-2/30 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="rounded-md border border-line-strong bg-surface-2 px-1.5 font-mono text-[11.5px] text-fg">{exceptionScopeLabel(e)}</span>
                  {e.snippet_pattern && (
                    <code className="max-w-full truncate rounded-md bg-accent-soft px-1.5 font-mono text-[11.5px] text-fg" title={e.snippet_pattern}>
                      {e.snippet_pattern}
                    </code>
                  )}
                </div>
                <p className="mt-1 text-[12.5px] text-fg-muted">{e.reason}</p>
                <p className="mt-0.5 text-[11px] text-fg-subtle">{formatDateTime(e.created_at)}</p>
              </div>
              <Tooltip content="İstisnayı sil">
                <Button variant="ghost" size="xs" iconOnly aria-label="İstisnayı sil" className="hover:text-bad" onClick={() => onDelete(e)}>
                  <Trash2 className="size-3.5" />
                </Button>
              </Tooltip>
            </li>
          ))}
        </ul>
      )}
      <div>
        <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setAdding((n) => n + 1)}>
          İstisna ekle
        </Button>
      </div>
      <ExceptionDialog
        key={adding}
        target={adding ? {rule: {id: rule.id, code: rule.code, name: rule.name}, object: null, snippet: null} : null}
        onClose={() => setAdding(0)}
      />
    </div>
  );
}
