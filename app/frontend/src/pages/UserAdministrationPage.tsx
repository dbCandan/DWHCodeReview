import {useState, type FormEvent} from 'react';
import {Pager} from '@/components/ui/Pager';
import {Alert} from '@/components/ui/Alert';
import {Badge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {Card} from '@/components/ui/Card';
import {PageHeader} from '@/components/ui/PageHeader';
import {EmptyState, ErrorState, LoadingState} from '@/components/ui/States';
import {useAuth} from '@/contexts/AuthContext';
import {useResource} from '@/hooks/useResource';
import {roleLabel} from '@/lib/access';
import {describeError} from '@/lib/errorMessages';
import {formatDateTime} from '@/lib/format';
import {UserAdminService} from '@/services/userAdmin';
import type {UserPage, UserSummary} from '@/types/sqlReview';

const PAGE_SIZE = 50;

/**
 * Super-admin user administration (application-foundation directory-login Requirement 5, 13):
 * list, deactivate or reactivate. Everyone but the super admin is a user (directory-login Decision 14).
 */
export default function UserAdministrationPage() {
  const {user: current} = useAuth();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');
  const [draftQuery, setDraftQuery] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{tone: 'success' | 'error'; text: string} | null>(null);
  const users = useResource(`users:${page}:${query}`, () =>
    UserAdminService.list({page, size: PAGE_SIZE, q: query || undefined}),
  );

  function search(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setQuery(draftQuery.trim());
  }

  function updateRow(data: UserPage, updated: UserSummary) {
    users.replace({...data, items: data.items.map((item) => (item.public_id === updated.public_id ? updated : item))});
  }

  async function changeActive(data: UserPage, target: UserSummary, active: boolean) {
    setBusyId(target.public_id);
    setNotice(null);
    try {
      const result = await UserAdminService.setActive(target, active);
      updateRow(data, {...target, is_active: result.active});
      setNotice({
        tone: 'success',
        text: `${target.username} hesabı ${result.active ? 'etkinleştirildi' : 'pasifleştirildi'}.`,
      });
    } catch (error) {
      setNotice({tone: 'error', text: describeError(error)});
    } finally {
      setBusyId(null);
    }
  }

  const data = users.data;
  return (
    <div className="page">
      <PageHeader
        title="Kullanıcılar"
        description="Kurum hesabıyla ilk kez giren kişi inceleyici olur. Rolü veya durumu değişen kullanıcının açık oturumları kapanır."
      />
      <form className="row" role="search" onSubmit={search}>
        <div className="field grow">
          <label className="field-label" htmlFor="user-search">
            Kullanıcı ara
          </label>
          <input
            id="user-search"
            className="input"
            type="search"
            value={draftQuery}
            placeholder="ad.soyad"
            onChange={(event) => setDraftQuery(event.target.value)}
          />
        </div>
        <Button type="submit" className="push-end">
          Ara
        </Button>
      </form>
      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      {users.status === 'error' && <ErrorState message={describeError(users.error)} onRetry={users.reload} />}
      {users.status === 'loading' && data === undefined && <LoadingState label="Kullanıcılar yükleniyor…" />}
      {data && (
        <Card
          title={`Kullanıcı listesi (${data.total})`}
          footer={<Pager page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />}
          bodyClassName="table-wrap"
        >
          {data.items.length === 0 ? (
            <EmptyState title="Kullanıcı bulunamadı." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Kullanıcı adı</th>
                  <th scope="col">Görünen ad</th>
                  <th scope="col">Hesap türü</th>
                  <th scope="col">Rol</th>
                  <th scope="col">Durum</th>
                  <th scope="col">Son giriş</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => {
                  const own = item.public_id === current?.public_id;
                  const busy = busyId === item.public_id;
                  return (
                    <tr key={item.public_id}>
                      <td className="mono">{item.username}</td>
                      <td>
                        {item.display_name}
                        <div className="subtle">{item.email}</div>
                      </td>
                      <td>{item.account_type === 'directory' ? 'Kurum dizini' : 'Yerel'}</td>
                      <td>
                        {item.is_super_admin ? (
                          <Badge tone="primary">Süper yönetici</Badge>
                        ) : (
                          <Badge tone="neutral">{roleLabel(item.role)}</Badge>
                        )}
                      </td>
                      <td>
                        <div className="row">
                          <Badge tone={item.is_active ? 'success' : 'neutral'}>
                            {item.is_active ? 'Etkin' : 'Pasif'}
                          </Badge>
                          {!item.is_super_admin && !own && (
                            <Button
                              size="sm"
                              variant={item.is_active ? 'danger-outline' : 'secondary'}
                              disabled={busy}
                              busy={busy}
                              aria-label={`${item.username} hesabını ${item.is_active ? 'pasifleştir' : 'etkinleştir'}`}
                              onClick={() => void changeActive(data, item, !item.is_active)}
                            >
                              {item.is_active ? 'Pasifleştir' : 'Etkinleştir'}
                            </Button>
                          )}
                        </div>
                      </td>
                      <td className="nowrap">{formatDateTime(item.last_login_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  );
}
