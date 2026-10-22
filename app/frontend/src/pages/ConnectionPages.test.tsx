import {fireEvent, screen, waitFor} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import LlmConnectionPage from './LlmConnectionPage';
import SqlConnectionPage from './SqlConnectionPage';
import {ConnectionService} from '@/services/connections';
import {apiError, renderWithSession} from '@/test/render';
import type {LlmConnectionView, SqlConnectionView} from '@/types/sqlReview';

const sqlLocal: SqlConnectionView = {
  environment: 'local',
  editable: true,
  configured: true,
  managed_by: 'local_process',
  server: 'sql.local',
  port: 1433,
  user: 'reader',
  encrypt: true,
  trust_server_certificate: false,
  password_set: true,
};

// nonprod without a deployment connection: the super admin saves it in the application.
const sqlStored: SqlConnectionView = {
  environment: 'nonprod',
  editable: true,
  configured: true,
  managed_by: 'super_admin',
  server: 'sql-dwh.kurum.local',
  port: 1433,
  user: 'dwh_okuyucu',
  encrypt: true,
  trust_server_certificate: false,
  password_set: true,
};

const llmLocal: LlmConnectionView = {
  environment: 'local',
  editable: true,
  chat_api: 'openai',
  base_url: 'http://10.0.0.5:1234/v1',
  chat_url: null,
  resolved_chat_url: 'http://10.0.0.5:1234/v1/chat/completions',
  model: 'qwen',
  api_key_set: false,
};

describe('SQL connection page', () => {
  it('shows only the deployment note and status when settings are not editable (nonprod)', async () => {
    vi.spyOn(ConnectionService, 'sql').mockResolvedValue({
      environment: 'nonprod',
      editable: false,
      configured: true,
      managed_by: 'deployment',
    });
    renderWithSession(<SqlConnectionPage />, {role: 'super_admin'});
    expect(await screen.findByText('Bu ortamda bağlantı ayarları dağıtımla yönetilir.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Sunucu adı')).toBeNull();
    expect(screen.queryByRole('button', {name: 'Kaydet'})).toBeNull();
  });

  it('tells a rule manager that only the application administrator edits the nonprod connection', async () => {
    vi.spyOn(ConnectionService, 'sql').mockResolvedValue({
      environment: 'nonprod',
      editable: false,
      configured: false,
      managed_by: 'super_admin',
    });
    renderWithSession(<SqlConnectionPage />, {role: 'super_admin'});
    expect(
      await screen.findByText('Bu ortamda SQL bağlantısını yalnız uygulama yöneticisi düzenleyebilir.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Bu ortamda bağlantı ayarları dağıtımla yönetilir.')).toBeNull();
    expect(screen.getByText('Yapılandırılmamış')).toBeInTheDocument();
    expect(screen.queryByLabelText('Sunucu adı')).toBeNull();
    expect(screen.queryByRole('button', {name: 'Kaydet'})).toBeNull();
  });

  it('lets the super admin edit the nonprod connection without any database list, with encryption fixed', async () => {
    vi.spyOn(ConnectionService, 'sql').mockResolvedValue(sqlStored);
    const saveSql = vi.spyOn(ConnectionService, 'saveSql').mockResolvedValue({...sqlStored, port: 1444});
    renderWithSession(<SqlConnectionPage />, {role: 'super_admin'});
    expect(await screen.findByText(/parola şifrelenerek saklanır/)).toBeInTheDocument();
    expect(screen.queryByText(/yalnız çalışan sunucu sürecine uygulanır/)).toBeNull();
    expect(screen.queryByLabelText('Şifreli bağlantı (Encrypt)')).toBeNull();
    expect(screen.getByText('Bu ortamda bağlantı her zaman şifrelidir; bu ayar değiştirilemez.')).toBeInTheDocument();
    // The account's own permissions decide what can be reviewed; there is nothing to list here.
    expect(screen.queryByLabelText('İzinli veritabanları')).toBeNull();
    expect(screen.queryByText(/İzinli veritabanları/)).toBeNull();
    expect(screen.getByText(/hesabın erişebildiği bütün veritabanları listelenir/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Port'), {target: {value: '1444'}});
    fireEvent.click(screen.getByRole('button', {name: 'Kaydet'}));
    await screen.findByText('SQL bağlantı ayarları kaydedildi.');
    expect(saveSql).toHaveBeenCalledWith({
      server: 'sql-dwh.kurum.local',
      port: 1444,
      user: 'dwh_okuyucu',
      trust_server_certificate: false,
    });
  });

  it('lets the super admin accept an unverified server certificate in nonprod, with a plain warning', async () => {
    vi.spyOn(ConnectionService, 'sql').mockResolvedValue(sqlStored);
    const testSql = vi
      .spyOn(ConnectionService, 'testSql')
      .mockResolvedValue({ok: true, code: null, message: 'ok', databases: ['DWH_Risk', 'DWH_Sales', 'Scratch']});
    const saveSql = vi
      .spyOn(ConnectionService, 'saveSql')
      .mockResolvedValue({...sqlStored, trust_server_certificate: true});
    renderWithSession(<SqlConnectionPage />, {role: 'super_admin'});
    const trust = await screen.findByLabelText('Sunucu sertifikasına doğrulamadan güven (TrustServerCertificate)');
    expect(trust).not.toBeChecked();
    expect(screen.queryByText(/sunucunun kimliği doğrulanmaz/)).toBeNull();

    fireEvent.click(trust);
    expect(screen.getByRole('status', {name: 'Sertifika doğrulaması kapalı'})).toHaveTextContent(
      'Bağlantı yine şifrelidir, ancak sunucunun kimliği doğrulanmaz; ağdaki biri kendini bu sunucu gibi gösterebilir. Bu seçeneği yalnız sunucunun sertifikası kurumun sertifika otoritesiyle imzalı değilse açın ve sunucuya kurum imzalı sertifika kurulunca kapatın.',
    );
    fireEvent.click(screen.getByRole('button', {name: 'Bağlantıyı test et'}));
    expect(await screen.findByText('Bağlantı başarılı: 3 veritabanı bulundu.')).toBeInTheDocument();
    const sent = {server: 'sql-dwh.kurum.local', port: 1433, user: 'dwh_okuyucu', trust_server_certificate: true};
    expect(testSql).toHaveBeenCalledWith(sent);
    fireEvent.click(screen.getByRole('button', {name: 'Kaydet'}));
    await waitFor(() => expect(saveSql).toHaveBeenCalledWith(sent));
    // The saved state comes back checked, with the warning still visible.
    expect(
      await screen.findByLabelText('Sunucu sertifikasına doğrulamadan güven (TrustServerCertificate)'),
    ).toBeChecked();
    expect(screen.getByRole('status', {name: 'Sertifika doğrulaması kapalı'})).toBeInTheDocument();
  });

  it('shows the fixed message when the server refuses a fixed setting', async () => {
    vi.spyOn(ConnectionService, 'sql').mockResolvedValue(sqlStored);
    vi.spyOn(ConnectionService, 'saveSql').mockRejectedValue(apiError(422, 'sql_setting_fixed'));
    renderWithSession(<SqlConnectionPage />, {role: 'super_admin'});
    fireEvent.click(await screen.findByRole('button', {name: 'Kaydet'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Bu ayar bu ortamda değiştirilemez.');
  });

  it('keeps both encryption choices editable in the local environment and shows no database list', async () => {
    vi.spyOn(ConnectionService, 'sql').mockResolvedValue(sqlLocal);
    renderWithSession(<SqlConnectionPage />, {role: 'super_admin'});
    expect(await screen.findByLabelText('Şifreli bağlantı (Encrypt)')).toBeChecked();
    expect(screen.getByLabelText(/TrustServerCertificate/)).not.toBeChecked();
    expect(screen.queryByText(/İzinli veritabanları/)).toBeNull();
  });
});

describe('LLM connection page', () => {
  it('shows format and model read-only when not editable (nonprod)', async () => {
    vi.spyOn(ConnectionService, 'llm').mockResolvedValue({
      environment: 'nonprod',
      editable: false,
      chat_api: 'openai',
      model: '/data/models--Qwen',
    });
    renderWithSession(<LlmConnectionPage />, {role: 'super_admin'});
    expect(await screen.findByText('Bu ortamda bağlantı ayarları dağıtımla yönetilir.')).toBeInTheDocument();
    expect(screen.getByText('/data/models--Qwen')).toBeInTheDocument();
    expect(screen.queryByLabelText('Temel adres')).toBeNull();
  });

  it('saves format, addresses and model; an empty key field keeps the stored key', async () => {
    vi.spyOn(ConnectionService, 'llm').mockResolvedValue(llmLocal);
    const save = vi.spyOn(ConnectionService, 'saveLlm').mockResolvedValue({...llmLocal, model: 'yeni'});
    renderWithSession(<LlmConnectionPage />, {role: 'super_admin'});
    expect(await screen.findByText('http://10.0.0.5:1234/v1/chat/completions')).toBeInTheDocument();
    expect(screen.queryByText(/vekil|proxy/i)).toBeNull();
    fireEvent.change(screen.getByLabelText('Model'), {target: {value: 'yeni'}});
    fireEvent.click(screen.getByRole('button', {name: 'Kaydet'}));
    await screen.findByText('LLM bağlantı ayarları kaydedildi.');
    expect(save).toHaveBeenCalledWith({
      chat_api: 'openai',
      base_url: 'http://10.0.0.5:1234/v1',
      chat_url: '',
      model: 'yeni',
    });
  });

  it('shows the class message when the address is outside the internal network', async () => {
    vi.spyOn(ConnectionService, 'llm').mockResolvedValue(llmLocal);
    vi.spyOn(ConnectionService, 'saveLlm').mockRejectedValue(apiError(422, 'network_policy_denied'));
    renderWithSession(<LlmConnectionPage />, {role: 'super_admin'});
    fireEvent.change(await screen.findByLabelText('Temel adres'), {target: {value: 'https://api.example.com/v1'}});
    fireEvent.click(screen.getByRole('button', {name: 'Kaydet'}));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('LLM adresi kurum içi ağda değil; bu adrese istek gönderilemez.'),
    );
  });
});
