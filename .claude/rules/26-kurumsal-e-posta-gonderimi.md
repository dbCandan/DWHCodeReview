<!-- kt-scaffold tarafından ÜRETİLDİ. rules/ dizinini düzenleyip yeniden üretin. -->
---
paths:
  - app/backend/**
  - app/infra/**
  - helm/**
  - specs/**/PRDs/**
---

# Maili yalnız kurum relay'inden, zorunlu STARTTLS ve doğrulanan sertifikayla gönder

# Kurumsal mail gönderimi

Mail gönderimi sabit profilin isteğe bağlı yeteneğidir (`technology-profile.yml#corporate_mail`).
Yalnız kabul edilmiş `PRD` mail gönderen bir davranış tanımladığında aç: `requirements.in` sonuna
`-r requirements-mail.in` ekle, `scripts/compile-dependency-locks.sh` ile kilitleri yeniden üret,
`dependency-admission.json` kaydını güncelle. Tek istemci `aiosmtplib`'dir; eşzamanlı `smtplib`,
üçüncü parti mail servisleri ve kurum dışı SMTP sunucuları kullanılmaz. Takvim daveti mail ile
gönderilmez; davet `27-exchange-takvim-esitlemesi` kuralındaki takvim entegrasyonundan çıkar.

## Kurum ortamı

Relay adresi, servis hesabı ve gönderen adresi depoda tutulmaz. Ajan bu değerleri fabrikanın MCP
sunucusundaki `kurum_ortami_getir` aracından (`area: mail`, kök sertifikalar için
`area: kok-sertifikalar`) alır; yerel geliştirmede yalnız Git'in yok saydığı ortam dosyasına yazar,
depoya, `values-project.yaml`'a, PRD'ye veya teste yazmaz. Araç "yapılandırılmamış" derse değerleri
mesajlaşma ekibinden yazılı al; uydurma. Kural, değerlerin biçimini sabitler:

| Ayar | Biçim |
|---|---|
| Relay | Kurum içi SMTP relay'inin DNS adı (IP değil); port `25` veya `587` |
| Taşıma | Düz bağlantı, ardından zorunlu STARTTLS |
| Kimlik doğrulama | SMTP AUTH, servis hesabının **sade adıyla** (`<servis-hesabı>`); UPN (`<servis-hesabı>@<iç alan adı>`) `535` alır |
| Gönderen | Servis hesabının kurumsal adresi: `Görünen Ad <<servis-hesabı>@<kurumsal alan adı>>` |
| Relay sertifikası | Kurum iç CA'sıyla imzalı; zincir kurum kökleriyle doğrulanır |

Relay'in AUTH mı IP izin listesi kipinde mi çalıştığını mesajlaşma ekibinden yazılı al. IP kipinde
kullanıcı adı boş kalır; dolu kullanıcı adı AUTH denemesine ve `535`'e yol açar. Kubernetes'te pod IP'si
değişkendir; izin listesinde kümenin çıkış adresi bulunmalıdır. Relay ani yüzlerce bağlantıda hız
sınırına takılır.

## Bağlantı ve TLS

- Port `25` ve `587`'de `aiosmtplib.SMTP(..., use_tls=False, start_tls=True)`, yalnız `465`'te
  `use_tls=True, start_tls=False` kullan. `start_tls=None` varsayılanı fırsatçıdır: sunucu STARTTLS
  önermezse parola ve gövde düz metinle gider. Bu yüzden `start_tls` her zaman açıkça verilir.
- Sertifika doğrulamasını hiçbir dalda kapatma: `validate_certs=False`, `ssl.CERT_NONE`,
  `check_hostname=False` ve `ssl._create_unverified_context` üretim kodunda bulunmaz. İç CA sorununu
  güven deposunu genişleterek çöz: `ctx = ssl.create_default_context()`,
  `ctx.load_verify_locations(cafile=<kurum kökleri PEM>)`, `ctx.minimum_version = ssl.TLSVersion.TLSv1_2`
  ve bağlantıya `tls_context=ctx` ver. Kurum kök ve ara sertifikaları gizli değildir; proje PEM
  dosyasını kurumdan edinir, depoda ve imajda taşır, yolunu ayardan okur.
- Relay'e IP ile değil adıyla bağlan; sertifika ad doğrulaması bu adla yapılır. Zinciri önce gör:
  `openssl s_client -starttls smtp -connect <relay>:25 -servername <relay> -CAfile <kökler.pem>`
  komutu `Verify return code: 0 (ok)` vermeden devam etme.
- AUTH yalnız TLS kurulduktan sonra yapılır. Servis hesabı parolası yalnız önceden oluşturulmuş
  `Secret`'tan gelir; komut satırı argümanına, loga, değer dosyasına ve depoya yazılmaz. Servis
  hesabına başkası adına gönderim (`Send As`) yetkisi istenmez.
- Bağlantıya sonlu zaman aşımı ver (`timeout=`, ör. 15-20 sn) ve gönderimi `asyncio.timeout` ile sar;
  relay yanıt vermediğinde istek işçisi asılı kalmaz.

## Zarf, başlık ve içerik

- Mesajı standart `email.message.EmailMessage` ile kur; MIME'ı ve Türkçe başlık kodlamasını
  kitaplığa bırak. Konu, görünen ad ve adres alanlarından CR, LF ve diğer kontrol karakterlerini
  çıkar; konuyu uzunlukla sınırla (ör. 200 karakter). Kullanıcı metni yeni başlık üretemez.
- `From` ayardan okunur, istemciden alınmaz ve servis hesabının adresidir; yalnız görünen ad
  değişebilir. Yanıt gerçek bir kutuya gidecekse `Reply-To` kullan. Otomatik bildirimde
  `Auto-Submitted: auto-generated` başlığını ekle.
- Alıcıyı kayıtlı ve doğrulanmış adresten seç. Kurum dışına gönderim gerekmiyorsa alan adı izin
  listesi (yalnız kurumsal alan adı) uygula; dış adreslere açmak ürün sahibi kararıdır. Adreste tek `@`,
  boşluk ve kontrol karakteri yokluğu ve en fazla 254 karakteri doğrula.
- Her şablon konu, düz metin ve HTML üretir; düz metin sürümü zorunludur (`set_content` ardından
  `add_alternative(..., subtype="html")`). HTML'e giren her değeri `html.escape` ile kaçır; kullanıcı
  girdisini ham HTML olarak kabul etme. Stil satır içidir; harici CSS, script, form ve uzak görsel
  kullanma, görseli `cid:` ile göm.
- Bağlantıların kökü ayardaki kanonik uygulama adresidir; istek `Host` veya `X-Forwarded-Host`
  başlığından bağlantı üretme. Yalnız `https://` şeması kullanılır.
- Parolayı mail ile gönderme; tek kullanımlık, kısa süreli bağlantı gönder ve tokenın yalnız özetini
  sakla (`58-kimlik-dogrulama-ve-yetkilendirme`). Konu satırına hassas bilgi yazma; mailde yalnız amaca
  gereken kişisel veriyi taşı. Eki yalnız gerekiyorsa, sunucuda üretilmiş adla ve relay boyut
  tavanının belirgin altında koy; hassas dosyayı yetki kontrollü indirme bağlantısıyla ver.

## Teslimat

- Mail ana işlemi bloklamaz ve patlatmaz. Parola sıfırlama, onay ve hesap açma relay erişilemezken
  de tamamlanır; HTTP yanıtı gönderimi beklemez ve mailin gidip gitmediğini sızdırmaz.
- Kaybı kabul edilemeyen maili iş değişikliğiyle aynı `AsyncSession` işleminde bir giden kutusu
  (`outbox`) tablosuna yaz: şablon anahtarı, alıcı kimliği, şablon verisi, durum, deneme sayısı,
  sonraki deneme zamanı ve benzersiz kısıtlı tekillik anahtarı (ör. `onay-sonucu:<talepId>`). Tablo
  `40-kalicilik-kaynagi` kuralına göre alan modelinde ve `Alembic` göçünde tanımlanır. Bellekte
  arka plan görevine bırakılan gönderim yalnız kaybı kabul edilebilir bildirim içindir.
- Giden kutusu işçisi arka uç sürecinde yaşam döngüsüne bağlı bir arka plan görevi olarak çalışır ve
  satırı ağ çağrısından önce atomik olarak sahiplenir (`SELECT ... FOR UPDATE SKIP LOCKED` veya
  koşullu `UPDATE ... WHERE durum = 'bekliyor'`); çok kopyalı dağıtımda aynı satır iki kez gönderilmez.
  Bayat `gonderiliyor` satırı (ör. 10 dakikadan eski) yeniden sahiplenilebilir.
- Geçici hatayı (ağ, `421`, `450`-`452`) üstel geri çekilmeyle yeniden dene; kalıcı hatada (`5xx`)
  denemeyi bırak. Deneme tavanı dolan satır `basarisiz` kalır, silinmez. Kuyruğa gövde değil şablon
  verisi yazılır; içinde token varsa satır gönderimden sonra temizlenir.
- Toplu gönderimde her alıcıya ayrı mail gönder; adresler `To`/`Cc`'de birbirine görünmez, tek zarflı
  `Bcc` kullanılmaz. Alıcı listesini sunucu veritabanından kurar; istemci yalnız kapsamı söyler.
  Yalnız etkin ve e-postası doğrulanmış hesapları al, büyük/küçük harfe duyarsız tekilleştir, toplam
  alıcı tavanını aşan gönderimi başlatmadan reddet, küçük gruplar ve gruplar arası bekleme ile gönder,
  sonucu (toplam, gönderilen, başarısız, maskeli ulaşılamayan adresler) yöneticiye raporla ve denetim
  kaydına yaz. Uzun gönderim istek içinde değil arka plan işinde yürür.

## Hata, log ve işletim

- Hatayı istisna türü ve SMTP koduyla (`SMTPResponseException.code`) sabit bir alt sebep kümesine
  eşle, metniyle eşleme: `yapilandirma_eksik`, `dns_bulunamadi`, `baglanti_reddedildi`,
  `baglanti_zaman_asimi` (`SMTPConnectTimeoutError`, `SMTPReadTimeoutError`), `tls_dogrulanamadi`,
  `tls_ad_uyusmazligi`, `tls_kip_hatasi`, `starttls_yok` (`SMTPException`: sunucu STARTTLS önermiyor
  veya `530`), `kimlik_reddedildi` (`SMTPAuthenticationError`, `535`), `gonderen_reddedildi`
  (`SMTPSenderRefused`, `550 5.7.1`, `553`), `relay_reddedildi` (`550 5.7.1 Unable to relay`,
  `554`), `alici_reddedildi` (`SMTPRecipientsRefused`, `550 5.1.1`), `hiz_siniri` (`421`, `450`,
  `451`, `452`), `mesaj_buyuk` (`552`), `bilinmeyen`. Bir alıcının reddi diğerlerini durdurmaz;
  `send_message` dönüşündeki alıcı hatalarına bak.
- Relay'in kabul etmesi teslim değildir; geri dönen bildirimleri servis hesabının kutusunda izle.
- Loga ve denetim kaydına adresi maskeli yaz (`a***@<alan adı>`); gövde, parola, token ve
  sıfırlama bağlantısı hiç yazılmaz. Ham SMTP hata metni kullanıcıya dönmez; ayrıntı yalnız
  yöneticinin gördüğü kayıttadır. Ölçüler alt sebebe göre sayılır, adres etiket olmaz
  (`25-backend-gozlemlenebilirligi`).
- Yöneticiye uygulamanın çalıştığı ortamın içinden koşan iki araç ver: gönderimle aynı ayarla
  bağlanıp STARTTLS ve AUTH'u mail atmadan sınayan bağlantı testi ve yalnız oturumdaki yöneticinin
  doğrulanmış adresine giden test maili. Özellik kapalı veya ayar eksikse ekran bunu adıyla söyler.

## Ayarlar ve dağıtım

Ayarlar `22-backend-yapilandirmasi` kuralına göre tipli ayarlar nesnesinden ve projenin ön ekiyle
okunur, açılışta doğrulanır: `<ENV_PREFIX>MAIL_ENABLED` (varsayılan kapalı), `<ENV_PREFIX>SMTP_HOST`
(IP değil ad), `<ENV_PREFIX>SMTP_PORT`, `<ENV_PREFIX>SMTP_USER` (sade ad; IP kipinde boş),
`<ENV_PREFIX>SMTP_PASSWORD` (yalnız `Secret`), `<ENV_PREFIX>SMTP_CA_BUNDLE`,
`<ENV_PREFIX>MAIL_FROM`, `<ENV_PREFIX>MAIL_REPLY_TO`, `<ENV_PREFIX>MAIL_ALLOWED_RECIPIENT_DOMAINS`,
`<ENV_PREFIX>MAIL_BROADCAST_MAX_RECIPIENTS` ve bağlantı kökü `<ENV_PREFIX>PUBLIC_ORIGIN`.
Özellik açıkken ad, gönderen ve kök sertifika zorunludur; kullanıcı doluysa parola zorunludur;
kullanıcıda `@` varsa açılış reddeder; gönderen kurumsal alan adında değilse açılış reddeder; TLS
doğrulamasını kapatan veya STARTTLS'i isteğe bağlı yapan ayar yoktur. Özellik kapalıyken hiçbir mail
sırrı zorunlu değildir ve hiçbir bağlantı açılmaz.

Dağıtımda `helm/<ürün-kısa-adı>/values-project.yaml` yalnız `backend.corporateEnvironment.sections`
listesine `mail` ekler. `deploy.sh` relay adresini, portu, servis hesabını, gönderen adresini, izinli
alan adlarını ve relay'e `25/TCP` (veya kurum ortamındaki port) çıkış eşini dağıtım anında kurum
ortamından alır (`45-dagitim-hedefi`); bunlar depoya yazılmaz. Diğer gizli olmayan ayarlar
`backend.config` altında, parola `backend.existingSecret` içinde durur.

## Doğrulama

Taşıyıcıyı enjekte edilebilir bir portun arkasında tut ve birim testlerini sahte uyarlayıcıyla yaz;
gerçek relay'e çıkan test birim paketinde yer almaz. Zorunlu senaryolar: özellik kapalıyken bağlantı
açılmaz ve işlem tamamlanır; relay hatasında çağıran işlem başarılı biter ve hata alt sebebiyle
kaydedilir; CR/LF içeren konu ve adres yeni başlık üretmez; `<script>` içeren kullanıcı adı HTML'de
kaçırılır; her şablonun düz metni doludur; sahte `Host` başlığıyla bile sıfırlama bağlantısı kanonik
adresi kullanır; toplu gönderimde her alıcıya ayrı mesaj, tekilleştirme, pasif hesabın dışlanması ve
tavan aşımında hiç başlamama; aynı tekillik anahtarı ikinci satır üretmez, iki işçi aynı satırı
sahiplenemez, geçici hata yeniden denenir, kalıcı hata denenmez; logda açık adres, parola veya token
geçmez; her SMTP hatası doğru alt sebebe eşlenir; üretim kaynağında `validate_certs=False`,
`ssl.CERT_NONE` ve `start_tls=` verilmemiş `aiosmtplib.SMTP` çağrısı yoktur (kaynak tarayan test).
Uçtan uca denemede yerel bir SMTP yakalayıcıyı test CA'sıyla STARTTLS üzerinden kullan.
