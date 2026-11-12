import {useEffect, useState} from 'react';
import {Link, useLocation, useNavigate, useParams} from 'react-router';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {ArrowLeft, GitMerge, History, Plus, SquarePlus} from 'lucide-react';
import {api, ApiError, errorMessage} from '@/lib/api';
import {qk} from '@/hooks/queries';
import {cn} from '@/lib/utils';
import {relativeTime} from '@/lib/format';
import {
  ASSISTANT_STATUS_LABEL,
  buildAssistantRequest,
  emptyAssistantForm,
  formFromRequest,
  wizardStep,
  type AssistantForm,
} from '@/lib/assistant';
import type {AssistantRequest, AssistantSession, RuleInput} from '@/types';
import {PageHeader} from '@/components/layout/AppShell';
import {Stepper} from '@/components/ui/Progress';
import {Card, CardHeader} from '@/components/ui/Card';
import {buttonClass} from '@/components/ui/Button';
import {EmptyState, ErrorState, Skeleton} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';
import {DefinitionStep} from '@/components/assistant/DefinitionStep';
import {RunningStep} from '@/components/assistant/RunningStep';
import {ProposalStep} from '@/components/assistant/ProposalStep';

const STEPS = [
  {title: 'Tanım', description: 'Açıklama ve örnekler'},
  {title: 'Çalışıyor', description: 'LLM taslak ve doğrulama'},
  {title: 'Öneri ve onay', description: 'Gözden geçir ve kaydet'},
];

/** 404 from the assistant endpoints = backend without v1.6. */
function assistantError(e: unknown): string {
  if (e instanceof ApiError && e.status === 404) return `${e.message} (Kural asistanı uç noktaları sunucuda henüz yoksa backend güncellenmelidir.)`;
  return errorMessage(e);
}
const asError = (e: unknown) => new Error(assistantError(e));

const STATUS_TONE: Record<AssistantSession['status'], string> = {
  running: 'bg-accent-soft text-accent ring-accent/30',
  ready: 'bg-warn-soft text-warn ring-warn/30',
  saved: 'bg-ok-soft text-ok ring-ok/30',
  failed: 'bg-bad-soft text-bad ring-bad/30',
  cancelled: 'bg-surface-3 text-fg-muted ring-line-strong',
};

export function StatusTag({status}: {status: AssistantSession['status']}) {
  return (
    <span className={cn('inline-flex h-5 shrink-0 items-center rounded-md px-1.5 text-[11px] font-semibold ring-1 ring-inset', STATUS_TONE[status] ?? STATUS_TONE.cancelled)}>
      {ASSISTANT_STATUS_LABEL[status] ?? status}
    </span>
  );
}

function PreviousSessions({currentId}: {currentId: number | null}) {
  const list = useQuery({queryKey: qk.assistantSessions, queryFn: () => api.assistant.list(20), retry: false});
  return (
    <Card className="overflow-hidden">
      <CardHeader
        icon={<History className="size-4" />}
        title="Önceki oturumlar"
        actions={
          currentId !== null && (
            <Link to="/rules/assistant" className={buttonClass('ghost', 'xs')}>
              <Plus className="size-3.5" /> Yeni
            </Link>
          )
        }
      />
      {list.isPending ? (
        <div className="flex flex-col gap-2 p-3">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : list.isError ? (
        <p className="px-4 py-3 text-xs text-fg-muted">Oturumlar yüklenemedi: {assistantError(list.error)}</p>
      ) : list.data.length === 0 ? (
        <p className="px-4 py-3 text-xs text-fg-subtle">Henüz oturum yok.</p>
      ) : (
        <ul className="max-h-[420px] divide-y divide-line overflow-y-auto">
          {list.data.map((s) => (
            <li key={s.id}>
              <Link
                to={`/rules/assistant/${s.id}`}
                aria-current={s.id === currentId ? 'page' : undefined}
                className={cn(
                  'flex flex-col gap-1 px-4 py-2.5 transition-colors hover:bg-surface-2',
                  s.id === currentId && 'bg-accent-soft shadow-[inset_3px_0_0_var(--color-accent)]',
                )}
              >
                <span className="flex items-center gap-2">
                  <span className="font-mono text-[11px] text-fg-subtle">#{s.id}</span>
                  <StatusTag status={s.status} />
                  {s.decision && (
                    <span className="flex min-w-0 items-center gap-1 text-[11.5px] text-fg-muted">
                      {s.decision === 'extend' ? <GitMerge className="size-3 shrink-0" /> : <SquarePlus className="size-3 shrink-0" />}
                      <span className="truncate">{s.decision === 'extend' ? (s.target_rule_code ?? 'Genişletme') : 'Yeni kural'}</span>
                    </span>
                  )}
                  <span className="ml-auto shrink-0 text-[11px] text-fg-subtle">{relativeTime(s.created_at)}</span>
                </span>
                <span className="line-clamp-2 text-[12px] text-fg">{s.request?.description ?? '—'}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SessionView({id, onRestart}: {id: number; onRestart: (r: AssistantRequest | null) => void}) {
  const client = useQueryClient();
  const feedback = useFeedback();
  const navigate = useNavigate();
  const session = useQuery({
    queryKey: qk.assistantSession(id),
    queryFn: () => api.assistant.get(id),
    retry: false,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 1500 : false),
  });
  // Keep the "Önceki oturumlar" list in sync when this session changes status.
  const status = session.data?.status;
  useEffect(() => {
    if (status) client.invalidateQueries({queryKey: qk.assistantSessions});
  }, [status, client]);
  const put = (s: AssistantSession) => {
    client.setQueryData(qk.assistantSession(id), s);
    client.invalidateQueries({queryKey: qk.assistantSessions});
  };

  const cancel = useMutation({
    mutationFn: () => api.assistant.cancel(id),
    onSuccess: put,
    onError: (e) => feedback.error('İptal edilemedi', asError(e)),
  });
  const revalidate = useMutation({
    mutationFn: ({proposal, runNoise}: {proposal: RuleInput; runNoise: boolean}) => api.assistant.revalidate(id, proposal, runNoise),
    onSuccess: put,
    onError: (e) => feedback.error('Yeniden doğrulama başlatılamadı', asError(e)),
  });
  const save = useMutation({
    mutationFn: (proposal: RuleInput) => api.assistant.save(id, proposal),
    onSuccess: (res) => {
      put(res.session);
      client.invalidateQueries({queryKey: qk.rules});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success(
        res.session.decision === 'extend' ? 'Kural güncellendi' : 'Kural oluşturuldu',
        `${res.rule.code} · ${res.rule.name} — “Kuralı aç” ile düzenleyebilirsiniz.`,
      );
    },
    onError: (e) =>
      feedback.error(e instanceof ApiError && e.status === 409 ? 'Kod çakışması: bu kodla bir kural zaten var' : 'Kural kaydedilemedi', asError(e)),
  });

  if (session.isPending)
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    );
  if (session.isError)
    return (
      <Card>
        <ErrorState title="Oturum yüklenemedi" error={asError(session.error)} onRetry={() => session.refetch()} />
      </Card>
    );
  const s = session.data;
  const step = wizardStep(s);

  return (
    <div className="flex flex-col gap-4">
      <Card className="px-4 py-3">
        <Stepper steps={STEPS} current={step} maxReachable={step} />
      </Card>
      {step === 2 ? (
        <ProposalStep
          key={`${s.id}-${s.status}-${s.updated_at}`}
          session={s}
          revalidating={revalidate.isPending}
          saving={save.isPending}
          onRevalidate={(proposal, runNoise) => revalidate.mutate({proposal, runNoise})}
          onSave={async (proposal, risky) => {
            if (
              risky &&
              !(await feedback.confirm({
                title: s.validation && !s.validation.passed ? 'Bazı örnekler başarısız, yine de kaydedilsin mi?' : 'Değişiklikler doğrulanmadı, yine de kaydedilsin mi?',
                description:
                  s.decision === 'extend'
                    ? `${s.target_rule_code ?? 'Hedef kural'} bu tanımla güncellenecek.`
                    : 'Kural bu tanımla oluşturulacak; sonradan Kurallar sayfasından düzenleyebilirsiniz.',
                confirmLabel: 'Yine de kaydet',
                tone: 'primary',
              }))
            )
              return;
            save.mutate(proposal);
          }}
          onDiscard={async () => {
            if (
              await feedback.confirm({
                title: 'Öneri kaydedilmeden kapatılsın mı?',
                description: 'Oturum iptal edilir; tanımı daha sonra önceki oturumlardan yeniden başlatabilirsiniz.',
                confirmLabel: 'Vazgeç ve kapat',
              })
            ) {
              api.assistant.cancel(id).catch(() => undefined);
              client.invalidateQueries({queryKey: qk.assistantSessions});
              navigate('/rules');
            }
          }}
        />
      ) : (
        <RunningStep session={s} cancelling={cancel.isPending} onCancel={() => cancel.mutate()} onRestart={() => onRestart(s.request ?? null)} />
      )}
    </div>
  );
}

export function RuleAssistantPage() {
  const {id} = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const client = useQueryClient();
  const sessionId = id ? Number(id) : null;
  const [form, setForm] = useState<AssistantForm>(() => (location.state as {request?: AssistantRequest} | null)?.request ? formFromRequest((location.state as {request: AssistantRequest}).request) : emptyAssistantForm());

  const start = useMutation({
    mutationFn: () => api.assistant.create(buildAssistantRequest(form)),
    onSuccess: (s) => {
      client.setQueryData(qk.assistantSession(s.id), s);
      client.invalidateQueries({queryKey: qk.assistantSessions});
      navigate(`/rules/assistant/${s.id}`);
    },
  });

  const restart = (r: AssistantRequest | null) => {
    setForm(formFromRequest(r));
    start.reset();
    navigate('/rules/assistant', {state: {request: r}});
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow={
          <Link to="/rules" className="inline-flex items-center gap-1 text-xs text-fg-subtle hover:text-fg">
            <ArrowLeft className="size-3.5" /> Kurallar
          </Link>
        }
        title="LLM ile kural oluştur"
        description="Ne denetlenmesini istediğinizi ve birkaç örnek yazın. LLM uygun bir kuralı genişletir ya da yeni kural taslağı hazırlar, örneklerle doğrular; siz onaylamadan hiçbir şey kaydedilmez."
      />
      <div className="grid items-start gap-4 2xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          {sessionId === null ? (
            <div className="flex flex-col gap-4">
              <Card className="px-4 py-3">
                <Stepper steps={STEPS} current={0} maxReachable={0} />
              </Card>
              <DefinitionStep form={form} setForm={setForm} onStart={() => start.mutate()} starting={start.isPending} startError={start.error ? assistantError(start.error) : null} />
            </div>
          ) : Number.isFinite(sessionId) ? (
            <SessionView key={sessionId} id={sessionId} onRestart={restart} />
          ) : (
            <Card>
              <EmptyState icon={<History />} title="Geçersiz oturum" />
            </Card>
          )}
        </div>
        <PreviousSessions currentId={sessionId} />
      </div>
    </div>
  );
}
