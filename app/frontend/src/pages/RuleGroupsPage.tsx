import {useEffect, useMemo, useState} from 'react';
import {useSearchParams} from 'react-router';
import {useMutation, useQueryClient} from '@tanstack/react-query';
import {Check, Layers, Pencil, Plus, Sparkles, Trash2} from 'lucide-react';
import {api, errorMessage} from '@/lib/api';
import {qk, useGroups, useRules} from '@/hooks/queries';
import {cn, GROUP_COLORS, hexAlpha} from '@/lib/utils';
import {countBySeverity} from '@/lib/severity';
import {formatDateTime} from '@/lib/format';
import type {Rule, RuleGroup, RuleGroupInput} from '@/types';
import {PageHeader} from '@/components/layout/AppShell';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {Dialog} from '@/components/ui/Overlay';
import {Field, Input, Textarea} from '@/components/ui/Input';
import {SeverityBar, SeverityCountsInline} from '@/components/ui/Charts';
import {Alert, EmptyState, ErrorState, Skeleton} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';
import {RulePicker} from '@/components/rules/RulePicker';

export function RuleGroupsPage() {
  const groups = useGroups();
  const rules = useRules();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState<RuleGroup | 'new' | null>(null);
  const client = useQueryClient();
  const feedback = useFeedback();

  useEffect(() => {
    if (params.get('new') === '1') {
      setEditing('new');
      params.delete('new');
      setParams(params, {replace: true});
    }
  }, [params, setParams]);

  const ruleMap = useMemo(() => new Map((rules.data ?? []).map((r) => [r.id, r])), [rules.data]);

  const remove = useMutation({
    mutationFn: (g: RuleGroup) => api.groups.remove(g.id),
    onSuccess: () => {
      client.invalidateQueries({queryKey: qk.groups});
      client.invalidateQueries({queryKey: qk.rules});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success('Grup silindi');
    },
    onError: (e) => feedback.error('Grup silinemedi', e),
  });

  const onDelete = async (g: RuleGroup) => {
    if (
      await feedback.confirm({
        title: `“${g.name}” grubu silinsin mi?`,
        description: 'Gruptaki kurallar silinmez, yalnızca gruptan çıkarılır. Bu işlem geri alınamaz.',
      })
    )
      remove.mutate(g);
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Kural Grupları"
        description="Kuralları amaçlarına göre gruplayın (performans, güvenlik, standartlar…). Bir kural birden fazla grupta yer alabilir."
        actions={
          <Button data-tour="groups-new" variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>
            Yeni Grup
          </Button>
        }
      />
      {groups.isPending ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({length: 3}).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : groups.isError ? (
        <Card>
          <ErrorState error={groups.error} onRetry={() => groups.refetch()} />
        </Card>
      ) : groups.data.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Layers />}
            title="Henüz grup yok"
            description="Grup oluşturarak analiz sırasında ilgili kuralları tek tıkla seçebilirsiniz."
            action={
              <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>
                Grup oluştur
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {groups.data.map((g) => (
            <GroupCard key={g.id} group={g} rules={g.rule_ids.map((id) => ruleMap.get(id)).filter(Boolean) as Rule[]} onEdit={() => setEditing(g)} onDelete={() => onDelete(g)} />
          ))}
        </div>
      )}
      <GroupDialog
        key={editing === 'new' ? 'new' : (editing?.id ?? 'none')}
        open={editing !== null}
        group={editing === 'new' ? null : editing}
        rules={rules.data ?? []}
        onClose={() => setEditing(null)}
      />
    </div>
  );
}

function GroupCard({group: g, rules, onEdit, onDelete}: {group: RuleGroup; rules: Rule[]; onEdit: () => void; onDelete: () => void}) {
  const counts = countBySeverity(rules);
  const llmCount = rules.filter((r) => r.kind === 'llm').length;
  return (
    <Card
      className="group relative flex cursor-pointer flex-col overflow-hidden transition-[border-color,transform] duration-200 hover:-translate-y-px hover:border-line-strong"
      onClick={onEdit}
    >
      <div className="absolute inset-x-0 top-0 h-[2px]" style={{background: g.color}} />
      <div
        className="pointer-events-none absolute -top-20 -right-20 size-48 rounded-full opacity-60 blur-3xl transition-opacity group-hover:opacity-100"
        style={{background: hexAlpha(g.color, 0.14)}}
      />
      <div className="relative flex items-start gap-3 p-4">
        <span
          className="flex size-9 shrink-0 items-center justify-center rounded-lg border"
          style={{background: hexAlpha(g.color, 0.14), borderColor: hexAlpha(g.color, 0.35), color: g.color}}
        >
          <Layers className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14px] font-semibold text-fg">{g.name}</h3>
          <p className="mt-0.5 line-clamp-2 min-h-9 text-[12.5px] leading-[18px] text-fg-subtle">{g.description || 'Açıklama yok'}</p>
        </div>
        <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100" onClick={(e) => e.stopPropagation()}>
          <Button variant="ghost" size="xs" iconOnly aria-label="Düzenle" onClick={onEdit}>
            <Pencil className="size-3.5" />
          </Button>
          <Button variant="ghost" size="xs" iconOnly aria-label="Sil" className="hover:text-bad" onClick={onDelete}>
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>
      <div className="relative mt-auto flex flex-col gap-2.5 border-t border-line px-4 py-3">
        <div className="flex items-center justify-between">
          <span className="text-[13px] text-fg">
            <span className="font-semibold tnum">{g.rule_ids.length}</span> <span className="text-fg-subtle">kural</span>
            {llmCount > 0 && (
              <span className="ml-2 inline-flex items-center gap-1 text-[11.5px] text-accent">
                <Sparkles className="size-3" />
                {llmCount} LLM
              </span>
            )}
          </span>
          <SeverityCountsInline counts={counts} />
        </div>
        <SeverityBar counts={counts} height={5} />
        <span className="text-[11px] text-fg-subtle">Güncellendi {formatDateTime(g.updated_at)}</span>
      </div>
    </Card>
  );
}

function GroupDialog({open, group, rules, onClose}: {open: boolean; group: RuleGroup | null; rules: Rule[]; onClose: () => void}) {
  const [form, setForm] = useState<RuleGroupInput>(() =>
    group
      ? {name: group.name, description: group.description, color: group.color, rule_ids: group.rule_ids}
      : {name: '', description: '', color: GROUP_COLORS[0], rule_ids: []},
  );
  const [touched, setTouched] = useState(false);
  const client = useQueryClient();
  const feedback = useFeedback();
  const save = useMutation({
    mutationFn: () => (group ? api.groups.update(group.id, {...form, name: form.name.trim()}) : api.groups.create({...form, name: form.name.trim()})),
    onSuccess: () => {
      client.invalidateQueries({queryKey: qk.groups});
      client.invalidateQueries({queryKey: qk.rules});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success(group ? 'Grup güncellendi' : 'Grup oluşturuldu', form.name);
      onClose();
    },
  });
  const nameError = !form.name.trim() ? 'Ad zorunludur' : null;
  const submit = () => {
    setTouched(true);
    if (!nameError) save.mutate();
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="xl"
      icon={<Layers className="size-4" style={{color: form.color}} />}
      title={group ? 'Grubu düzenle' : 'Yeni kural grubu'}
      description="Gruba dahil edilecek kuralları soldan sağa taşıyın."
      footer={
        <>
          {save.error && <span className="mr-auto text-xs text-bad">{errorMessage(save.error)}</span>}
          <Button variant="ghost" onClick={onClose}>
            Vazgeç
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={submit}>
            {group ? 'Kaydet' : 'Grubu oluştur'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid gap-4 md:grid-cols-[1fr_auto]">
          <Field label="Ad" required error={touched && nameError}>
            <Input data-autofocus value={form.name} onChange={(e) => setForm({...form, name: e.target.value})} placeholder="Örn. Performans" aria-invalid={touched && !!nameError} />
          </Field>
          <Field label="Renk">
            <div className="flex h-8 flex-wrap items-center gap-1.5">
              {(GROUP_COLORS.includes(group?.color ?? '') || !group ? GROUP_COLORS : [group.color, ...GROUP_COLORS]).map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-label={`Renk ${c}`}
                  onClick={() => setForm({...form, color: c})}
                  className={cn(
                    'flex size-6 items-center justify-center rounded-full transition-transform hover:scale-110',
                    form.color === c && 'ring-2 ring-fg/80 ring-offset-2 ring-offset-elevated',
                  )}
                  style={{background: c}}
                >
                  {form.color === c && <Check className="size-3 text-white" strokeWidth={3} />}
                </button>
              ))}
            </div>
          </Field>
        </div>
        <Field label="Açıklama">
          <Textarea rows={2} value={form.description} onChange={(e) => setForm({...form, description: e.target.value})} placeholder="Bu grubun amacı…" />
        </Field>
        {rules.length === 0 ? (
          <Alert tone="info" title="Henüz kural yok">
            Gruba eklemek için önce Kurallar sayfasından kural oluşturun.
          </Alert>
        ) : (
          <RulePicker rules={rules} value={form.rule_ids} onChange={(ids) => setForm({...form, rule_ids: ids})} />
        )}
      </div>
    </Dialog>
  );
}
