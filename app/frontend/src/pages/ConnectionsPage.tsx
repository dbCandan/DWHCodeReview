import {useEffect, useState} from 'react';
import {useSearchParams} from 'react-router';
import {useMutation, useQueryClient} from '@tanstack/react-query';
import {CircleCheck, CircleX, Database, KeyRound, Lock, Pencil, PlugZap, Plus, Server, ShieldCheck, Trash2, User} from 'lucide-react';
import {api, errorMessage} from '@/lib/api';
import {qk, useConnections} from '@/hooks/queries';
import {formatDateTime, formatNumber} from '@/lib/format';
import type {Connection, ConnectionInput, ConnectionTestResult} from '@/types';
import {PageHeader} from '@/components/layout/AppShell';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {Badge} from '@/components/ui/Badge';
import {Dialog} from '@/components/ui/Overlay';
import {Field, Input} from '@/components/ui/Input';
import {SwitchRow} from '@/components/ui/Switch';
import {EmptyState, ErrorState, Skeleton} from '@/components/ui/Feedback';
import {useFeedback} from '@/components/ui/Toast';
import {cn} from '@/lib/utils';

export function ConnectionsPage() {
  const query = useConnections();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState<Connection | 'new' | null>(null);
  const feedback = useFeedback();
  const client = useQueryClient();

  useEffect(() => {
    if (params.get('new') === '1') {
      setEditing('new');
      params.delete('new');
      setParams(params, {replace: true});
    }
  }, [params, setParams]);

  const remove = useMutation({
    mutationFn: (id: number) => api.connections.remove(id),
    onSuccess: () => {
      client.invalidateQueries({queryKey: qk.connections});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success('Bağlantı silindi');
    },
    onError: (e) => feedback.error('Bağlantı silinemedi', e),
  });

  const onDelete = async (c: Connection) => {
    const ok = await feedback.confirm({
      title: `“${c.name}” bağlantısı silinsin mi?`,
      description: 'Bu bağlantıyla yapılmış analizler korunur, ancak yeni analizlerde kullanılamaz. Bu işlem geri alınamaz.',
    });
    if (ok) remove.mutate(c.id);
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Bağlantılar"
        description="Analiz edilecek SQL Server örnekleri. Parolalar yalnızca backend tarafında saklanır, asla geri gönderilmez."
        actions={
          <Button data-tour="connections-new" variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>
            Yeni Bağlantı
          </Button>
        }
      />
      {query.isPending ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({length: 3}).map((_, i) => (
            <Skeleton key={i} className="h-48 rounded-xl" />
          ))}
        </div>
      ) : query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      ) : query.data.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Database />}
            title="Henüz bağlantı yok"
            description="Analize başlamak için bir SQL Server bağlantısı ekleyin. Kaydetmeden önce bağlantıyı test edebilirsiniz."
            action={
              <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>
                Bağlantı ekle
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {query.data.map((c) => (
            <ConnectionCard key={c.id} connection={c} onEdit={() => setEditing(c)} onDelete={() => onDelete(c)} />
          ))}
        </div>
      )}
      <ConnectionDialog
        key={editing === 'new' ? 'new' : (editing?.id ?? 'none')}
        open={editing !== null}
        connection={editing === 'new' ? null : editing}
        onClose={() => setEditing(null)}
      />
    </div>
  );
}

function TestResult({result, error}: {result?: ConnectionTestResult; error?: unknown}) {
  if (error) {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-bad/30 bg-bad-soft px-3 py-2 text-xs">
        <CircleX className="mt-px size-3.5 shrink-0 text-bad" />
        <span className="text-fg-muted">{errorMessage(error)}</span>
      </div>
    );
  }
  if (!result) return null;
  return (
    <div
      className={cn(
        'flex animate-fade-in items-start gap-2 rounded-lg border px-3 py-2 text-xs',
        result.ok ? 'border-ok/30 bg-ok-soft' : 'border-bad/30 bg-bad-soft',
      )}
    >
      {result.ok ? <CircleCheck className="mt-px size-3.5 shrink-0 text-ok" /> : <CircleX className="mt-px size-3.5 shrink-0 text-bad" />}
      <div className="min-w-0">
        <p className="font-medium text-fg">{result.ok ? 'Bağlantı başarılı' : 'Bağlantı başarısız'}</p>
        <p className="mt-0.5 break-words text-fg-muted">{result.message}</p>
        {result.ok && (result.server_version || result.database_count !== null) && (
          <p className="mt-1 text-fg-subtle">
            {result.server_version && <span className="line-clamp-1">{result.server_version}</span>}
            {result.database_count !== null && <span className="tnum">{formatNumber(result.database_count)} kullanıcı veritabanı</span>}
          </p>
        )}
      </div>
    </div>
  );
}

function toInput(c: Connection): ConnectionInput {
  return {
    name: c.name,
    server: c.server,
    port: c.port,
    username: c.username,
    password: null,
    encrypt: c.encrypt,
    trust_server_certificate: c.trust_server_certificate,
  };
}

function ConnectionCard({connection: c, onEdit, onDelete}: {connection: Connection; onEdit: () => void; onDelete: () => void}) {
  const test = useMutation({mutationFn: () => api.connections.test({...toInput(c), id: c.id})});
  return (
    <Card className="group flex flex-col transition-colors hover:border-line-strong">
      <div className="flex items-start gap-3 p-4">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-line-strong bg-gradient-to-b from-surface-3 to-surface-2 text-fg-muted">
          <Server className="size-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14px] font-semibold text-fg">{c.name}</h3>
          <p className="truncate font-mono text-[12px] text-fg-muted">
            {c.server}
            <span className="text-fg-subtle">:{c.port}</span>
          </p>
        </div>
        <div className="flex gap-0.5 opacity-70 transition-opacity group-hover:opacity-100">
          <Button variant="ghost" size="sm" iconOnly aria-label="Düzenle" onClick={onEdit}>
            <Pencil className="size-3.5" />
          </Button>
          <Button variant="ghost" size="sm" iconOnly aria-label="Sil" onClick={onDelete} className="hover:text-bad">
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line px-4 py-3 text-xs">
        <div className="flex items-center gap-1.5 text-fg-subtle">
          <User className="size-3.5" />
          <span className="truncate text-fg-muted">{c.username || '—'}</span>
        </div>
        <div className="flex items-center gap-1.5 text-fg-subtle">
          <KeyRound className="size-3.5" />
          <span className="text-fg-muted">{c.has_password ? 'Parola kayıtlı' : 'Parola yok'}</span>
        </div>
        <div className="col-span-2 flex flex-wrap gap-1.5">
          <Badge tone={c.encrypt ? 'ok' : 'neutral'} icon={<Lock className="size-3" />}>
            {c.encrypt ? 'Şifreli' : 'Şifresiz'}
          </Badge>
          {c.trust_server_certificate && (
            <Badge tone="warn" icon={<ShieldCheck className="size-3" />}>
              Sertifikaya güven
            </Badge>
          )}
        </div>
      </dl>
      <div className="mt-auto flex flex-col gap-2 border-t border-line px-4 py-3">
        {(test.data || test.error) && <TestResult result={test.data} error={test.error} />}
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] text-fg-subtle">Güncellendi {formatDateTime(c.updated_at)}</span>
          <Button size="sm" loading={test.isPending} icon={<PlugZap className="size-3.5" />} onClick={() => test.mutate()}>
            Test et
          </Button>
        </div>
      </div>
    </Card>
  );
}

const EMPTY: ConnectionInput = {
  name: '',
  server: '',
  port: 1433,
  username: '',
  password: '',
  encrypt: true,
  trust_server_certificate: true,
};

function ConnectionDialog({open, connection, onClose}: {open: boolean; connection: Connection | null; onClose: () => void}) {
  const [form, setForm] = useState<ConnectionInput>(() => (connection ? toInput(connection) : EMPTY));
  const [touched, setTouched] = useState(false);
  const client = useQueryClient();
  const feedback = useFeedback();
  const set = <K extends keyof ConnectionInput>(key: K, value: ConnectionInput[K]) => setForm((f) => ({...f, [key]: value}));

  const payload = (): ConnectionInput => ({...form, port: Number(form.port) || 1433, password: form.password ? form.password : null});
  const test = useMutation({mutationFn: () => api.connections.test({...payload(), ...(connection ? {id: connection.id} : {})})});
  const save = useMutation({
    mutationFn: () => (connection ? api.connections.update(connection.id, payload()) : api.connections.create(payload())),
    onSuccess: () => {
      client.invalidateQueries({queryKey: qk.connections});
      client.invalidateQueries({queryKey: qk.dashboard});
      feedback.success(connection ? 'Bağlantı güncellendi' : 'Bağlantı eklendi');
      onClose();
    },
  });

  const errors = {
    name: !form.name.trim() ? 'Ad zorunludur' : null,
    server: !form.server.trim() ? 'Sunucu zorunludur' : null,
    username: !form.username.trim() ? 'Kullanıcı adı zorunludur' : null,
    password: !connection && !form.password ? 'Yeni bağlantı için parola zorunludur' : null,
    port: !(Number(form.port) > 0 && Number(form.port) < 65536) ? 'Geçerli bir port girin' : null,
  };
  const invalid = Object.values(errors).some(Boolean);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      icon={<Database className="size-4 text-accent" />}
      title={connection ? 'Bağlantıyı düzenle' : 'Yeni bağlantı'}
      description="SQL Server kimlik doğrulaması (kullanıcı adı / parola) ile bağlanılır."
      footer={
        <>
          <Button
            className="mr-auto"
            loading={test.isPending}
            icon={<PlugZap className="size-3.5" />}
            disabled={!form.server.trim()}
            onClick={() => test.mutate()}
          >
            Bağlantıyı test et
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Vazgeç
          </Button>
          <Button
            variant="primary"
            loading={save.isPending}
            onClick={() => {
              setTouched(true);
              if (!invalid) save.mutate();
            }}
          >
            {connection ? 'Kaydet' : 'Bağlantı ekle'}
          </Button>
        </>
      }
    >
      <form
        className="grid gap-4 sm:grid-cols-6"
        onSubmit={(e) => {
          e.preventDefault();
          setTouched(true);
          if (!invalid) save.mutate();
        }}
      >
        <Field label="Bağlantı adı" required className="sm:col-span-6" error={touched && errors.name}>
          <Input data-autofocus value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Örn. DWH Prod Raporlama" aria-invalid={touched && !!errors.name} />
        </Field>
        <Field label="Sunucu" required className="sm:col-span-4" hint="host, host\instance, host,port veya SQL istemci takma adı (alias)" error={touched && errors.server}>
          <Input mono value={form.server} onChange={(e) => set('server', e.target.value)} placeholder="sqlprod01\DWH" aria-invalid={touched && !!errors.server} />
        </Field>
        <Field label="Port" className="sm:col-span-2" error={touched && errors.port}>
          <Input mono type="number" value={form.port} onChange={(e) => set('port', Number(e.target.value))} aria-invalid={touched && !!errors.port} />
        </Field>
        <Field label="Kullanıcı adı" required className="sm:col-span-3" error={touched && errors.username}>
          <Input value={form.username} onChange={(e) => set('username', e.target.value)} autoComplete="off" aria-invalid={touched && !!errors.username} />
        </Field>
        <Field
          label="Parola"
          required={!connection}
          className="sm:col-span-3"
          hint={connection ? 'Boş bırakılırsa mevcut parola korunur.' : undefined}
          error={touched && errors.password}
        >
          <Input
            type="password"
            value={form.password ?? ''}
            onChange={(e) => set('password', e.target.value)}
            autoComplete="new-password"
            placeholder={connection?.has_password ? '••••••••' : ''}
            aria-invalid={touched && !!errors.password}
          />
        </Field>
        <div className="grid gap-2 sm:col-span-6 sm:grid-cols-2">
          <SwitchRow title="Şifreli bağlantı" description="TLS ile bağlan (Encrypt)" checked={form.encrypt} onChange={(v) => set('encrypt', v)} />
          <SwitchRow
            title="Sunucu sertifikasına güven"
            description="Yerel / kurum içi kullanım için"
            checked={form.trust_server_certificate}
            onChange={(v) => set('trust_server_certificate', v)}
          />
        </div>
        {(test.data || test.error) && (
          <div className="sm:col-span-6">
            <TestResult result={test.data} error={test.error} />
          </div>
        )}
        {save.error && (
          <div className="sm:col-span-6">
            <TestResult error={save.error} />
          </div>
        )}
        <button type="submit" className="hidden" />
      </form>
    </Dialog>
  );
}
