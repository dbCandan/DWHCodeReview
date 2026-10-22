# PRD — directory-login

Status: Accepted

Version: 1.3.0

Acceptance date: 2026-10-15

Domain: [application-foundation](../../DOMAIN.md)

Kabul kaydı: Proje sahibi bu PRD'yi 2026-09-27'de, açık sorulardaki önerileri ve Decision 13'teki
nonprod ilk süper yönetici kararı dahil sahip kararlarını benimseyerek kabul etti. 1.3.0
revizyonunu (Decision 14: tek uygulama rolü) proje sahibi 2026-10-15'te "artık kural yöneticisi diye bir
rol olmamalı; normal kullanıcı ve süper admin olmalı" kararıyla kabul etti.

## Amaç

Kullanıcının kurum Active Directory hesabıyla (kurumun merkezi kullanıcı dizini) giriş yapması ve
`inceleyici` rolüyle (arayüzde "Kullanıcı") yetkilendirilmesi; diğer her yetki süper yöneticidedir
(Decision 14). Dizin girişi LDAPS (dizine
şifreli bağlantı) üzerinden yalnız kullanıcı adı ve parolayı doğrular; kullanıcı eşitleme ve dizinde
arama yoktur. Oturum, iskeletin mevcut JWT (uygulamanın imzaladığı kısa ömürlü oturum belirteci)
yapısı üzerine kurulur; statik API anahtarı koruması kaldırılır.

## Aktörler ve sonuçlar

- **Kullanıcı:** Kurum hesabıyla giriş yapar; ayrı kayıt formu yoktur. İlk girişte kaydı açılır.
- **Uygulama yöneticisi (süper yönetici):** Yerel hesaptır, dizin çalışmasa da girer; rol verir,
  alır ve hesabı pasifleştirir. `nonprod`'da `admin` hesabı dağıtımdan sonra kendiliğinden açılır;
  ilk parolasını proje sahibi seçer (Decision 13).
- **İşletim ekibi:** Dizin ayarlarını ve CA bundle'ını (dizin sunucusunun sertifikasına güvenmek
  için kullanılan kök sertifika dosyası) ortam girdisi olarak sağlar.
- **Geliştirici:** `local` ortamda Active Directory olmadan iki rolü de dener.

Ölçülebilir sonuç: `nonprod`'da geçerli kurum hesabı oturum alır; yanlış parola 401, yetkisiz rol 403
alır; her giriş, çıkış ve rol değişikliği bir denetim olayı üretir.

## Değişmezler ve sınırlar

- Decision 1: Kimlik kaynağı Active Directory'dir; bağlantı yalnız LDAPS (port 636) ve CA ile sunucu
  adı doğrulamasıyla kurulur. Şifresiz LDAP, sertifika doğrulamasını kapatma ve IP adresiyle bağlanma
  yoktur. Sunucu adı sertifikadaki adla eşleşen tam alan adıdır.
- Decision 2: Yalnız giriş (login-only): uygulama kullanıcının kendi bilgileriyle tek bağlanma
  (`bind`) yapar ve yalnız kendi kaydını okur. Servis hesabı, kullanıcı eşitleme, dizinde başkasını
  arama, grup ve yönetici zinciri okuma yoktur.
- Decision 3: Parola uygulamada saklanmaz, loglanmaz, JWT'ye girmez; yalnız o anki doğrulama için
  dizine iletilir. Dizin kullanıcısının kaydında parola özeti bulunmaz.
- Decision 4: (1.3.0 ile Decision 14'e bırakıldı) Roller yalnız `inceleyici` ve `kural-yoneticisi`dir; süper yönetici dışındaki her
  kullanıcının en fazla bir rolü vardır. `kural-yoneticisi`, `inceleyici`nin yapabildiği her şeyi
  yapar. İskeletin `super_admin` rolü uygulama yöneticisine aittir ve bu API ile verilemez.
- Decision 5: Yetki backend sınırında denetlenir. Menü veya düğme gizlemek yetki kontrolü değildir.
  Sağlık uçları (`/liveness`, `/readiness`) dışındaki her API ve SSE (sunucudan tarayıcıya canlı
  olay akışı) isteği geçerli oturum ve uygun rol ister.
- Decision 6: Tüm kullanıcılar iskeletin tek `platform` kiracısındadır. Hangi inceleme veya kural
  ucunun hangi rolü istediği `sql-review` alanının PRD'lerindedir; bu PRD rolleri ve denetimi tanımlar.

## Mevcut davranış

- Kaynak `~/codes/dwhcodereview/backend/main.py` `api_key_guard`: `API_ACCESS_TOKEN` doluysa `/api`
  uçları `X-API-Key`, `API_ADMIN_TOKEN` doluysa `/api/rules`, `/api/llm-config`, `/api/llm-logs`,
  `/api/sql-config` ayrıca `X-Admin-Key` ister. Anahtar herkes için aynıdır; kişi, rol ve giriş
  ekranı yoktur. Aynı katman inceleme uçlarında IP başına hız sınırı uygular.
- Hedef iskelet `app/backend/app/api/auth/`: yerel parola özetiyle `POST /auth/login`, `GET /auth/me`,
  ES256 imzalı 60 dakikalık JWT, `localStorage`'da belirteç; yenileme ve sunucu tarafı çıkış yok.
  `app/backend/app/core/login_throttle.py` ad+adres başına 15 dakikada 5 hatalı denemeyi sınırlar;
  `scripts/create-super-admin.sh` yerel süper yöneticiyi açar; `app_user.password_hash` zorunludur.
- Referans KT Verim `ldap_login_client.py` ve `login_service.py`: tek bağlanmalı LDAPS doğrulaması,
  UPN (kurumsal oturum adı, `ad.soyad@alan`) normalleştirmesi, ilk girişte kayıt açma.

Davranış değişiklikleri: statik anahtar koruması kişi bazlı oturum ve rolle değişir (Requirement
12); `nonprod`'da yerel parolalı giriş yalnız süper yöneticiye açıktır (Requirement 3); belirteç
60 dakikadan 15 dakikaya iner, `localStorage`'dan çıkar, yenileme ve sunucu tarafı çıkış eklenir
(Requirement 6–8); KT Verim'den farklı olarak grup ve yönetici zinciri okunmaz; `nonprod`'da süper
yönetici elle komutla değil, dağıtımdan sonra backend açılışında bir kez açılır (Requirement 14).

## İşlevsel gereksinimler

Requirement 1: `POST /auth/login` kullanıcı adı ve parolayı alır. Kullanıcı adı `ad.soyad` veya
`ad.soyad@<UPN soneki>` biçimindedir; NFKC ile normalleştirilir, küçük harfe çevrilir, sonek yoksa
yapılandırılmış sonek eklenir, farklı sonek reddedilir. Tek bir UPN üretilir; farklı biçimlerle
yeniden deneme yapılmaz. Boş parola dizine hiç gönderilmeden 401 alır (boş parolalı bağlanma
dizinde anonim oturum açabildiği için).

Requirement 2: Dizin doğrulaması tek LDAPS bağlanması ve kullanıcının kendi kaydının tek okunmasıdır:
`objectGUID` (değişmez dizin kimliği), `userPrincipalName`, `displayName`, `mail`,
`userAccountControl`. Yalnız etkin insan hesabı kabul edilir (bilgisayar ve servis hesabı reddedilir).
Bağlantı zaman aşımı 5 saniye, okuma zaman aşımı 10 saniyedir. Dizine ulaşılamazsa, TLS doğrulaması
başarısızsa veya kayıt eksik/çok kayıtlıysa istek 503 `directory_unavailable` ile kapanır; asla
başarılı sayılmaz.

Requirement 3: Hesap türü kaydın kendisinde tutulur: `local` veya `directory`. Adı mevcut bir yerel
hesapla eşleşen giriş yalnız yerel parola ile denetlenir ve dizine gönderilmez; diğer her giriş
dizine gider. `nonprod`'da yerel parolalı giriş yalnız `super_admin` rolündeki hesaba açıktır; diğer
yerel hesaplar 401 alır. Yerel hesap adı UPN sonekini içeremez.

Requirement 4: İlk başarılı dizin girişinde `objectGUID` anahtarlı kullanıcı kaydı açılır: dizin
kimliği, UPN, görünen ad, e-posta (yoksa UPN), hesap türü `directory`, son giriş zamanı. Varsayılan
rol `inceleyici`dir (Decision 7). Sonraki girişlerde görünen ad, e-posta
ve son giriş zamanı güncellenir; kayıt ikinci kez açılmaz. Aynı e-postaya sahip yerel hesap varsa
giriş 409 `identity_conflict` ile reddedilir ve süper yöneticinin çözmesi beklenir.

Requirement 5: Uygulama yöneticisi kullanıcıları sayfalı listeler, süper yönetici dışındaki bir
kullanıcının hesabını pasifleştirir veya yeniden etkinleştirir; seçilecek rol yoktur (Decision 14). Pasif hesap dizin parolası doğru olsa da 403 `user_inactive` alır. Rol veya
durum değişikliği o kullanıcının açık yenileme oturumlarını kapatır (rules/58: yetki değişiminde
oturum yenilenir) ve aynı işlemde PostgreSQL'deki değişiklik kaydı tablosuna (yapan, hedef, değişen
alan, eski ve yeni değer, zaman) yazılır (Decision 10). Süper yönetici hesabının rolü ve durumu bu
uçlarla değiştirilemez.

Requirement 6: Başarılı giriş 15 dakikalık ES256 imzalı erişim belirteci (JWT) döndürür. Belirteç;
kullanıcı kimliği, kiracı, rol, `iss`, `aud`, `iat`, `exp` taşır; parola veya dizin ayrıntısı taşımaz.
Algoritma allowlist'i (izin listesi) yalnız yapılandırılmış algoritmayı kabul eder; `none` ve
algoritma karışıklığı reddedilir. Tarayıcı erişim belirtecini yalnız bellekte tutar; `localStorage`
kullanılmaz.

Requirement 7: Giriş ayrıca CSPRNG (tahmin edilemez rastgele üreteç) ile yenileme belirteci üretir;
PostgreSQL'de yalnız özeti saklanır; `Secure`, `HttpOnly`, `SameSite=Strict` çerezde yalnız
`/api/dwhcodereview/v1/auth` yolunda taşınır. `POST /auth/refresh` her kullanımda belirteci yeniler
ve eskisini geçersiz kılar; rolü veritabanından güncel okur. Boşta kalma 60 dakika, mutlak üst sınır
8 saattir. Kullanılmış belirteç tekrar gelirse o oturum ailesi kapatılır ve denetim olayı yazılır.

Requirement 8: `POST /auth/logout` yenileme oturumunu sunucuda kapatır, çerezi siler ve 204 döner;
süresi dolmuş erişim belirteciyle de çalışır. Çıkıştan sonra aynı yenileme belirteci 401 alır.

Requirement 9: Giriş hız sınırı: aynı normalleştirilmiş kullanıcı adı ve istemci adresi için
15 dakikada 5, aynı istemci adresi için 15 dakikada 30 hatalı deneme. Sınır aşılınca dizine
gidilmeden 429 ve `Retry-After` döner; başarılı giriş kullanıcı sayacını sıfırlar. Uygulama kalıcı
hesap kilidi koymaz (saldırgan başkasının hesabını kilitleyemesin diye). İstemci adresi yalnız
güvenilen giriş denetleyicisinden (ingress) gelen `X-Forwarded-For` ile belirlenir; başka kaynaktan
gelen başlık yok sayılır.

Requirement 10: CA bundle'ı herkese açık kök/ara sertifikadır, özel anahtar içermez; içeriği KT
Verim `helm/kt-verim/certs/nonprod-directory-ca.crt` ile aynıdır ve depoda sürümlenir. Backend onu
ayarla verilen dosya yolundan okur. "Eski TLS uyumluluğu" ayarı (KT Verim nonprod varsayılanı `true`)
yalnız şifre takımı seviyesini düşürür; CA ve sunucu adı doğrulaması her durumda zorunludur.

Requirement 11: Dizin girişi `DWHCODEREVIEW_DIRECTORY_ENABLED` ayarıyla açılır; `local` ortamda
varsayılan kapalıdır. Dizin kapalıyken giriş yalnız yerel hesaplarla yapılır ve geliştirici her iki
rolü, yalnız dizin kapalıyken çalışan `scripts/create-local-user.sh --role <rol>` komutuyla açtığı
yerel test hesaplarıyla dener; yerel sahte AD sunucusu kurulmaz (Decision 9). Dizin açıkken zorunlu
dizin ayarlarından biri eksikse backend başlamaz.

Requirement 12: `X-API-Key` ve `X-Admin-Key` başlıkları hiçbir uçta anlam taşımaz; yalnız bu
başlıkla gelen istek 401 alır. Kaynaktaki "yönetici anahtarı" ile korunan kural ve LLM çağrı özeti
işlemleri süper yöneticiye bağlanır (Decision 14). Durum değiştiren ve kural yayımlayan uçlar rolü
veritabanından güncel okur; diğer uçlar JWT'deki rolü kullanır.

Requirement 13: Ön yüzde giriş ekranı ("Kurum kullanıcı adınız ve parolanız"), çıkış düğmesi, oturum
bitince giriş ekranına dönüş ve yalnız süper yöneticiye görünen kullanıcı yönetimi ekranı bulunur.
Hata iletileri parolanın mı kullanıcı adının mı yanlış olduğunu ayırt etmez.

Requirement 14: Backend her açılışta başlangıç parolası (`DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_PASSWORD`)
doluysa `DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_USERNAME` adındaki hesabı arar; bu adla hiçbir hesap
yoksa onu etkin, yerel ve `super_admin` rollü açar. Açılış `python -m app.scripts.create_super_admin`
komutuyla aynı kod yolunu kullanır: aynı ad kuralı, aynı parola politikası (rules/58: en az 15
karakter, yaygın parola ve hesap adını içeren parola reddi) ve aynı parola özeti. Bu adla bir hesap
varsa (etkin, pasif, silinmiş ya da başka rollü olsa da) hiçbir alanına dokunulmaz; yöneticinin
sonradan değiştirdiği parola, rolü ve durumu yeniden dağıtımda korunur. Parola politikaya uymuyorsa,
ad geçersizse veya e-posta başka hesaptaysa hesap açılmaz; backend çalışmaya devam eder ve yalnız
neden sınıfını loglar. Veritabanı veya şema henüz hazır değilse (ilk kurulumda göç sürerken)
açılışı bekletmeden arka planda 2 saniyeden başlayıp en çok 60 saniyeye çıkan aralıkla yeniden
dener. Aynı anda açılan birden çok backend kopyası tek hesap açar. Hesap açıldığında aynı işlemde
Requirement 5'teki değişiklik kaydı tablosuna bir `role` satırı yazılır (eski değer boş, yeni değer
`super_admin`, yapan açılan hesabın kendisi; işlemi bir kişi değil dağıtım yapar). Başlangıç parolası
boşsa hiçbir şey yapılmaz. Elle çalıştırılan komut parolayı yalnız istemden veya `--password-stdin`
ile okur; kümedeki başlangıç parolasını kullanmaz.

## API sözleşmesi

Taban yol `/api/dwhcodereview/v1`. Hatalar iskeletin tek hata zarfını kullanır:
`{"detail":{"code":"...","message":"..."}}`.

| Uç | Yetki | Başarı | Hatalar |
|---|---|---|---|
| `POST /auth/login` | Herkese açık | 200: `access_token`, `token_type`, `expires_in`, `user`; yenileme çerezi | 401 `invalid_credentials`, 403 `user_inactive`, 409 `identity_conflict`, 429 `rate_limited`, 503 `directory_unavailable` |
| `POST /auth/refresh` | Yenileme çerezi | 200: yeni erişim belirteci; yeni çerez | 401 `session_expired`, 401 `session_revoked` |
| `POST /auth/logout` | Yenileme çerezi | 204; çerez silinir | — (çerez yoksa da 204) |
| `GET /auth/me` | Oturum | 200: kimlik, görünen ad, rol, hesap türü | 401 |
| `GET /admin/users?page=&size=&q=` | `super_admin` | 200: sayfalı liste, UPN'e göre sıralı | 401, 403 |
| `PUT /admin/users/{public_id}/active` | `super_admin` | 200: `{"active":true\|false}` | 400, 403, 404, 409 (kendi hesabı) |

`refresh` ve `logout` çerezle çalıştığından CSRF'e (başka sitenin tarayıcı adına istek göndermesi)
karşı `Origin` başlığı uygulama adresiyle birebir eşleşmelidir. Rol ve durum uçları tekrarlandığında
aynı sonucu verir. `specs/openapi/` bu tabloyla birlikte güncellenir.

## Güvenlik ve yetkilendirme

- LDAP filtre değerleri kaçışlanır (özel karakterler etkisizleştirilir); dizin yönlendirmesi
  (referral) izlenmez; ad ve parola uzunluk sınırı sunucuda uygulanır. Başarısız giriş yanıtı ve
  süresi hesabın var olup olmadığını ele vermez.
- JWT imza anahtarı ve yenileme belirteci özeti yalnız sunucudadır; tarayıcıya, loga, Git'e girmez.
  Anahtarın kaynağı kubernetes-delivery PRD'sindedir.
- `nonprod`'da süper yönetici `admin` hesabını dağıtımdan sonra backend açar (Requirement 14,
  Decision 13). Parolayı proje sahibi seçer ve yalnız Azure gizli değişkeni
  `DWHCODEREVIEW_ADMIN_PASSWORD` ile verir; değer Git'e, değer dosyalarına, komut argümanına, loga,
  iz ve ölçümlere, test verisine girmez; kümeye yalnız runtime Secret üzerinden ulaşır
  ([kubernetes-delivery](../002-kubernetes-delivery/PRD.md) Requirement 5). Parola sıfırlama,
  işletim ekibinin elle çalıştırdığı `python -m app.scripts.create_super_admin --password-stdin`
  komutudur; komut hesap adını aynı `DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_USERNAME` ayarından alır.
  Dağıtım var olan hesabın parolasını değiştirmez.
- Kurumda kapatılan dizin hesabının açık oturumu en geç 8 saatlik mutlak sürede biter; daha erken
  kapatmak için süper yönetici hesabı pasifleştirir.

## Veri ve geçiş

- `app_user`'a hesap türü (`local` | `directory`), benzersiz dizin kimliği (`objectGUID`) ve son
  giriş zamanı eklenir; `password_hash` veritabanı kısıtıyla yalnız yerel hesapta zorunludur.
- Yeni yenileme oturumu tablosu: kullanıcı, oturum ailesi, belirteç özeti, son kullanım, mutlak
  bitiş, kapatılma zamanı ve nedeni. Süresi dolan kayıt 7 gün sonra silinir.
- Yeni değişiklik kaydı tablosu (Requirement 5): yapan, hedef kullanıcı, değişen alan (rol veya
  durum), eski ve yeni değer, zaman. Satırlar yalnız eklenir; uygulamada güncelleme ve silme yolu
  yoktur.
- Alembic göçü (şema değişikliği aracı) iki rolü, izinlerini ve `platform` kiracısını tohumlar;
  böylece süper yönetici oluşturulmadan da dizin girişi çalışır. Kaynakta taşınacak kullanıcı yoktur.
- Süper yönetici açılışı (Requirement 14) yeni tablo veya göç gerektirmez; mevcut `app_user`,
  `app_user_role` ve değişiklik kaydı tablosunu kullanır.

## Gözlemlenebilirlik

Her olay yapılandırılmış JSON log satırıdır; istek kimliği (`x-request-id`) taşır. Parola, JWT,
çerez, yenileme belirteci ve LDAP ham hata metni asla yazılmaz. Başarısız girişte kullanıcı adı yerine
anahtarlı özeti yazılır.

| Olay | Alanlar |
|---|---|
| `auth.login.succeeded` | kullanıcı `public_id`, hesap türü |
| `auth.login.failed` | neden sınıfı (`invalid_credentials`, `account_disabled`, `user_inactive`, `identity_conflict`), ad özeti |
| `auth.login.rate_limited` | ad özeti, sınır türü (kullanıcı/adres) |
| `auth.directory.unavailable` | neden sınıfı (`tls`, `transport`, `timeout`, `incomplete`) |
| `auth.user.created` | kullanıcı `public_id`, atanan rol |
| `auth.session.reuse_detected` | kullanıcı `public_id`, oturum ailesi |
| `auth.logout` | kullanıcı `public_id` |
| `admin.user.role_changed` / `admin.user.active_changed` | yapan, hedef, eski ve yeni değer |
| `auth.super_admin.bootstrap` | sonuç (`created`, `exists`, `rejected`, `not_configured`); `created` ve `exists`te hesap `public_id` ve hesabın `super_admin` olup olmadığı; `rejected`te neden (`password_policy`, `invalid_username`, `invalid_email`, `identity_conflict`) |
| `auth.super_admin.bootstrap_retry` | deneme sırası, hata türü (yalnız sınıf adı), sonraki denemeye kalan saniye |

Ölçüm: giriş denemeleri `dwhcodereview_auth_login_attempts_total{outcome}` ile sayılır; `outcome`
`succeeded`, `invalid_credentials`, `account_disabled`, `user_inactive`, `identity_conflict`,
`rate_limited` veya `directory_unavailable` değerlerinden biridir. Kullanıcı adı, ad özeti ve adres
ölçüme girmez. Her istek, yöntemi, rota şablonu ve yanıt kodu olan bir sunucu iz aralığı üretir ve
istek logu aynı iz kimliğini (`trace_id`) taşır. Ortak kurallar ve saklama süresi
[alan belgesinde](../../DOMAIN.md) tanımlıdır. Tüketen test:
`app/backend/tests/integration/test_telemetry_signals.py`. Rol ve durum değişikliği geçmişi ayrıca
Requirement 5'teki değişiklik kaydı tablosunda kalıcı saklanır (Decision 10).

## Dağıtım etkisi

- Yeni `DWHCODEREVIEW_` önekli ayarlar: dizin açık/kapalı, sunucu, port, temel DN (dizin arama
  kökü), UPN soneki, CA bundle yolu, eski TLS uyumluluğu, zaman aşımları, yerel girişin yalnız süper
  yöneticiye açık olması, oturum süreleri. Hiçbiri sır değildir; login-only kipte servis hesabı
  olmadığından LDAP parolası da yoktur.
- Nonprod değerleri KT Verim `helm/kt-verim/deploy.sh` nonprod varsayılanlarıdır (sunucu, temel DN,
  UPN soneki, CA dosyası, eski TLS `true`, keşif kapalı). Bunların değer katmanına
  (`values-project.yaml`) yazılması, CA dosyasının backend'e ulaştırılması ve LDAPS çıkış kuralı
  kubernetes-delivery PRD'sine aittir.
- Süper yönetici açılışı: `DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_USERNAME` (nonprod `admin`) sır
  değildir ve `values-project.yaml`'dadır; e-posta `DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_EMAIL`
  varsayılanıdır. Başlangıç parolası runtime Secret'ın
  `DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_PASSWORD` anahtarındadır; kaynağı kubernetes-delivery
  PRD'sindedir.
- Kaldırılanlar: `API_ACCESS_TOKEN`, `API_ADMIN_TOKEN` ayarları ve pipeline değişkenleri.

## Test stratejisi

- Birim: UPN normalleştirme, boş parola reddi, hız sınırı sayaçları, JWT allowlist ve `none` reddi,
  yenileme rotasyonu ve tekrar kullanım tespiti.
- Dizin bağdaştırıcısı bir arayüz arkasındadır; sahte dizinle doğru/yanlış parola, kapalı hesap,
  servis/bilgisayar hesabı, eksik `objectGUID`, zaman aşımı ve TLS hatası denenir.
- API: her uçta 401/403/409/429/503 negatif testi; `X-API-Key` ile gelen isteğe 401; `inceleyici`'nin
  kural yayımlayamaması; pasif hesap reddi; rol değişikliğinin oturumu kapatması ve değişiklik kaydı
  tablosuna yazılması; `scripts/create-local-user.sh`'ın dizin açıkken çalışmaması.
- Süper yönetici açılışı (Requirement 14), gerçek PostgreSQL'de: hesabın bir kez açılıp giriş
  yapabilmesi ve tek değişiklik kaydı; var olan hesabın parolasının, rolünün ve durumunun
  değişmemesi; zayıf parolada hesap açılmaması ve parolanın loga düşmemesi; eşzamanlı açılışta tek
  hesap; veritabanına ulaşılamazken artan aralıkla yeniden deneme; ayar boşken veritabanına hiç
  gidilmemesi; elle komutun başlangıç parolasını kullanmaması.
- Ön yüz: giriş, sessiz yenileme, çıkış ve rol tabanlı ekran testleri (Vitest) ve tarayıcı senaryosu.
  Canlı AD yalnız `nonprod`'da doğrulanır; yerel test onun yerine sayılmaz.

## Vektör ve gömme sözleşmesi (uygulanabilirse)

- Sağlayıcı / dağıtım sınırı: Uygulanamaz
- Model kimliği ve değişmez sürüm: Uygulanamaz
- Boyut ve normalleştirme: Uygulanamaz
- Uzaklık metriği ve indeks stratejisi: Uygulanamaz
- Getirim kalitesi/duyarlılık ve gecikme eşikleri: Uygulanamaz
- Kaynak sınıflandırması, en aza indirme ve saklama: Uygulanamaz
- Yeniden gömme, geçiş ve geri alma: Uygulanamaz

## Kabul kriterleri

- [ ] Acceptance 1: L1 — Otomatik testlerden geçti: backend, ön yüz ve göç kapıları; sahte dizinle
  Requirement 1–5 ve 9–12 negatif testleri, Requirement 6–8 oturum testleri ve Requirement 14
  süper yönetici açılışı testleri geçer.
- [ ] Acceptance 2: L2 — Gerçek istemci/ortamda doğrulandı: yerel Compose'da tarayıcıyla yerel test
  hesaplarıyla giriş, 15 dakikalık belirtecin sessiz yenilenmesi, çıkış, `inceleyici`'nin kural
  ekranına erişememesi ve süper yöneticinin rol değiştirmesi gözlenir (Requirement 3, 5–8, 11, 13).
- [ ] Acceptance 3: L2 — Nonprod kümede gerçek Active Directory hesabıyla tarayıcıdan giriş, ilk
  girişte kaydın açılması, yanlış parolada 401, altıncı hatalı denemede 429 ve denetim olaylarının
  logda görünmesi doğrulanır (Requirement 1–4, 9, 10). Bu kanıt yerel kanıttan ayrı raporlanır.
- [ ] Acceptance 4: L2 — Nonprod kümede `DWHCODEREVIEW_ADMIN_PASSWORD` tanımlıyken ilk dağıtımdan
  sonra `admin` hesabıyla tarayıcıdan giriş yapılır ve logda `auth.super_admin.bootstrap` olayı
  `created` görünür; sonraki dağıtımda olay `exists` olur ve hesabın parolası değişmez
  (Requirement 14, Decision 13).

## Kararlar

- Decision 7: İlk girişte herkes `inceleyici` rolünü alır (Requirement 4); bugün uygulama anahtarı
  bilen herkese açıktır ve inceleme zaten tek salt okunur SQL Server hesabıyla yapılır. 1.3.0 ile
  başka rol atanmaz (Decision 14).
- Decision 8: Yerel parolalı giriş `nonprod`'da yalnız süper yöneticiye açıktır (dizin arızasında
  yönetim ve acil erişim için); `local`'de tüm yerel hesaplara açıktır (Requirement 3).
- Decision 9: Geliştirici yerelde iki rolü yalnız dizin kapalıyken çalışan
  `scripts/create-local-user.sh --role <rol>` komutuyla açtığı yerel hesaplarla dener; yerel sahte AD
  sunucusu kurulmaz (Requirement 11).
- Decision 10: Rol ve durum değişiklikleri veritabanında küçük bir değişiklik kaydı tablosunda geçmiş
  olarak saklanır (Requirement 5); `nonprod`'da log saklama süresi güvenceli değildir.
- Decision 11: Oturum süreleri erişim belirteci 15 dakika, yenileme oturumunda boşta kalma 60 dakika ve
  mutlak üst sınır 8 saattir (Requirement 6 ve 7). KT Verim 480 dakikalık tek belirteç kullanır ama
  yenileme ve iptal sunmaz.
- Decision 12: Kaynaktaki inceleme uçlarının hız sınırı korunur ama IP adresine göre değil oturumdaki
  kullanıcıya göre sayılır; sahibi `sql-review` alanının
  [object-review](../../../sql-review/PRDs/003-object-review/PRD.md) (Requirement 18) ve
  [script-review](../../../sql-review/PRDs/004-script-review/PRD.md) (Requirement 10) PRD'leridir.
- Decision 13: Proje sahibinin 2026-09-27 kararı; rules/58'in yönetici hesabı oluşturmanın
  otomatikleşmesi için istediği eylem bazlı açık insan onayı da budur: `nonprod`'da dağıtımdan sonra
  `admin` adlı yerel süper yönetici hesabı bulunur ve işletim ekibinin elle komut çalıştırması
  beklenmez (Requirement 14). Parolayı sahip seçer ve yalnız Azure gizli değişkeniyle verir; değer
  depoda, değer dosyalarında, komut argümanlarında, loglarda ve test verisinde yer almaz. Hesap bir
  kez açılır; sonraki dağıtımlar ona dokunmaz. Açılış her ortamda yalnız başlangıç parolası
  verilince çalışır; yerel test hesapları Decision 9'daki komutla açılmaya devam eder.
- Decision 14: Tek uygulama rolü vardır: `inceleyici` (arayüzde "Kullanıcı"). Kural taslağını
  düzenleme ve yayımlama, SQL Server ve LLM bağlantı ayarları, LLM çağrı özetleri, tüm incelemeleri
  görme, zamanlama ayarı ve kullanıcı yönetimi süper yöneticidedir. Kural ve grup önerileri
  sql-review rule-proposals 2.0.0 Decision 8 ile 2026-10-19'da kaldırıldı. `kural-yoneticisi` rolü 202610150001 göçüyle
  emekliye ayrılır: atamaları `inceleyici` olur, rol ve eski atamalar yumuşak silinir; rol değiştirme
  ucu (`PUT /admin/users/{id}/role`) kaldırılır. Proje sahibinin 2026-10-15 kararı. Gerekçe: iki kademeli
  yetki ve yayın isteği akışı küçük ekip için gereksiz karmaşıklıktır; her yayın tek yetkiliden geçer.

## Teslim akışı

Belirtim → Plan → Görevler → Uygulama

## Riskler

- Active Directory'nin hesap kilitleme eşiği 5 denemeden düşükse yanlış parolalar kurum hesabını
  kilitleyebilir; nonprod eşiği teyit edilmelidir.
- Nonprod dizin sunucusu eski TLS istiyor; bu ayarın üretimde kullanılmaması ayrı karar gerektirir.
- Hız sınırı sayaçları süreç içindedir; backend birden çok kopyaya çıkarsa sınır kopya başına sayılır.
- Dizinde hesabı olan herkes girebilir ve ilk girişte `inceleyici` olur; SPN taşımayan servis
  hesapları da kişi gibi kabul edilir (2026-09-27 yerel sahte dizin gözlemi). Sahip 2026-09-27'de
  bunu şimdilik kabul etti; girişi bir Active Directory grubuna sınırlama açık işi Task 14'tedir.
  Grup denetimi kullanıcının kendi kaydındaki üyelikle yapılabilir, Decision 2'yi aşmaz.
- Süper yönetici parolası kaybolursa rol yönetimi durur; sıfırlama işletim ekibinin küme erişimine
  bağlıdır. Aynı e-postalı yerel ve dizin hesabı çakışması elle çözülür.
- Başlangıç parolası Azure'da ve kümedeki runtime Secret'ta durur. Parola değiştirilmezse bu
  Secret'ı okuyabilen kişi `admin` olarak girebilir; uygulamada parola değiştirme ekranı yoktur,
  değiştirme işletim ekibinin elle komutuyla yapılır.
