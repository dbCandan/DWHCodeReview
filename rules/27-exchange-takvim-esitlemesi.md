---
id: "27-exchange-takvim-esitlemesi"
title: "Takvime yalnız şirket içi Exchange'e EWS ile, tek yönlü ve atomik sahiplenerek yaz"
scope: backend
authority: mandatory
priority: 90
trigger: path-match
applies_to:
  - "app/backend/**"
  - "app/infra/**"
  - "helm/**"
  - "specs/**/PRDs/**"
gate: "governed-review"
application_modes:
  - separated-web
---

# Exchange takvim eşitlemesi

Takvim eşitlemesi sabit profilin isteğe bağlı yeteneğidir (`technology-profile.yml#calendar_sync`).
Yalnız kabul edilmiş `PRD` kayıtların (rezervasyon, randevu, toplantı) Outlook takvimine yazılmasını
tanımladığında aç: `requirements.in` sonuna `-r requirements-calendar.in` ekle,
`scripts/compile-dependency-locks.sh` ile kilitleri yeniden üret, `dependency-admission.json` kaydını
güncelle. Tek istemci `exchangelib`'dir. Şirket içi Exchange için Microsoft Graph, Basic kimlik
doğrulama, etkileşimli giriş ve kapsamsız impersonation kullanılmaz. Posta kutuları Exchange Online'a
taşınırsa Graph bağlantısı ayrı bir kabul edilmiş `PRD` ile eklenir.

## Kurum ortamı

EWS adresi, NTLM alan adı, servis hesabı, sunucu sürümü ve oda kutusu adresleri depoda tutulmaz.
Ajan bu değerleri fabrikanın MCP sunucusundaki `kurum_ortami_getir` aracından (`area: exchange`, kök
sertifikalar için `area: kok-sertifikalar`) alır; yerel geliştirmede yalnız Git'in yok saydığı ortam
dosyasına yazar, depoya, `values-project.yaml`'a, PRD'ye veya teste yazmaz. Oda eşlemesi uygulamanın
verisinde tutulur. Araç "yapılandırılmamış" derse değerleri Exchange ekibinden yazılı al; uydurma.
Kural, değerlerin biçimini sabitler:

| Ayar | Biçim |
|---|---|
| Exchange | Şirket içi Exchange Server; yapı numarası Exchange ekibinden alınır |
| EWS adresi | `https://<owa adı>/EWS/Exchange.asmx` |
| Kimlik doğrulama | NTLM servis hesabı; Basic kullanılmaz |
| NTLM kimliği | `<ALAN>\<servis-hesabı>` (NetBIOS alan adı + sade hesap adı) |
| Oda kutusu | Odanın Exchange'deki posta kutusu adresi |

Kimlik doğrulama yöntemini kimlik göndermeden ölç:
`curl -sSI https://<owa adı>/EWS/Exchange.asmx | grep -i www-authenticate` komutu `401` ile
`Negotiate` ve `NTLM` döndürmelidir; `Basic` yoksa Basic kipi her istekte `401` alır. NTLM alan adı
sunucunun challenge yanıtında `TargetName` olarak görünür; tahmin etme.

## Bağlantı

- Exchange erişimini tek bir altyapı uyarlayıcısında topla (oda listesi, takvim okuma, oluştur,
  güncelle, iptal, sağlık); iş katmanı yalnız tipli bir portu çağırır. Graph'a geçişte yalnız bu
  uyarlayıcı değişir.
- `Credentials(f"{alan}\\{hesap}", parola)`, `Configuration(service_endpoint=<EWS adresi>,
  credentials=..., auth_type=NTLM, version=Version(build=Build(...)))` ve
  `Account(primary_smtp_address=<servis hesabının adresi>, config=..., autodiscover=False,
  access_type=DELEGATE)` kullan. Autodiscover kapalıdır; adres ayardan gelir. Sunucu yapı numarası
  `Build` ile ayardan verilir; böylece kitaplık sürüm tahmini için ek istek atmaz. Kullanıcı adı zaten
  `ALAN\hesap` biçimindeyse ön eki ikinci kez ekleme; UPN verme.
- Adres `https://` değilse açılış reddeder. TLS doğrulamasını kapatma: `NoVerifyHTTPAdapter` ve
  `verify=False` üretim kodunda bulunmaz. Kurum köklerini, `requests.adapters.HTTPAdapter`'dan
  türeyen ve hem `cert_verify` hem `get_connection_with_tls_context` içinde `verify` değerini kurum
  kökleri PEM dosyasının yoluyla değiştiren bir bağdaştırıcıyla `BaseProtocol.HTTP_ADAPTER_CLS`
  üzerinden tanıt; yalnız `cert_verify`'ı değiştirmek güncel `requests` sürümlerinde yetmez.
- `BaseProtocol.HTTP_ADAPTER_CLS` ve `BaseProtocol.TIMEOUT` süreç genelinde geçerlidir; ikisini
  uygulama açılışında, ilk Exchange bağlantısından önce ata. Kitaplık protokolü ve oturumlarını adrese
  göre önbelleğe alır; sonradan değişen bağdaştırıcı açık oturumlara uygulanmaz. Aynı süreçte farklı
  kimlik veya güven deposuyla iki Exchange yapılandırması kurma. `TIMEOUT` varsayılanı 120 sn'dir;
  tek işlem için sonlu bir değer (ör. 20 sn) ver.
- `exchangelib` eşzamanlıdır. Çağrıyı istek döngüsünü bloklamadan `anyio.to_thread.run_sync` ile iş
  parçacığında çalıştır ve dıştan da süre sınırı koy; iş parçacığı iptal edilemediği için asıl sınır
  `TIMEOUT`'tur. Onay akışı Exchange'e takılı kalmaz.
- Kitaplık içe aktarılırken kullanıcı adını (`getpass.getuser()`) ve yazılabilir geçici dizini okur.
  İmajda kaydı olmayan bir UID ile ve `USER` tanımsızken `import exchangelib` `OSError` verir; arka
  ucu imajdaki kayıtlı kullanıcıyla (`app`, UID `10001`) ve yazılabilir `/tmp` birimiyle çalıştır.
- Servis hesabının etkileşimli girişi kapalıdır; parolası yalnız önceden oluşturulmuş `Secret`'tan
  gelir.

## Yetki ve kapsam

- Doğruluk kaynağı uygulamadır; yazma uygulamadan Exchange'e tek yönlüdür. Outlook'ta reddedilen
  veya silinen davet uygulamadaki kaydı değiştirmez; kullanıcılara iptal ve değişikliğin uygulamadan
  yapılacağını söyle. İki yönlü eşitleme yalnız kabul edilmiş `PRD` her alanın sahibini yazılı
  belirlediğinde kurulur.
- Yalnız onaylanmış ve gelecekteki kayıtları yaz; bekleyen talep ve geçmiş kayıt takvime yazılmaz.
  Hangi kayıt türlerinin yazılacağını `PRD` açıkça listeler. Posta kutusu eşlenmemiş oda entegrasyon
  dışıdır (`skipped`); bu hata değildir.
- Servis hesabı organizatör olarak çalışır ve odayı kaynak olarak davet eder; ek kutu yetkisi
  gerekmez. Başka bir kutu adına açmak gerekiyorsa `ApplicationImpersonation` yalnız oda kutularını
  kapsayan bir yönetim kapsamıyla verilir. Servis hesabının gelen kutusuna düşen kabul/ret yanıtları
  için temizlik kuralı planla.
- Oda kutularının takvim işleme ayarlarını (`AutomateProcessing`, `AllowConflicts`,
  `BookingWindowInDays`, `MaximumDurationInMinutes`, `AddOrganizerToSubject`, `DeleteSubject`,
  `DeleteComments`, servis hesabının rezervasyon izni) Exchange ekibiyle teyit et.

## Toplantı oluşturma, güncelleme ve iptal

- Her yerel kayıt için tek toplantı aç. Odayı `resources`, kullanıcıyı `required_attendees` alanına
  ekle; katılımcı olarak eklenen oda takvimde yer tutmaz. `item.save(send_meeting_invitations=
  SEND_TO_ALL_AND_SAVE_COPY)` ile kaydet; daveti Exchange gönderir, aynı olay için ayrıca `.ics` maili
  atılmaz.
- Kayıttan sonra `item.id`, `item.changekey` ve `item.uid` (`ICalUid`) değerlerini yerel kayda aynı
  anda yaz. Oda takviminde ve mutabakatta eşlemeyi konu veya saatle değil `ICalUid` ile yap; `ItemId`
  öğe taşınınca değişebilir. Bir Exchange oda kutusu tek yerel odaya bağlanır (büyük/küçük harfe
  duyarsız benzersiz indeks); eşleme sabit kodda değil yönetilebilir veride tutulur.
- Güncellemede öğeyi `ItemId` ile al, yalnız değişen alanları ata ve `update_fields` ile aynı davet
  kipinde kaydet. `ItemId` yoksa güncelleme değil oluşturma yap; oda değişiyorsa eskisini iptal edip
  yenisini aç.
- İptalde organizatör öğesinde `item.cancel()` kullan; katılımcısız öğede `item.delete()`.
  `ErrorItemNotFound` ve `ErrorInvalidIdMalformed` iptalde başarı sayılır.
- Kaydın başarılı dönmesi odanın kabul ettiği anlamına gelmez; oda daveti eşzamansız işler. Kısa süre
  sonra organizatör öğesindeki kaynak yanıtını (`response_type`) veya oda takvimini oku; `Decline`
  varsa kaydı `oda_reddetti` sebebiyle işaretle ve yöneticiye göster.
- Metin alanlarını kitaplığa vermeden önce XML 1.0'da yasak kontrol karakterlerinden
  (`\x00`-`\x08`, `\x0b`, `\x0c`, `\x0e`-`\x1f`) temizle ve uzunlukla sınırla (ör. konu 250 karakter).
  `exchangelib` `&`, `<` ve `>` karakterlerini kendisi kaçırır; uygulamada ayrıca kaçırmak çift
  kaçırma üretir. Gövdeyi `Body` ile düz metin ver; `HTMLBody` kullanılmaz.
- Oda takvimi kurumda geniş bir kitleye görünür. Konuya ve gövdeye yalnız gerekli bilgiyi yaz
  (`Proje — Ad Soyad` gibi, uygulamaya dönüş bilgisi); kullanıcı notu, telefon ve kişisel ayrıntı
  yazılmaz.
- Zamanı tek yerde dönüştür: saklama biçimini bil, saat dilimli `EWSDateTime` ile
  `EWSTimeZone("Europe/Istanbul")` kullan, saat dilimsiz yerel damgayı tahminle ayrıştırma. Gece
  yarısını geçen ve tam gün kayıtları test et.

## Oda keşfi ve uygunluk

- `account.protocol.get_roomlists()` ve `get_rooms(...)` oda listelerini döner; listeye üye olmayan
  oda görünmez. Bir listenin okunamaması bütün keşfi düşürmez. Keşif sonucu yerel odalarla otomatik
  eşlenmez; öneri olarak gösterilir, yönetici onaylar.
- Onaydan önce oda takvimini ilgili aralık için oku (`calendar.view(...)`) veya serbest/meşgul
  bilgisini sor; kesilmiş sonucu boş sayma. Uygulamanın kendi açtığı toplantıları `ICalUid` ile
  çakışma sayımından çıkar. Exchange erişilemiyorsa uygunluk `bilinmiyor` olarak raporlanır, sessizce
  uygun sayılmaz.

## Dayanıklılık ve tutarlılık

- Varsayılan esnek kipte Exchange hatası yerel kaydı engellemez: kayıt oluşur, eşitleme `failed`
  işaretlenir ve sonra yeniden denenir. Katı kipte kayıt oluşmaz. İptal hiçbir kipte Exchange yüzünden
  engellenmez. Uygulama ayrıca "takvime eklendi" maili atacaksa yalnız `synced` olduğunda atar.
- Ağ çağrısından önce satırı tek koşullu `UPDATE` ile sahiplen: `ews_item_id IS NULL` ve durum
  `pending` değil ya da sahiplenme zaman damgası bayatlık sınırından eski (ör. 5 dk; işlem zaman
  aşımından belirgin uzun). Etkilenen satır yoksa başka bir çağrı işliyordur; yeni toplantı açma.
  Başarıda `ItemId`, `ICalUid`, `synced` ve zaman damgasını tek `UPDATE` ile yaz.
- Durumlar `skipped`, `pending`, `synced`, `failed`, `cancelled`'dır; son hata kısaltılmış (ör. 300
  karakter) ve sırsız olarak kaydın üstünde tutulur.
- Yeniden deneme işi arka uç sürecinde yaşam döngüsüne bağlı arka plan görevidir ve çok kopyalı
  dağıtımda PostgreSQL danışma kilidiyle (`pg_try_advisory_lock`) tek yürütücüyle çalışır. Yalnız
  gelecekteki kayıtları tarar; `pending`, `failed` ve `skipped` durumlarını tarar; yerelde iptal
  edilmiş ama Exchange'de duran toplantıları iptal eder; tur başına tavan uygular ve kalan sayısını
  raporlar; `ErrorServerBusy` istisnasının `back_off` süresi kadar bekler; deneme tavanını aşan kaydı
  kalıcı `failed` bırakıp yöneticiye gösterir.
- Mutabakat işi gelecekteki `synced` kayıtları `ItemId` ile, bulunamazsa `ICalUid` ile arar; saat,
  oda ve iptal farklarını raporlar ve yerel kaydı kendiliğinden değiştirmez. Yönetici ekranı fark
  türlerini ve tek tıkla yeniden yazmayı gösterir.

## Hata ve işletim

- Hatayı sabit bir alt sebep kümesine eşle; kullanıcıya sade mesaj, yöneticiye alt sebep göster:
  `kapali` (uçlar `503`), `yapilandirma_eksik`, `ulasilamiyor` (`TransportError`, DNS ve bağlantı
  hataları), `zaman_asimi`, `uc_uyusmazligi`, `kimlik_reddedildi` (`UnauthorizedError`, `401`),
  `erisim_reddedildi` (`ErrorAccessDenied`, `403`), `sema_hatasi` (`ErrorSchemaValidation`),
  `oge_yok` (`ErrorItemNotFound`, `ErrorInvalidIdMalformed`), `sunucu_mesgul` (`ErrorServerBusy`),
  `oda_reddetti`, `tls_dogrulanamadi`, `bilinmeyen`. Ham hata iç sunucu adı ve yığın izi taşıyabilir;
  dışarı çıkmaz. Her başarılı ve başarısız oluşturma ve iptal denetim kaydına yazılır.
- Yöneticiye uygulamanın çalıştığı ortamın içinden koşan bağlantı testi ver: `get_roomlists()` ağ,
  TLS, kimlik doğrulama ve okuma yetkisini tek çağrıda sınar; sonuç hata fırlatmadan, alt sebebiyle
  döner. Ekranda adres, kimlik doğrulama yöntemi ve açık/kapalı durumu görünür, parola görünmez. Oda
  eşleme ekranı her odanın son eşitleme durumunu ve son hatasını, "başarısızları yeniden dene"
  düğmesi deneme, başarı, başarısız ve kalan sayılarını gösterir.

## Ayarlar ve dağıtım

Ayarlar `22-backend-yapilandirmasi` kuralına göre tipli ayarlar nesnesinden ve projenin ön ekiyle
okunur, açılışta doğrulanır: `<ENV_PREFIX>EWS_ENABLED` (varsayılan kapalı), `<ENV_PREFIX>EWS_URL`
(yalnız `https://`), `<ENV_PREFIX>EWS_DOMAIN`, `<ENV_PREFIX>EWS_USER` (sade hesap adı),
`<ENV_PREFIX>EWS_PASSWORD` (yalnız `Secret`), `<ENV_PREFIX>EWS_SERVICE_MAILBOX`,
`<ENV_PREFIX>EWS_SERVER_BUILD`, `<ENV_PREFIX>EWS_CA_BUNDLE`, `<ENV_PREFIX>EWS_TIMEOUT_SECONDS` (alt
ve üst sınırla), `<ENV_PREFIX>EWS_STRICT` ve yalnız impersonation kipinde
`<ENV_PREFIX>EWS_IMPERSONATED_MAILBOX`. Özellik açıkken adres, alan adı, kullanıcı, parola, servis
kutusu, sunucu yapı numarası ve kök sertifika zorunludur; eksikse süreç başlamaz ve eksik anahtarları
adıyla söyler. Özellik kapalıyken hiçbir Exchange sırrı
zorunlu değildir ve hiçbir Exchange isteği atılmaz.

Dağıtımda `helm/<ürün-kısa-adı>/values-project.yaml` yalnız `backend.corporateEnvironment.sections`
listesine `exchange` ekler. `deploy.sh` EWS adresini, NTLM alan adını, servis hesabını ve kutusunu,
sunucu yapı numarasını ve EWS sunucusuna `443/TCP` çıkış eşini dağıtım anında kurum ortamından alır
(`45-dagitim-hedefi`); bunlar depoya yazılmaz. Diğer gizli olmayan ayarlar `backend.config` altında,
parola `backend.existingSecret` içinde durur.

## Doğrulama

Uyarlayıcıyı enjekte edilebilir yap ve iş katmanını sahte uyarlayıcıyla sına; gerçek ağa çıkan
testleri birim paketinden ayır, kapalı ağda zaman aşımına düşüp sahte kırmızı üretirler. Zorunlu
senaryolar: özellik kapalıyken Exchange çağrısı yapılmaz, kayıt `skipped`, uçlar `503`; eşlenmemiş
oda `skipped`; esnek kipte Exchange hatasında yerel kayıt oluşur ve durum `failed`; katı kipte kayıt
oluşmaz ama iptal başarılıdır; eşzamanlı iki oluşturma tek toplantı açar; bayat `pending` yeniden
sahiplenilir, taze `pending` sahiplenilmez; `ItemId` doluyken oluşturma yeni toplantı açmaz; iptalde
`ErrorItemNotFound` başarıdır; yeniden deneme işi `skipped`'i de tarar, geçmiş kayıtları taramaz ve
kalan sayısını raporlar; `&`, `<`, `>` ve kontrol karakteri içeren konu temizlenmiş ve bir kez
kaçırılmış olarak gider; gövde düz metindir; zaman aşımı `zaman_asimi` sebebini üretir ve çağrı
süresiz beklemez; her hata doğru alt sebebe eşlenir ve parola ile iç sunucu ayrıntısı dışarı çıkmaz;
yerel damga saat dilimi kaymadan dönüştürülür; üretim kaynağında `NoVerifyHTTPAdapter`,
`verify=False`, `BASIC` ve `autodiscover=True` yoktur (kaynak tarayan test).
