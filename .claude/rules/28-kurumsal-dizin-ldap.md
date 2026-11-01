<!-- kt-scaffold tarafından ÜRETİLDİ. rules/ dizinini düzenleyip yeniden üretin. -->
---
paths:
  - app/backend/**
  - app/infra/**
  - helm/**
  - specs/**/PRDs/**
---

# Kurum dizinine yalnız LDAPS ile, doğrulanan sertifika ve tek bağlanma denemesiyle bağlan

# Kurum dizini (LDAP)

Kurum dizinine (Active Directory) bağlanma sabit profilin isteğe bağlı yeteneğidir
(`technology-profile.yml#corporate_directory`). Yalnız kabul edilmiş `PRD` kurum kimliğiyle giriş,
kullanıcı arama veya dizin eşitlemesi tanımladığında aç: `requirements.in` sonuna
`-r requirements-ldap.in` ekle, `scripts/compile-dependency-locks.sh` ile kilitleri yeniden üret,
`dependency-admission.json` kaydını güncelle. Tek istemci `ldap3`'tür; başka LDAP kitaplığı, kendi
yazılmış protokol kodu ve dizine başka yoldan (HTTP ağ geçidi, betik) erişim kullanılmaz.

## Kurum ortamı

Dizin sunucusu adları, arama tabanı, UPN soneki, servis hesabı ve kurum kök sertifikaları depoda
tutulmaz. Ajan bu değerleri fabrikanın MCP sunucusundaki `kurum_ortami_getir` aracından
(`area: ldap`, kök sertifikalar için `area: kok-sertifikalar`) alır; yerel geliştirmede yalnız Git'in
yok saydığı ortam dosyasına yazar, depoya, `values-project.yaml`'a, PRD'ye veya teste yazmaz. Araç
"yapılandırılmamış" derse değerleri dizin ekibinden yazılı al; uydurma. Dağıtımda
`helm/<ürün-kısa-adı>/values-project.yaml` yalnız `backend.corporateEnvironment.sections` listesine
`ldap` ekler; `deploy.sh` ayar anahtarlarını ve dizin çıkış eşini dağıtım anında kendisi alır
(`45-dagitim-hedefi`). Kurum kök sertifikaları gizli değildir; PEM dosyası imajda taşınabilir.

## Bağlantı ve TLS

- Yalnız LDAPS: `Server(host, port=636, use_ssl=True, tls=..., get_info=NONE, connect_timeout=...)`.
  StartTLS, 389 portu ve şifresiz bağlantıya geri düşme yoktur.
- `Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=<kurum kökleri PEM>, version=ssl.PROTOCOL_TLS_CLIENT,
  valid_names=[host])` kullan. Doğrulamayı kapatan ayar (`CERT_NONE`, `validate=False`) üretim
  kodunda bulunmaz. Kurum CA'sını bağlantıya doğrudan ver; süreç genelindeki güven deposunu
  (`SSL_CERT_FILE`) değiştirme.
- Sunucu adı IP değil, sertifikadaki ada uyan tam alan adıdır (FQDN); şema veya port içermez.
- Dizin sunucusunun sertifikası zayıf anahtarlı olduğu için el sıkışma `EE certificate key too weak`
  ile düşerse yalnız açık bir ayarla (`<ENV_PREFIX>LDAP_TLS_WEAK_SERVER_KEY_ALLOWED=true`)
  `ciphers=ssl._DEFAULT_CIPHERS + ":@SECLEVEL=1"` ver; CA ve ad doğrulaması açık kalır, varsayılan
  kapalıdır.
- `Connection(..., receive_timeout=..., auto_referrals=False, raise_exceptions=True)`: referans
  izlenmez. Bağlanma zaman aşımı (ör. 5 sn) ve okuma zaman aşımı (ör. 10 sn) sınırlıdır ve üst
  sınırla doğrulanır; tam eşitleme daha uzun okuma süresi isteyebilir.
- `ldap3` eşzamanlıdır. Bağlan, işle ve `unbind()` adımlarının tamamını tek bir
  `asyncio.to_thread` çağrısında yürüt; bağlantıyı iş parçacıkları veya istekler arasında paylaşma,
  havuz kurma.
- Bağlanma ve okuma yeniden denenmez, başka sunucuya geçilmez: yeniden deneme hesap kilitlenmesini
  çoğaltır. Eşitleme yalnız ilk sunucuyu kullanır.

## Giriş

- Kullanıcı girdisini tek bir UPN biçimine normalleştir: NFKC, kırp; boşluk, denetim karakteri, `\`,
  `/` ve birden fazla `@` reddedilir; sonek verilmişse yapılandırılan UPN sonekine eşit olmalı,
  verilmemişse eklenir; hesap kısmı küçük harfe çevrilir; uzunluk sınırları (ör. 120/254) uygulanır.
  Başka biçim türetilip denenmez.
- Parolayı kullanıcının UPN'iyle tek bir basit bağlanmayla (simple bind) doğrula. Parola alanı
  boş olamaz (anonim bağlanmayı önler). Bağlanma reddi kimlik reddidir; tanı metninde `data 533`
  devre dışı hesaptır.
- Bağlandıktan sonra aynı bağlantıda kullanıcıyı UPN ile yeniden ara ve tam bir kayıt iste; hesabın
  insan hesabı, etkin ve silinmemiş olduğunu denetle ve dizindeki UPN'i girilenle sabit zamanlı
  karşılaştır (`hmac.compare_digest`).
- Giriş denemesini bağlanmadan önce hız sınırından geçir: kimlik başına ve IP başına sayaç (ör. 900
  sn'de 5 ve 30), anahtarlar HMAC'lı; sınır deposu erişilemezse giriş kapalı başarısız olur (`503`).
- Uygulamanın yerel hesapları varsa önce yerel hesap denenir; yerel hata dizine düşmez.
- Servis hesabı UPN ile bağlanır; parolası yalnız önceden oluşturulmuş `Secret`'tan gelir.

## Arama

- Süzgece giren her kullanıcı değerini `ldap3.utils.conv.escape_filter_chars` ile kaçır; GUID'i
  `objectGUID.bytes_le` baytlarının her birini `\xx` olarak kaçırarak ver.
- Giriş süzgeci yalnız etkin insan hesaplarını seçer: `objectCategory=person`, `objectClass=user`;
  bilgisayar, `msDS-ManagedServiceAccount` ve `msDS-GroupManagedServiceAccount` hariç;
  `userAccountControl:1.2.840.113556.1.4.803:=2` hariç.
- Yalnız gereken öznitelikleri iste (ör. `objectGUID`, `distinguishedName`, `userPrincipalName`,
  `sAMAccountName`, `mail`, `displayName`, `memberOf`, `objectSid`, `primaryGroupID`,
  `userAccountControl`, `whenChanged`, `uSNChanged`).
- Kararlı kimlik `objectGUID`'dir (`UUID(bytes_le=...)`); UPN, posta ve DN değişebilir.
- Çok sonuçlu aramada sayfalı sonuç denetimini (`1.2.840.113556.1.4.319`, ör. sayfa 500, en çok
  1000) kullan ve toplam tavan koy; tavan aşılırsa hiçbir sonuç kullanılmaz. Tek nesne aramasında
  `size_limit=2` ver ve tam bir sonuç iste.
- Grup üyeliğini `memberOf` ve birincil gruptan (kullanıcı SID'inin alan kısmı + `primaryGroupID`)
  başlat; iç içe grupları sınırlı genişlikte ve derinlikte (ör. kişi başına 500 grup, derinlik 8)
  dolaş. `memberOf;range=` yanıtı eksik okumadır, sonuç kullanılmaz. Grup tavanı kişi başınadır,
  paylaşılan önbelleğe uygulanmaz.

## Eşitleme

Dizin eşitlemesi gerekiyorsa:

- Artımlı ve tam tur ayrı zamanlanmış işlerdir; her tur PostgreSQL danışma kilidiyle
  (`pg_try_advisory_lock`) tek yürütücüyle çalışır, kilit tutuluyorsa tur atlanır.
- Artımlı tur `uSNChanged` damgasıyla, sunucunun `highestCommittedUSN` ve `invocationId`
  değerleriyle ilerler; `invocationId` değişirse tur kısmi sayılır. Başarısız veya kısmi tur damgayı
  ilerletmez.
- Eşitleme süzgeci `userPrincipalName=*` ve `displayName=*` ister; bilgisayarları, yönetilen
  hizmet hesaplarını ve `servicePrincipalName` taşıyan hesapları dışlar.
- Devre dışı veya silinmiş hesap hemen pasifleşir; yokluk yalnız tam turda ve art arda iki tam turla
  kesinleşir. Grup üyeliği kapanmadan önce bekleme süresinden geçer. Pasifleşen kaydın profil
  alanları temizlenir.

## Hata, log ve işletim

- Hataları sabit kodlara eşle: `directory_transport_failed`, `directory_bind_failed`,
  `directory_result_incomplete`, `directory_result_limit`, `directory_required_attribute_missing`.
  Tanınmayan hata `directory_transport_failed` sayılır. TLS hatalarını OpenSSL doğrulama koduna göre
  ayır (ad uyuşmazlığı, süresi dolmuş, henüz geçerli değil, CA doğrulanamadı); istisna metni dışarı
  çıkmaz.
- HTTP eşlemesi: kimlik reddi veya insan olmayan hesap `401`, dizin okuma veya taşıma hatası `503`,
  hız sınırı `429` ve `Retry-After`.
- Loga ve denetim kaydına UPN, DN, grup listesi, GUID, parola veya sertifika gövdesi yazılmaz;
  kimlik yalnız HMAC'lı tutulur. Ölçü etiketleri sabit kümelerden gelir
  (`25-backend-gozlemlenebilirligi`).
- Yöneticiye uygulamanın çalıştığı ortamın içinden koşan bir bağlantı testi ver (TLS ve servis
  hesabıyla bağlanma); sonuç alt sebebiyle döner, değer göstermez.

## Ayarlar ve dağıtım

Ayarlar `22-backend-yapilandirmasi` kuralına göre tipli ayarlar nesnesinden ve projenin ön ekiyle
okunur, açılışta doğrulanır: `<ENV_PREFIX>LDAP_ENABLED` (varsayılan kapalı),
`<ENV_PREFIX>LDAP_HOSTS` (virgülle ayrılmış FQDN), `<ENV_PREFIX>LDAP_PORT`,
`<ENV_PREFIX>LDAP_BASE_DN`, `<ENV_PREFIX>LDAP_UPN_SUFFIX`, `<ENV_PREFIX>LDAP_SERVICE_BIND_UPN`,
`<ENV_PREFIX>LDAP_SERVICE_PASSWORD` (yalnız `Secret`), `<ENV_PREFIX>LDAP_NETBIOS_DOMAIN`,
`<ENV_PREFIX>LDAP_DISCOVERY_BASE_DN`, `<ENV_PREFIX>LDAP_TLS_WEAK_SERVER_KEY_ALLOWED`,
`<ENV_PREFIX>LDAP_CA_BUNDLE`, bağlanma ve okuma zaman aşımları, sayfa boyutu, sonuç ve grup
tavanları ve giriş hız sınırları. Özellik açıkken sunucu, arama tabanı, UPN soneki ve okunabilir CA
dosyası zorunludur; servis hesabı UPN'i ile parolası birlikte verilir ya da hiç verilmez. Adres ve
hesap anahtarlarını `deploy.sh` dağıtım anında kurum ortamından üretir; gizli olmayan diğer ayarlar
`backend.config` altında, parola `backend.existingSecret` içinde durur. Dizine çıkış `636/TCP` ile
ve yalnız dağıtım anında gelen `corporateEgress` eşiyle açılır; `NetworkPolicy` alan adı tanımaz,
TLS yine adı doğrular. Helm bayraklarını `--set` ile ver, `--set-string` kullanma.

Yerel geliştirmede vekil sunucu (`HTTPS_PROXY`) LDAPS'i taşımaz; dizine ulaşılamıyorsa sahte dizinle
çalış.

## Doğrulama

`Tls`, `Server` ve `Connection`'ı enjekte edilebilir yap ve birim testlerini sahte sınıflarla yaz;
gerçek dizine çıkan test birim paketinde yer almaz ve gerçek hesaplarla yanlış parola denenmez
(hesap kilitlenir). Zorunlu senaryolar: TLS ayarları ve tek bağlanma; `auto_referrals=False`;
işin `to_thread` içinde yürümesi; süzgeç ve GUID kaçırma; `memberOf;range=` reddi; grup ve derinlik
tavanları; birincil grubun SID ile bulunması; kısmi sonucun kullanılmaması; hız sınırında bağlanma
yapılmaması; yeniden deneme olmaması; HMAC'lı denetim kaydı; yerel hesap önceliği; devre dışı
hesabın reddi. Uçtan uca denemede test CA'sı ve kendi sertifikasıyla çalışan sahte bir AD (ör.
Samba AD DC kapsayıcısı) kullan; ad uyuşmazlığı ve güvenilmeyen CA ile bağlantının reddedildiğini ve
sayfalı tam eşitlemeyi sına; üretim kaynağında `CERT_NONE`, `validate=False`, `use_ssl=False`,
`start_tls` ve `auto_referrals=True` bulunmadığını kaynak tarayan bir testle doğrula.
