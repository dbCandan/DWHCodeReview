# Görevler — directory-login

[Plan](plan.md) belgesinden türetildi. Kanıt: `scripts/quality-gate.sh all` 2026-09-27'de yerel
Compose yığınında geçti (arka uç 638/638, ön yüz 130/130 test; göç, OpenAPI, üretilmiş tip,
yönetişim sapması ve chart adımları dahil). Bu, arka uç ve ön yüz için L1 (otomatik testlerden
geçti) kanıtıdır. Yerel tarayıcı kanıtı (L2, gerçek istemcide gözlem) Task 11'dedir.

- [x] Task 1 — Requirement 3, 6, 7, 9, 10, 11 / Acceptance 1: tipli ayarlar (ortam eşlemesi,
  dizin, oturum süreleri, güvenilen giriş denetleyicisi, uygulama adresi), `.env.example` ve yerel
  Compose ortamı. Kanıt: `tests/unit/test_config.py`, `python3 scripts/check-config-sync.py`.
- [x] Task 2 — Requirement 3, 4, 5, 7 ve "Veri ve geçiş" / Acceptance 1: `app_user` genişletmesi,
  `auth_refresh_session`, `app_user_change`, `platform` kiracısı ve iki rolün tohumlanması; göç
  `202609260001`. Kanıt: `tests/integration/test_data_model.py`, `scripts/db.sh validate`.
- [x] Task 3 — Requirement 1, 2, 10 / Acceptance 1: UPN normalleştirme, LDAPS yalnız-giriş
  uyarlayıcısı (CA ve sunucu adı doğrulaması, yönlendirme yok, 5/10 saniye), sürümlenmiş CA bundle'ı.
  Kanıt: `tests/unit/test_directory_identity.py`, `tests/unit/test_ldap_login_client.py`,
  `tests/unit/test_directory_ca_bundle.py`.
- [x] Task 4 — Requirement 1–4, 9, 11, 12 / Acceptance 1: giriş hizmeti ve `POST /auth/login`
  (yerel/dizin ayrımı, `nonprod` yerel giriş sınırı, ilk girişte kayıt, 401/403/409/429/503, hız
  sınırı, denetim olayları, statik anahtar başlıklarının anlamsızlığı). Kanıt:
  `tests/integration/test_directory_login.py`, `tests/unit/test_login_throttle.py`,
  `tests/unit/test_api_baseline.py`.
- [x] Task 5 — Requirement 6, 7, 8 / Acceptance 1: 15 dakikalık ES256 belirteç, dönen yenileme
  oturumu, tekrar kullanım tespiti, `Origin` denetimi, `POST /auth/refresh`, `POST /auth/logout`,
  7 günlük temizlik. Kanıt: `tests/integration/test_directory_login.py`,
  `tests/unit/test_security.py`.
- [x] Task 6 — Requirement 5, 12 / Acceptance 1: `GET /admin/users`, rol ve durum uçları,
  değişiklik kaydı tablosu, oturum kapatma, çağıranın veritabanından yeniden okunması. Kanıt:
  `tests/integration/test_user_administration.py`, `tests/unit/test_rbac.py`.
- [x] Task 7 — Requirement 11, Decision 9 / Acceptance 1: `scripts/create-local-user.sh --role <rol>`
  yalnız dizin kapalıyken ve `local` ortamda çalışır. Kanıt:
  `tests/integration/test_user_administration.py` (dizin açık ve `nonprod` redleri, tekrar
  çalıştırmada aynı sonuç).
- [x] Task 8 — Requirement 2 / Acceptance 1: `ldap3==2.9.1` bağımlılık kabulü ve özetle kilitli
  gereksinim dosyaları. Kanıt: `python3 scripts/check-dependency-admission.py`,
  `dependency-admission.json` karar kaydı.
- [x] Task 9 — API sözleşmesi / Acceptance 1: `specs/openapi/dwhcodereview-api.yaml` ve üretilmiş ön
  yüz tipleri; dışa aktarım yalnız üretilmiş `title` ve `operationId` anahtarlarını düşürür, `title`
  adlı alanı korur. Kanıt: `tests/unit/test_openapi_export.py`, `scripts/export-openapi.sh --check`,
  `scripts/generate-types.sh --check`.
- [x] Task 10 — Requirement 6 (belleğe alınan belirteç), 13 / Acceptance 1, Acceptance 2: giriş
  ekranı, sessiz yenileme, çıkış, oturum bitince girişe dönüş, süper yönetici kullanıcı yönetimi
  ekranı, Vitest testleri ve tarayıcı senaryosu. Kanıt: `app/frontend/src/lib/authStorage.test.ts`,
  `app/frontend/src/lib/apiClient.test.ts` (reddedilen belirteçte tek ortak yenileme ve yeniden
  deneme, yenileme bitince oturumun kapanması, ilgisiz hatalarda korunması),
  `app/frontend/src/contexts/AuthContext.test.tsx`, `app/frontend/src/pages/LoginPage.test.tsx`,
  `app/frontend/src/components/layout/AppShell.test.tsx`,
  `app/frontend/src/pages/UserAdministrationPage.test.tsx`, `e2e/auth/01-super-admin-login.mjs`.
  Giriş ekranı iki bölümlüdür: solda form ve giriş notları (kurum soneki, ilk girişte `inceleyici`
  rolü, yerel yönetici hesabı), geniş ekranda sağda kabul edilmiş PRD'lerdeki yetenekleri anlatan
  tanıtım paneli; davranış ve iletiler Requirement 13 ile aynıdır. Kanıt:
  `app/frontend/src/pages/LoginPage.test.tsx` (`pairs the sign-in form with a panel naming what the
  product does`).
- [x] Task 11 — Requirement 3, 5–8, 11, 13 / Acceptance 2: yerel Compose'da tarayıcıyla L2
  doğrulaması. 2026-09-26'da `scripts/create-local-user.sh` ile açılan yerel hesaplarla (dizin
  kapalı) Chromium'da gözlendi: `e2e/auth/01-super-admin-login.mjs` (belirteç tarayıcı deposunda
  yok, `HttpOnly` çerez, başka kökenden yenileme 403, yeniden yüklemede çerezle oturum, çıkıştan sonra
  yenileme 401), `e2e/sql-review/01-rules-and-roles.mjs` (inceleyici kural ekranını açamaz, taslak
  ucundan 403), `e2e/sql-review/03-settings-objects-users.mjs` (süper yönetici rol ve durum değiştirir,
  rol değişince kullanıcının yenilemesi 401, pasif hesap girişte reddedilir). Ayrıca inceleyici
  oturumu 16 dakika boşta bekletilip geçmiş sayfası açıldı: süresi dolan belirteç 401 aldı, sayfa bir
  kez `POST /auth/refresh` (200) yapıp isteği yineledi (200) ve giriş ekranına dönmedi (tek seferlik
  yerel tarayıcı betiği; kalıcı senaryoda değil).
- [ ] Task 12 — Requirement 1–4, 9, 10 / Acceptance 3: `nonprod` kümede gerçek Active Directory ile
  L2 doğrulaması; CA bundle'ının imaja, dizin ayarlarının değer katmanına girmesi ve LDAPS çıkış
  kuralı [kubernetes-delivery](../002-kubernetes-delivery/PRD.md) görevleriyle birlikte.

- [x] Task 13 — Gözlemlenebilirlik: OpenTelemetry altyapısı (tipli `DWHCODEREVIEW_OTEL_*`
  ayarları, boş adreste dışa aktarım yok, `OTEL_*` süreç değişkeninde başlangıç reddi, `nonprod`'da
  yalnız `https`, gözlemlenebilirlik Compose katmanında yerel toplayıcı), istek başına sunucu izi,
  PostgreSQL komut izleri (yalnız komut türü), istek logunda `trace_id`, giriş sonuçları ölçümü
  `dwhcodereview_auth_login_attempts_total{outcome}`; OpenTelemetry paketlerinin bağımlılık kabulü.
  Sunucu izinin adı ve istek logunun `http_route` alanı, bütün yönlendirici önekleriyle tam rota
  şablonunu taşır (`POST /api/dwhcodereview/v1/auth/login`); somut yol değeri hiçbirine girmez.
  Kanıt: `tests/unit/test_telemetry.py`
  (`test_server_spans_and_logs_name_the_full_template_behind_router_prefixes`),
  `tests/unit/test_request_logging.py`, `tests/unit/test_config.py`,
  `tests/unit/test_integration_settings.py`, `tests/integration/test_telemetry_signals.py`
  (`test_login_outcomes_are_counted_without_names_or_passwords`),
  `python3 scripts/check-dependency-admission.py`, `python3 scripts/check-config-sync.py`,
  `scripts/quality-gate.sh all`. Yerel gözlemlenebilirlik yığınında giriş ölçümü Prometheus'ta, aynı isteğin izi
  Tempo'da ve iz kimliği istek logunda gözlendi; bu, yerel ortam gözlemidir, `nonprod` kanıtı değildir.

- [ ] Task 14 — Riskler (dizindeki her hesabın girebilmesi): girişi sahibin adını vereceği Active
  Directory grubuna sınırla. Grup üyeliği kullanıcının kendi kaydından okunur; grupta olmayan hesap
  403 alır, servis hesapları girişte reddedilir. Sahip kararı bekliyor (grup adı ve nonprod/yerel
  ayrımı); karar gelince bu PRD Requirement ve Acceptance ile revize edilip yeniden kabul edilir.

- [x] Task 15 — Requirement 14, Decision 13 / Acceptance 1: backend açılışında süper yöneticinin
  bir kez açılması; komutla ortak açma yolu, danışma kilidi, değişiklik kaydı satırı, arka planda
  artan aralıkla yeniden deneme, komutun parolayı yalnız istemden veya standart girdiden okuması;
  `values-project.yaml`'da `DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_USERNAME: admin`. Kanıt:
  `tests/unit/test_super_admin_bootstrap.py` (ayar yokken veritabanına gidilmemesi, 2–60 saniyelik
  yeniden deneme, kesin retlerin yeniden denenmemesi, komutun başlangıç parolasını kullanmaması,
  açılışın arka planda koşup kapanışta durması), `tests/integration/test_super_admin_bootstrap.py`
  (bir kez açılış ve giriş, sonraki açılışın sahibin değiştirdiği parolayı korması, adı taşıyan
  başka hesaba dokunulmaması, zayıf parolada hesap açılmaması ve parolanın loga düşmemesi, e-posta
  çakışması, dört eşzamanlı açılışta tek hesap, veritabanı gelene kadar yeniden deneme). Danışma
  kilidi kaldırılınca eşzamanlılık testi, açılış var olan hesabı sıfırlayınca iki koruma testi
  kırmızıya döndü. 2026-09-27 yerel gözlem (küme değil): boş veritabanına bağlanan gerçek backend
  süreci şema yokken 2, 4, 8 saniye arayla yeniden denedi, `alembic upgrade head` sonrası `admin`
  hesabını açtı (`created`), giriş 200 ve `is_super_admin: true`, yanlış parola 401; ikinci açılış
  `exists` yazdı; süreç ve göç loglarında parola yoktu.
- [ ] Task 16 — Requirement 14, Decision 13 / Acceptance 4: nonprod kümede sahibin
  `DWHCODEREVIEW_ADMIN_PASSWORD` gizli değişkenini tanımlayıp dağıtım adımının ortamına eşlemesinden
  sonra ilk dağıtımda `admin` girişi ve `created` olayı, sonraki dağıtımda `exists` olayı ve
  değişmeyen parola. Sahibin değişkeni eklemesini ve Azure koşumunu bekliyor.

## 1.3.0 revizyonu (2026-10-15)

- [x] Task 18 — Decision 14: `APPLICATION_ROLES` yalnız `inceleyici`; kural yöneticisine bağlı uçlar
  süper yöneticiye (`require_super_admin`), ortak uçlar `inceleyici`ye bağlandı; rol değiştirme ucu ve
  yayın isteği uçları kaldırıldı; göç `202610150001_single_application_role` ve testi
  `test_single_application_role_migration.py`; ön yüz "Kullanıcı" etiketi, rol seçimi kalktı; e2e 01-04.
