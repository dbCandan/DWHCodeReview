import {useState, type FormEvent} from 'react';
import {Navigate, useLocation, useNavigate} from 'react-router';
import {LoginShowcase} from '@/components/auth/LoginShowcase';
import {BrandMark} from '@/components/brand/BrandMark';
import {Backdrop} from '@/components/layout/Backdrop';
import {Alert} from '@/components/ui/Alert';
import {Button} from '@/components/ui/Button';
import {Field} from '@/components/ui/Field';
import {Icon} from '@/components/ui/Icon';
import {useAuth} from '@/contexts/AuthContext';
import {useIntl} from '@/contexts/IntlContext';
import {ApiError} from '@/lib/apiClient';
import {config} from '@/lib/config';

/** Stable catalog key for each login failure the backend distinguishes. */
function loginErrorKey(error: unknown): string {
  // A wrong user name and a wrong password get the same message (directory-login Requirement 13).
  if (error instanceof ApiError && error.status === 401) return 'auth.login.invalidCredentials';
  if (error instanceof ApiError && error.status === 429) return 'auth.login.tooManyAttempts';
  if (error instanceof ApiError && error.code === 'user_inactive') return 'auth.login.inactive';
  if (error instanceof ApiError && error.code === 'identity_conflict') return 'auth.login.identityConflict';
  if (error instanceof ApiError && error.code === 'directory_unavailable')
    return 'auth.login.directoryUnavailable';
  return 'auth.login.unavailable';
}

function languageName(locale: string): string {
  try {
    return new Intl.DisplayNames([locale], {type: 'language'}).of(locale) ?? locale;
  } catch {
    return locale;
  }
}

/**
 * Sign-in screen (directory-login Requirement 13): the form, its hints and the language choice on
 * one half, the product showcase on the other. An open session skips straight to its target page.
 */
export default function LoginPage() {
  const {user, login} = useAuth();
  const {locale, locales, setLocale, t} = useIntl();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as {from?: unknown} | null)?.from;
  const target = typeof from === 'string' && from.startsWith('/') && !from.startsWith('//') && from !== '/login' ? from : '/';
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={target} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setErrorKey(null);
    try {
      await login(username, password);
      navigate(target, {replace: true});
    } catch (error) {
      setErrorKey(loginErrorKey(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-shell">
      <Backdrop />
      <div className="login-panel">
        <header className="login-header">
          <div className="login-brand">
            <BrandMark />
            <span>{config.productName}</span>
          </div>
          {locales.length > 1 && (
            <div className="login-language">
              <label htmlFor="language">{t('common.language.label')}</label>
              <select id="language" className="select" value={locale} onChange={(e) => setLocale(e.target.value)}>
                {locales.map((option) => (
                  <option key={option} value={option} lang={option}>
                    {languageName(option)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </header>

        <div className="login-body">
          <section className="login-form-block" aria-labelledby="login-title">
            <div className="login-intro">
              <p className="login-eyebrow">
                <Icon name="building" />
                {t('auth.login.eyebrow')}
              </p>
              <h1 id="login-title">{t('auth.login.title')}</h1>
              <p>{t('auth.login.subtitle')}</p>
            </div>

            <form className="login-form" onSubmit={submit}>
              {errorKey && <Alert tone="error">{t(errorKey)}</Alert>}
              <Field id="username" label={t('auth.login.username')} hint={t('auth.login.usernameHint')}>
                <input
                  id="username"
                  className="input"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  aria-describedby="username-hint"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </Field>
              <Field id="password" label={t('auth.login.password')}>
                <input
                  id="password"
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
              <Button type="submit" variant="primary" className="login-submit" disabled={busy} busy={busy}>
                {busy ? t('auth.login.busy') : t('auth.login.submit')}
                {!busy && <Icon name="arrowRight" />}
              </Button>
            </form>

            <div className="login-help">
              <p>{t('auth.login.help.suffix')}</p>
              <p>{t('auth.login.help.firstLogin')}</p>
              <p>{t('auth.login.help.localAccount')}</p>
            </div>
          </section>
        </div>
      </div>

      <LoginShowcase />
    </main>
  );
}
