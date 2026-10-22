import {useState, type FormEvent} from 'react';
import {Alert} from '@/components/ui/Alert';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {Field} from '@/components/ui/Field';
import {PageHeader} from '@/components/ui/PageHeader';
import {ErrorState, LoadingState} from '@/components/ui/States';
import {useResource} from '@/hooks/useResource';
import {
  MANAGED_BY_DEPLOYMENT,
  RUNTIME_ONLY,
  SQL_ALL_DATABASES,
  SQL_CERTIFICATE_NOT_VERIFIED,
  SQL_ENCRYPTION_FIXED,
  SQL_MANAGED_BY_SUPER_ADMIN,
  SQL_STORED_IN_APPLICATION,
} from '@/lib/connectionText';
import {describeError, messageForCode} from '@/lib/errorMessages';
import {ConnectionService} from '@/services/connections';
import type {SqlConnectionChange, SqlConnectionTestResult, SqlConnectionView} from '@/types/sqlReview';


/**
 * SQL Server connection settings (sql-review sql-server-connection Requirement 3–5, 9, 10).
 * Editable only when the backend says so: the super admin in `local` (this process only), the
 * super admin in a `nonprod` whose deployment supplies no connection (saved in the application).
 * Otherwise a read-only status.
 */
export default function SqlConnectionPage() {
  const view = useResource('sql-connection', (signal) => ConnectionService.sql(signal));
  const [saved, setSaved] = useState(false);
  return (
    <div className="page">
      <PageHeader title="SQL bağlantısı" description="İnceleme sayfasındaki veritabanı ve nesne listeleri bu bağlantıyla okunur." />
      {view.status === 'error' && <ErrorState message={describeError(view.error)} onRetry={view.reload} />}
      {view.status === 'loading' && view.data === undefined && <LoadingState label="Ayarlar yükleniyor…" />}
      {view.data && !view.data.editable && <ReadOnlyStatus view={view.data} />}
      {view.data && view.data.editable && (
        <SqlConnectionForm
          key={JSON.stringify(view.data)}
          view={view.data}
          saved={saved}
          onSaved={(next) => {
            setSaved(true);
            view.replace(next);
          }}
          onReload={() => {
            setSaved(false);
            view.reload();
          }}
        />
      )}
    </div>
  );
}

function ReadOnlyStatus({view}: {view: SqlConnectionView}) {
  return (
    <Card title="Bağlantı durumu">
      <div className="stack">
        <Alert tone="info">
          {view.managed_by === 'super_admin' ? SQL_MANAGED_BY_SUPER_ADMIN : MANAGED_BY_DEPLOYMENT}
        </Alert>
        <dl className="facts">
          <div>
            <dt>Ortam</dt>
            <dd>{view.environment}</dd>
          </div>
          <div>
            <dt>Yapılandırma</dt>
            <dd>{view.configured ? 'Yapılandırılmış' : 'Yapılandırılmamış'}</dd>
          </div>
        </dl>
      </div>
    </Card>
  );
}

function SqlConnectionForm({
  view,
  saved,
  onSaved,
  onReload,
}: {
  view: SqlConnectionView;
  saved: boolean;
  onSaved: (view: SqlConnectionView) => void;
  onReload: () => void;
}) {
  const [server, setServer] = useState(view.server ?? '');
  const [port, setPort] = useState(String(view.port ?? 1433));
  const [user, setUser] = useState(view.user ?? '');
  const [password, setPassword] = useState('');
  const [removePassword, setRemovePassword] = useState(false);
  const [encrypt, setEncrypt] = useState(view.encrypt ?? true);
  const [trust, setTrust] = useState(view.trust_server_certificate ?? false);
  // nonprod: the connection is saved in the application and is always encrypted.
  const stored = view.managed_by === 'super_admin';
  const [busy, setBusy] = useState<'save' | 'test' | null>(null);
  const [notice, setNotice] = useState<{tone: 'success' | 'error'; text: string} | null>(null);
  const [test, setTest] = useState<SqlConnectionTestResult | null>(null);
  const portNumber = Number(port);
  const portValid = Number.isInteger(portNumber) && portNumber >= 1 && portNumber <= 65535;

  function change(): SqlConnectionChange {
    const value: SqlConnectionChange = {
      server: server.trim(),
      port: portNumber,
      user: user.trim(),
      trust_server_certificate: trust,
    };
    // nonprod fixes encryption; only the local environment may send it.
    if (!stored) value.encrypt = encrypt;
    // No password field keeps the stored one; an empty string removes it.
    if (removePassword) value.password = '';
    else if (password !== '') value.password = password;
    return value;
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!portValid) return;
    setBusy('save');
    setNotice(null);
    try {
      const next = await ConnectionService.saveSql(change());
      setPassword('');
      setRemovePassword(false);
      onSaved(next);
    } catch (error) {
      setNotice({tone: 'error', text: describeError(error)});
    } finally {
      setBusy(null);
    }
  }

  async function runTest() {
    if (!portValid) return;
    setBusy('test');
    setNotice(null);
    setTest(null);
    try {
      setTest(await ConnectionService.testSql(change()));
    } catch (error) {
      setNotice({tone: 'error', text: describeError(error)});
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title="Bağlantı ayarları">
      <form className="form-grid" onSubmit={(event) => void save(event)} noValidate>
        <Alert tone="info">{stored ? SQL_STORED_IN_APPLICATION : RUNTIME_ONLY}</Alert>
        {saved && notice === null && test === null && <Alert tone="success">SQL bağlantı ayarları kaydedildi.</Alert>}
        {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
        {test && <TestResult result={test} />}
        <Field id="sql-server" label="Sunucu adı">
          <input
            id="sql-server"
            className="input"
            value={server}
            autoComplete="off"
            spellCheck={false}
            placeholder="sunucu.kurum.local"
            onChange={(event) => setServer(event.target.value)}
          />
        </Field>
        <Field id="sql-port" label="Port" error={portValid ? null : 'Port 1 ile 65535 arasında bir sayı olmalıdır.'}>
          <input
            id="sql-port"
            className="input"
            type="number"
            min={1}
            max={65535}
            value={port}
            aria-invalid={!portValid || undefined}
            onChange={(event) => setPort(event.target.value)}
          />
        </Field>
        <Field id="sql-user" label="Kullanıcı adı">
          <input
            id="sql-user"
            className="input"
            value={user}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setUser(event.target.value)}
          />
        </Field>
        <Field
          id="sql-password"
          label="Parola"
          hint={view.password_set ? 'Kayıtlı parola var. Boş bırakırsanız korunur.' : 'Kayıtlı parola yok.'}
        >
          <input
            id="sql-password"
            className="input"
            type="password"
            value={password}
            autoComplete="new-password"
            disabled={removePassword}
            aria-describedby="sql-password-hint"
            placeholder={view.password_set ? 'Yeni parola yazın' : 'SQL Server giriş parolası'}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>
        {view.password_set && (
          <label className="check">
            <input
              type="checkbox"
              checked={removePassword}
              onChange={(event) => {
                setRemovePassword(event.target.checked);
                if (event.target.checked) setPassword('');
              }}
            />
            <span>Kayıtlı parolayı kaldır</span>
          </label>
        )}
        {stored ? (
          <p className="subtle">{SQL_ENCRYPTION_FIXED}</p>
        ) : (
          <label className="check">
            <input type="checkbox" checked={encrypt} onChange={(event) => setEncrypt(event.target.checked)} />
            <span>Şifreli bağlantı (Encrypt)</span>
          </label>
        )}
        <label className="check">
          <input type="checkbox" checked={trust} onChange={(event) => setTrust(event.target.checked)} />
          <span>Sunucu sertifikasına doğrulamadan güven (TrustServerCertificate)</span>
        </label>
        {stored && trust && (
          <div role="status" aria-label="Sertifika doğrulaması kapalı" className="alert alert-warning">
            {SQL_CERTIFICATE_NOT_VERIFIED}
          </div>
        )}
        <p className="subtle">{SQL_ALL_DATABASES}</p>
        <div className="row">
          <Button type="submit" variant="primary" disabled={busy !== null || !portValid} busy={busy === 'save'}>
            Kaydet
          </Button>
          <Button onClick={() => void runTest()} disabled={busy !== null || !portValid} busy={busy === 'test'}>
            {busy === 'test' ? 'Test ediliyor…' : 'Bağlantıyı test et'}
          </Button>
          <Button variant="ghost" onClick={onReload} disabled={busy !== null}>
            Yenile
          </Button>
        </div>
      </form>
    </Card>
  );
}

function TestResult({result}: {result: SqlConnectionTestResult}) {
  if (!result.ok)
    return <Alert tone="error">{messageForCode(result.code) ?? 'Bağlantı kurulamadı.'}</Alert>;
  const shown = result.databases.slice(0, 8);
  return (
    <Alert tone="success">
      <p>Bağlantı başarılı: {result.databases.length} veritabanı bulundu.</p>
      {shown.length > 0 && (
        <p>
          İlk veritabanları: {shown.join(', ')}
          {result.databases.length > shown.length ? '…' : ''}
        </p>
      )}
    </Alert>
  );
}
