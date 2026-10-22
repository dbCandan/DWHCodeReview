# PRD — scheduled-review-email

Status: Accepted

Version: 1.3.0

Acceptance date: 2026-10-15

Domain: [sql-review](../../DOMAIN.md)

Kabul kaydı: Proje sahibi bu PRD'yi 2026-10-14'te Decision 1–12 ile kabul etti. Alıcıların rapor
erişimi [review-history-export](../005-review-history-export/PRD.md) 1.3.0 Decision 8'dedir
(Decision 12). Bu PRD yeni bir yürütme modeli (arka uç içi zamanlanmış modül) ve yeni bir harici sınır
(kurumsal SMTP) getirir; ikisi [DOMAIN.md](../../DOMAIN.md) belgesindedir. 1.2.0 revizyonu
(Requirement 10, Decision 13–14: e-posta durumu ve deneme e-postası) proje sahibinin 2026-10-15
"mail atmıyor" bildirimi ve tasarımı geliştiriciye bırakan yetkisiyle eklendi; proje sahibi
reddederse bu revizyon geri alınır. Proje sahibi 1.2.0'ı 2026-10-15'te onayladı. 1.3.0 revizyonunu
(Requirement 11, Decision 15: zamanlanmış koşumu durdurma) proje sahibi 2026-10-15'te "zamanlanmış
incelemeler kısmında durduramıyorum" bildirimiyle kabul etti.

**1.x revizyon notu (2026-10-15):** [directory-login](../../../application-foundation/PRDs/001-directory-login/PRD.md) 1.3.0 Decision 14 ile `kural-yoneticisi` rolü kaldırıldı; kullanıcılar `inceleyici` (arayüzde "Kullanıcı") ve süper yöneticidir. Bu belgede kural yöneticisine verilen yetkiler (taslağı düzenleme ve yayımlama, bağlantı ayarları, LLM çağrı özetleri, tüm incelemeleri görme) süper yöneticidedir; "inceleyici" geçen yerler her kullanıcıyı anlatır.

## Amaç

İnceleyici (veya kural yöneticisi), bir **zamanlanmış inceleme tanımı** oluşturur: hangi nesnelerin,
hangi kural gruplarıyla, hangi aralıkta inceleneceğini ve sonucun kime e-posta ile gönderileceğini
belirler. Uygulama bu tanımı belirlenen aralıkta **tarayıcıdan bağımsız, arka planda** çalıştırır;
mevcut inceleme akışını kullanarak koşumu yürütür, sonucu rapor olarak saklar ve belirtilen alıcılara
kurumsal e-posta ile **özet bildirim** gönderir. Böylece inceleme elle başlatılmadan, düzenli olarak
çalışır ve ilgili kişiye ulaşır.

## Aktörler ve sonuçlar

- **İnceleyici (`inceleyici`):** Kendi zamanlanmış inceleme tanımlarını oluşturur, düzenler, duraklatır,
  siler ve geçmiş çalışmalarını görür. Ölçülebilir sonuç: tanım etkinken her periyotta bir koşum çalışır
  ve alıcılara bildirim gider.
- **Kural yöneticisi (`kural-yoneticisi`):** İnceleyicinin yaptıklarına ek bir yetkisi bu PRD'de yoktur.
- **Süper yönetici:** Bütün tanımları görür, düzenler, duraklatır ve siler; kaçırılan ya da hatalı biten
  bir tanımı "Şimdi çalıştır" ile elle tetikler; aynı anda çalışacak zamanlanmış koşum sayısını Ayarlar
  ekranından belirler (Decision 3, 8, 9).
- **İşletim ekibi:** SMTP (e-posta gönderim) sunucusu adresini, kimlik bilgisini ve gönderen adresini
  ortam sırrı olarak verir; uygulama içi rol değildir.

## Değişmezler ve sınırlar

- **Zamanlanmış inceleme tanımı:** ad, nesne seçimi (açık liste veya veritabanı/şema/tür/ad süzgeci),
  kural grubu seçimi ([rule-group-selection](../007-rule-group-selection/PRD.md); boşsa tüm kurallar),
  periyot (örneğin günlük/haftalık/aylık, saat ve zaman dilimi), alıcı e-posta adresleri, etkin/duraklı
  durumu ve sahibi. Kiracıya aittir.
- Zamanlanmış koşum, **en son yayımlanmış kural sürümünü** çalışma anında sabitler
  ([rule-management](../001-rule-management/PRD.md)); yayımlanmış sürüm yoksa koşum çalışmaz ve tanım
  "atlandı (yayımlanmış kural yok)" kaydı tutar.
- Koşum **arka planda** çalışır: tarayıcı bağlantısına veya SSE akışına bağlı değildir
  (object-review'deki canlı akıştan farkı budur). Sonuç ve incelenen SQL metni, elle başlatılan koşumla
  aynı tablolara, aynı saklama süresiyle (varsayılan 90 gün) yazılır
  ([review-history-export](../005-review-history-export/PRD.md)).
- SQL Server yalnız salt okunur sorgulanır; LLM yalnız onaylı kurum içi uca gider; ham SQL ve ham LLM
  yanıtı loga yazılmaz.
- **E-posta yalnız özet taşır.** Bildirim; koşum adı, zaman, seçilen kural grupları, incelenen nesne
  sayısı, durum ve grup/önem bazlı bulgu sayıları ile uygulamadaki rapora bir bağlantı içerir. **Ham SQL
  metni ve kod parçaları e-postaya konmaz; tam rapor (kod parçalı CSV) eke de konmaz** (Decision 1).
  Tam rapora yalnız giriş gerektiren uygulama bağlantısından erişilir.
- Alıcı adresleri yalnız kurum e-posta alan adlarıyla sınırlıdır; izinli alan adları ortam ayarıdır
  (Decision 5); dış adrese gönderim reddedilir. SMTP kimlik bilgisi yalnız sunucu sınırındadır; arayüze, Git'e, Helm değerine ve loga
  girmez.
- SMTP adresi ayarlı değilse zamanlama yine çalışır ve raporu saklar; bildirim "e-posta yapılandırılmadı"
  durumuyla atlanır ve tanım sahibine arayüzde gösterilir.
- Arayüz yalnız Türkçedir.

## İşlevsel gereksinimler

Requirement 1: Kullanıcı zamanlanmış inceleme tanımı oluşturur, listeler, düzenler, duraklatır,
etkinleştirir ve siler. Tanım adı kullanıcı başına tekildir (1–120 karakter). Nesne seçimi ya bir
süzgeç tanımıdır (veritabanı + arama + tür + tarih; **varsayılan**, her çalışmada güncel nesneleri
kapsar) ya da açık bir listedir (object-review Requirement 3 biçiminde seçimler) (Decision 4). Kullanıcı
başına etkin tanım sayısı için sınır yoktur; yük Requirement 7'deki eşzamanlı koşum sınırıyla korunur
(Decision 6).

Requirement 2: Periyot, sınırlı bir aralık kümesinden seçilir (en az: günlük, haftalık belirli güne,
aylık belirli güne), çalışma saati ve zaman dilimiyle. Serbest cron ifadesi kabul edilmez (girdi sınırı,
rules/57). Geçmiş veya geçersiz periyot `422` ile reddedilir.

Requirement 3: Zamanlayıcı, etkin tanımları periyoduna göre **en çok bir kez** tetikler: aynı tanım için
bir önceki koşum hâlâ sürüyorsa yeni tetikleme atlanır ve "önceki koşum sürüyor" kaydı tutulur
(üst üste binme olmaz). Zamanlayıcı arka uç sürecinin içinde çalışan bir modüldür (Decision 2); vadesi
gelen tanımı PostgreSQL satır kilidiyle (`SELECT … FOR UPDATE SKIP LOCKED`) alır, böylece arka uç birden
çok kopyaya çıksa bile bir tetikleme yalnız bir kopyada yürür.

Requirement 4: Tetiklenen koşum, elle başlatılan koşumla aynı yürütme mantığını kullanır (object-review
Requirement 5–17), ama olayları bir tarayıcıya yaymaz; ilerleme sunucu tarafında izlenir. Koşum kaydı
"zamanlanmış" türüyle ve tanımın kimliğiyle saklanır; kural sürümü, seçilen gruplar
([rule-group-selection](../007-rule-group-selection/PRD.md)), nesne sayısı ve durum yazılır.

Requirement 5: Koşum bittiğinde (tamamlandı, hata veya kısmi) sistem, tanımın alıcılarına özet bildirim
e-postası gönderir: koşum adı ve zamanı, seçilen kural grupları, incelenen nesne sayısı, durum, grup ve
önem bazlı bulgu sayıları ve uygulamadaki rapora derin bağlantı. E-posta ham SQL veya kod parçası
içermez. Gönderim başarısızsa artan aralıkla (1, 5 ve 15 dakika sonra) en çok 3 kez yeniden denenir
(Decision 7); hepsi başarısızsa sonuç "e-posta gönderilemedi" olarak tanım geçmişine yazılır; koşum
sonucu yine saklıdır.

Requirement 6: Tanım sahibi, her tanımın son çalışmalarını (zaman, durum, bulgu sayısı, e-posta durumu)
ve her çalışmanın raporunu görür; rapor [review-history-export](../005-review-history-export/PRD.md)
uçlarıyla açılır ve dışa aktarılır. Zamanlanmış koşumlar elle koşumlarla aynı geçmiş listesinde, tür
süzgeciyle ayrılabilir. Koşum başlarken tanımın o anki alıcı listesi koşumla birlikte saklanır;
e-postası bu listedeki bir adresle eşleşen uygulama kullanıcısı, e-postadaki bağlantıyla o koşumun
raporunu salt okunur açar ve indirir (Decision 12, review-history-export Decision 8).

Requirement 7: Zamanlanmış koşum, elle koşumlarla aynı LLM eşzamanlılık sınırlarını paylaşır
([llm-connection](../006-llm-connection/PRD.md) Requirement 7); süreç geneli sınır hiçbir anda aşılmaz.
Aynı anda çalışan zamanlanmış koşum sayısı için ayrı bir üst sınır vardır; fazlası sırada bekler. Sınırı
süper yönetici Ayarlar ekranından belirler (1–10, başlangıç değeri 2); değer kiracı başına uygulamada
saklanır, ortam ayarı değildir (Decision 8).

Requirement 8: Uygulama yeniden başladığında, "sürüyor" kalmış zamanlanmış koşum "yarıda kesildi" olarak
işaretlenir. Zamanı geçmiş ama çalışmamış tetikleme kendiliğinden telafi edilmez: çalışma geçmişine
"kaçırıldı" olarak yazılır, tanım listesinde uyarıyla görünür ve tanım bir sonraki periyodunda çalışır.
Süper yönetici kaçırılan ya da hatalı biten bir tanımı "Şimdi çalıştır" ile elle tetikler; elle
tetiklenen koşum zamanlanmış koşumla aynı yoldan (eşzamanlı sınır dahil) yürür ve geçmişte "elle
tetiklendi" ile tetikleyen kullanıcıyı taşır. Tanımın bir koşumu sürerken elle tetikleme `409` ile
reddedilir (Decision 9).

Requirement 9: Arayüz "Zamanlanmış incelemeler" sayfası: tanım oluşturma/düzenleme formu (ad, nesne
seçimi, kural grubu seçimi, periyot, alıcılar), tanım listesi (durum, sonraki çalışma, son sonuç),
duraklat/etkinleştir/sil ve çalışma geçmişi ("kaçırıldı" ve "e-posta gönderilemedi" uyarılarıyla).
Süper yöneticiye ayrıca bütün kullanıcıların tanımları, "Şimdi çalıştır" düğmesi ve Ayarlar ekranında
"Aynı anda çalışacak zamanlanmış koşum" alanı görünür. Alıcı adresi izinli alan adı dışındaysa veya
biçimsizse form `422` gösterir. Tüm metinler Türkçedir.

Requirement 10: Süper yönetici Yönetim ekranında özet e-postanın bu ortamdan çıkıp çıkamayacağını görür:
zamanlayıcının açık olup olmadığı, SMTP sunucusunun yapılandırılıp yapılandırılmadığı, şifreleme biçimi
ve izinli alıcı alan adları. Tek bir kurum adresine (izinli alan adı kuralı Decision 5 ile aynı) kısa bir
**deneme e-postası** gönderir; sonuç "gönderildi", "SMTP yapılandırılmadı" ya da özet e-postayla aynı
kararlı hata koduyla "gönderilemedi" olarak görünür (Decision 13, 14). Deneme e-postası rapor verisi,
SQL veya bulgu taşımaz.

Requirement 11: Tanım sahibi ve süper yönetici, tanımın sırada bekleyen veya süren koşumunu "Durdur" ile
bitirir: sıradaki koşum hemen "iptal edildi" olur; süren koşum "Analizi durdur" gibi kesilir
([object-review](../003-object-review/PRD.md) Decision 9) ve "iptal edildi" olarak saklanır. Durdurulan
koşum için özet e-posta gitmez; tanım etkin kalır ve sonraki periyotta yeniden çalışır (Decision 15).

## API sözleşmesi

Ön ek `/api/dwhcodereview/v1`. Tüm uçlar geçerli oturum ister; hata zarfı
`{"detail":{"code":"...","message":"..."}}`.

- `GET /scheduled-reviews` → kullanıcının görebildiği tanımlar (sayfalı; kendi tanımları, süper
  yöneticiye bütün tanımlar): `id`, `name`, sahip, nesne seçimi özeti, kural grupları, periyot, alıcı
  sayısı, durum, `next_run_at`, `last_run` özeti, `can_edit`.
- `POST /scheduled-reviews` → tanım oluşturur (201). Hatalar: `422 schedule_invalid`,
  `recipient_domain_not_allowed`, `recipient_invalid`, `schedule_name_duplicate`.
- `GET /scheduled-reviews/{id}` / `PUT /scheduled-reviews/{id}` / `DELETE /scheduled-reviews/{id}` →
  oku/güncelle/sil; yalnız sahip ve süper yönetici. Göremediği tanım `404`.
- `POST /scheduled-reviews/{id}/pause` ve `.../resume` → duraklat/etkinleştir (sahip, süper yönetici).
- `POST /scheduled-reviews/{id}/run` → "Şimdi çalıştır"; yalnız süper yönetici (202). Koşum sürüyorsa
  `409 scheduled_review_running`.
- `GET /scheduled-reviews/{id}/runs` → tanımın çalışma geçmişi; her çalışma koşum `public_id`'si,
  tetiklenme biçimi (`scheduled`, `manual`, `missed`), tetikleyen kullanıcı ve e-posta durumu taşır;
  rapor review-history-export uçlarıyla açılır.
- `GET /scheduled-review-settings` / `PUT /scheduled-review-settings` → `max_concurrent_runs` (1–10);
  yalnız süper yönetici. Aralık dışı değer `422 setting_out_of_range`.
- `GET /scheduled-review-settings/email` → `scheduler_enabled`, `smtp_configured`, `smtp_security`,
  `allowed_domains`, `suggested_recipient` (çağıranın adresi izinli alan adındaysa, değilse `null`);
  yalnız süper yönetici (Requirement 10).
- `POST /scheduled-review-settings/email/test` `{recipient}` → `{status: sent|failed|not_configured,
  error_code}`; yalnız süper yönetici. Alıcı hataları `422 recipient_invalid` /
  `recipient_domain_not_allowed`; bekleme süresi dolmadan ikinci deneme `429 email_test_too_soon`
  (Decision 14).
- `POST /scheduled-reviews/{id}/stop` → `{id, state: cancelling|cancelled}` (202); yalnız sahip ve süper
  yönetici. Bekleyen veya süren koşum yoksa `409 scheduled_review_not_running` (Requirement 11).
- Tanımı yalnız sahibi ve süper yönetici görür; tanımı başka kullanıcılarla paylaşma yoktur (Decision 11).
- İç tetikleme (zamanlayıcı → koşum) dış uç değildir; HTTP yüzeyine çıkmaz.

## Güvenlik ve yetkilendirme

- Her uç oturum ve rol ister. Tanımı sahibi yönetir; süper yönetici bütün tanımları yönetir, elle
  tetikler ve eşzamanlı sınırı ayarlar (Decision 3, 8, 9).
  Bu denetimler arka uçta yapılır.
- Alıcı adresleri yalnız kurum e-posta alan adlarına sınırlıdır; liste ortam ayarıdır (Decision 5).
  Bu, iç kaynak kod bulgularının dışarı gönderilmesini önleyen güven sınırıdır.
- SMTP kimlik bilgisi ve gönderen adresi yalnız sunucu sırrıdır (application-foundation Runtime Secret
  deseni); loga ve arayüze girmez.
- E-posta içeriği ham SQL, kod parçası, LLM adresi veya sunucu ayrıntısı içermez.
- Rapor bağlantısı kimlik doğrulaması gerektiren uygulama sayfasına gider; e-postadaki bağlantı tek
  başına veriye erişim vermez.

## Veri ve geçiş

- Yeni tablolar (Alembic göçü): **zamanlanmış inceleme tanımı** (kiracı, sahip, `public_id`, ad, nesne
  seçimi, kural grubu seçimi, periyot, zaman dilimi, alıcılar, durum, `next_run_at`, `last_run_at`) ve
  **zamanlanmış çalışma kaydı** (tanım, koşum `public_id`, tetiklenme zamanı, tetiklenme biçimi
  `scheduled`/`manual`/`missed`, tetikleyen kullanıcı, sonuç, e-posta durumu ve deneme sayısı),
  **koşum alıcısı** (koşum, küçük harfe çevrilmiş alıcı adresi; Requirement 6) ve **zamanlanmış inceleme
  ayarı** (kiracı başına `max_concurrent_runs`, son değiştiren ve zaman). Koşum tablolarına
  "zamanlanmış" tür ve tanım bağı eklenir (object-review koşum tablosu genişletilir).
- Alıcı adresleri kişisel veri olabilir (KVKK); yalnız sunucuda tutulur, loga yazılmaz. Tanımdaki liste
  tanım silinince silinir; koşumla saklanan kopya koşumla birlikte saklama süresi sonunda silinir.
- Göç genişleticidir; geri alma yeni tabloları düşürür ve etkin tanım varken veri kaybını bildirir.

## Gözlemlenebilirlik

- Log olayları: `scheduled_review.created/updated/deleted/paused/resumed` (tanım `public_id`, kullanıcı
  `public_id`), `scheduled_review.triggered` (tanım, koşum `public_id`), `scheduled_review.skipped`
  (neden: önceki sürüyor / yayımlanmış kural yok / SMTP yok), `scheduled_review.missed`,
  `scheduled_review.manual_run` (tetikleyen kullanıcı `public_id`), `scheduled_review.settings_changed`
  (yeni sınır), `scheduled_review.email_sent` / `email_failed` (alıcı sayısı; adres yazılmaz),
  `scheduled_review.email_test` (kullanıcı `public_id`, sonuç, hata kodu; adres yazılmaz),
  `scheduled_review.stopped` (tanım, koşum kaydı ve kullanıcı `public_id`, sonuç). Ad, SQL
  metni ve bulgu içeriği loga girmez.
- Yeni ölçüm eklenmez (Decision 10); mevcut koşum ölçümleri değişmez.
- İz: tetikleme → koşum → e-posta aralıkları; adres ve içerik özniteliğe girmez (application-foundation
  iz kuralları).

## Dağıtım etkisi

- **Yeni harici sınır (SMTP):** DOMAIN.md harici sınırlarına eklenir; onaylı çıkış hedefi ve kurum CA ile
  TLS gerekir (rules/56 harici içerik/çıkış güveni). Yeni ortam ayarları/sırları: SMTP adresi/port,
  kullanıcı, parola (sır), gönderen adresi, izinli alıcı alan adları, zamanlayıcı açık/kapalı.
  Eşzamanlı koşum sınırı ortam ayarı değil, uygulama ayarıdır (Requirement 7).
- **Zamanlayıcı arka uç içindedir (Decision 2):** Chart'a yeni iş yükü eklenmez; rules/45 (chart
  işleyici iş yükü içermez) korunur. Zamanlayıcı `DWHCODEREVIEW_SCHEDULER_ENABLED` ayarıyla açılır
  (varsayılan kapalı); ayar gizli değildir ve `values-project.yaml` içindeki `backend.config` altında
  verilir.
- SMTP çıkışı: SMTP sunucusu `values-project.yaml` içinde backend çıkış eşi (adıyla sınırlı `ipBlock`)
  olarak eklenir. SMTP kullanıcı ve parolası Git'e ve değer dosyasına girmez; `deploy-hooks.sh` isteğe
  bağlı Azure gizli değişkenlerini mevcut runtime `Secret`'ına eşler.
- Bellek: zamanlanmış koşum web istekleriyle aynı podda çalışır; object-review Riskler'deki 512 MiB pod
  sınırı burada da geçerlidir.

## Test stratejisi

- Arka uç birim: periyot doğrulama, alıcı etki alanı doğrulama, bir sonraki çalışma zamanının hesabı,
  özet e-posta gövdesinin ham SQL/kod parçası içermediği.
- Gerçek PostgreSQL + sahte SMTP + LLM ikamesi: tetikleme bir koşum üretir ve saklar; üst üste binme
  atlanır; yayımlanmış kural yoksa atlanır; e-posta gönderilir ve içeriği özettir; gönderim hatasında
  1/5/15 dakikalık 3 yeniden deneme ve "e-posta gönderilemedi" kaydı; çok kopyada tek yürütme kilidi;
  zamanı geçen tetiklemenin telafi edilmeden "kaçırıldı" yazılması; eşzamanlı sınırın aşılmaması ve
  ayarın değişince uygulanması.
- API: sahip/süper yönetici yetki ayrımı (`404`), `schedule_invalid`,
  `recipient_domain_not_allowed`, duraklat/etkinleştir, "Şimdi çalıştır"ın yalnız süper yöneticiye açık
  olması ve koşum sürerken `409`, ayar ucunun aralık denetimi.
- Ön yüz (Vitest): tanım formu, periyot ve alıcı doğrulama iletileri, tanım listesi ve çalışma geçmişi,
  rapora bağlantı.

## Vektör ve gömme sözleşmesi (uygulanabilirse)

- Sağlayıcı / dağıtım sınırı: Uygulanamaz
- Model kimliği ve değişmez sürüm: Uygulanamaz
- Boyut ve normalleştirme: Uygulanamaz
- Uzaklık metriği ve indeks stratejisi: Uygulanamaz
- Getirim kalitesi/duyarlılık ve gecikme eşikleri: Uygulanamaz
- Kaynak sınıflandırması, en aza indirme ve saklama: Uygulanamaz
- Yeniden gömme, geçiş ve geri alma: Uygulanamaz

## Kabul kriterleri

- [ ] Acceptance 1: L1 — Otomatik testlerden geçti: periyot/alıcı doğrulama, sonraki çalışma zamanı ve
  özet e-posta gövdesi (ham SQL yok) birim testleri geçer (Requirement 1, 2, 5).
- [ ] Acceptance 2: L1 — Otomatik testlerden geçti: sahte SMTP ve LLM ikamesiyle tetikleme→koşum→saklama,
  üst üste binme engeli, yayımlanmış kural yokken atlama, tek yürütme kilidi ve e-posta yeniden deneme
  testleri geçer (Requirement 3, 4, 5, 7, 8).
- [ ] Acceptance 3: L1 — Otomatik testlerden geçti: API yetki/sahiplik ve doğrulama hataları testleri
  geçer; OpenAPI kayıtlı yapıtla aynıdır (Requirement 1, 9).
- [ ] Acceptance 4: L2 — Gerçek istemci/ortamda doğrulandı: yerel PostgreSQL, test SQL Server, LLM ucu ve
  test SMTP'siyle bir tanım oluşturulur, kısa bir periyotta arka planda çalışır, rapor saklanır ve
  alıcıya özet e-posta ulaşır; e-postada kod parçası bulunmaz; rapor bağlantısı oturumla açılır
  (Requirement 1–6, 9).
- [ ] Acceptance 5: L1 — Otomatik testlerden geçti: e-posta durumu ve deneme e-postası yalnız süper
  yöneticiye açıktır; SMTP yokken "yapılandırılmadı" döner; deneme sahte SMTP'ye doğrulanmış TLS ile tek
  kurum adresine gider ve rapor verisi taşımaz; ulaşılamayan sunucu kararlı kodla döner; adres loga
  girmez (Requirement 10).
- [ ] Acceptance 6: L1 — Otomatik testlerden geçti: sahip sıradaki koşumu durdurur, başkası `404`, koşum
  yokken `409`; durdurulan koşum "iptal edildi" görünür ve tanım etkin kalır (Requirement 11).

## Kararlar

- Decision 1: Zamanlanmış koşum e-postası **yalnız özet + uygulamaya bağlantı** taşır; ham SQL, kod
  parçası ve tam rapor (kod parçalı CSV) e-postaya veya eke konmaz. Proje sahibinin 2026-10-05 kararı.
  Gerekçe: iç kaynak kodun e-postayla dışarı çıkmasını önler (KVKK/gizlilik, alan değişmezleri).
- Decision 2: Zamanlayıcı **arka uç sürecinin içinde çalışan bir modüldür**; tekil yürütmeyi PostgreSQL
  satır kilidi sağlar. Proje sahibinin 2026-10-05 kararı. Gerekçe: zorunlu dağıtım kuralı
  (`rules/45-dagitim-hedefi.md`) chart'ın işleyici iş yükü içermesini yasaklar; zamanlayıcı bu nedenle
  ayrı bir Kubernetes iş yükü değildir. Ek yararı: zamanlanmış koşumlar elle koşumlarla aynı süreç
  geneli LLM sınırını paylaşır (llm-connection Requirement 7), LLM yükü ikinci bir süreçle katlanmaz.
- Decision 3: Süper yönetici bütün zamanlanmış tanımları görür, düzenler, duraklatır ve siler; diğer
  kullanıcılar yalnız kendi tanımlarını yönetir. Proje sahibinin 2026-10-05 kararı.
- Decision 4: Nesne seçimi hem süzgeç hem açık liste olabilir; varsayılan süzgeçtir. Proje sahibinin
  2026-10-05 kararı. Gerekçe: süzgeç yeni eklenen nesneleri de yakalar.
- Decision 5: E-posta yalnız kurum alan adlarındaki adreslere gider; izinli alan adları ortam ayarıdır.
  Proje sahibinin 2026-10-05 kararı.
- Decision 6: Kullanıcı başına etkin tanım sayısı sınırlanmaz; yük eşzamanlı koşum sınırıyla korunur.
  Proje sahibinin 2026-10-05 kararı.
- Decision 7: Başarısız e-posta 1, 5 ve 15 dakika sonra olmak üzere en çok 3 kez yeniden denenir. Proje
  sahibinin 2026-10-05 kararı.
- Decision 8: Aynı anda çalışacak zamanlanmış koşum sayısını süper yönetici uygulamadaki Ayarlar
  ekranından belirler (1–10, başlangıç 2); değer ortam ayarı değil, kiracı başına uygulama ayarıdır.
  Proje sahibinin 2026-10-05 kararı.
- Decision 9: Kaçırılan tetiklemeler kendiliğinden telafi edilmez; geçmişte "kaçırıldı" görünür ve süper
  yönetici gerekirse "Şimdi çalıştır" ile elle tetikler. Proje sahibinin 2026-10-05 kararı. Gerekçe:
  uzun kesintiden sonra LLM'e yığılmayı önler; hangi işin yeniden çalışacağına insan karar verir.
- Decision 10: Bu yetenek için yeni ölçüm eklenmez; log olayları yeterlidir. Proje sahibinin 2026-10-05
  kararı.
- Decision 11: Tanım yalnız sahibine ve süper yöneticiye görünür; ekip veya paylaşım kapsamı yoktur. Proje
  sahibinin 2026-10-14 kararı. Gerekçe: rapor iç kaynak kod bulguları içerir; görünürlük sahiplikle
  sınırlı kalır, rapora alıcı erişimi Decision 12 ile ayrıca tanımlıdır.
- Decision 12: E-posta alıcısı olan uygulama kullanıcısı, alıcısı olduğu koşumun raporunu salt okunur
  açar ve indirir. Alıcılık koşum başında saklanan alıcı listesine göre belirlenir; erişim kuralı
  [review-history-export](../005-review-history-export/PRD.md) Decision 8'dedir. Proje sahibinin
  2026-10-05 kararı. Gerekçe: e-postadaki "Raporu aç" bağlantısı alıcıya çalışmalıdır.
- Decision 13: E-posta durumu ve deneme yalnız süper yöneticiye açıktır; SMTP adresi, kullanıcı adı ve
  gönderen adresi yanıtta yer almaz, yalnız "yapılandırıldı mı" bilgisi döner. Proje sahibinin
  2026-10-15 yetkisiyle. Gerekçe: "mail atmıyor" durumunda kök neden (yapılandırma yok, çıkış
  kapalı, TLS, kimlik) uygulamadan, sır göstermeden anlaşılmalıdır.
- Decision 14: Deneme e-postası tek alıcıya gider, alıcı izinli alan adı kuralına uyar (Decision 5) ve
  aynı süper yönetici için 15 saniyede bir kez gönderilebilir. Proje sahibinin 2026-10-15 yetkisiyle.
  Gerekçe: kurumsal SMTP'nin toplu gönderim için kullanılmasını önler.
- Decision 15: Zamanlanmış koşumu tanım sahibi ve süper yönetici durdurur; durdurma yalnız o koşumu
  bitirir, tanımı duraklatmaz (duraklatma ayrı bir işlemdir). Durdurulan koşum için e-posta gitmez.
  Proje sahibinin 2026-10-15 bildirimi.

## Açık sorular

Açık soru kalmadı.

## Teslim akışı

Belirtim → Plan → Görevler → Uygulama ([Plan](plan.md), [Görevler](tasks.md)).

## Riskler

- **Gizlilik:** Rapor iç kaynak kod bulguları içerir; e-postaya özet dışında içerik konması veri sızıntısı
  riskidir. "Yalnız özet + bağlantı" kararı (Decision 1) ve kurum alan adı sınırı (Decision 5) bu riski
  sınırlar.
- **Yük:** Zamanlanmış koşumlar LLM sınırını elle incelemeyle paylaşır; kötü ayarlanmış periyot ve büyük
  seçim, iş saatlerinde elle incelemeyi yavaşlatabilir. Requirement 7 ayrı üst sınır getirir.
- **Dağıtımda kesilme:** Zamanlayıcı arka uçta çalıştığı için her dağıtım (backend yeniden başlaması)
  süren zamanlanmış koşumu "yarıda kesildi" yapar; koşum kaldığı yerden devam etmez ve o ana kadarki
  LLM çağrıları atılır. Süper yönetici "Şimdi çalıştır" ile yeniden başlatır (Requirement 8, Decision 9).
  Dağıtımları uzun zamanlanmış koşumların saatlerine denk getirmemek işletim ekibinin dikkat edeceği
  bir noktadır.
- **Çift çalışma:** Arka uç birden çok kopyaya çıkarsa aynı tetiklemenin iki kez çalışmasını satır kilidi
  önler (Requirement 3); kilit testi bunu doğrular.
- **Elle tetikleme:** Süper yöneticinin "Şimdi çalıştır"ı yanlış zamanda kullanması iş saatinde LLM'i
  yükleyebilir; eşzamanlı sınır (Requirement 7) bunu da kapsar.
- **E-posta sırları:** SMTP kimlik bilgisi sırdır; sızarsa dış gönderim kötüye kullanılabilir.
- **Uzun koşum:** Nesne sınırı olmadığından (object-review Decision 3) bir tanım saatlerce süren bir
  koşum üretebilir; periyot bundan kısaysa üst üste binme engeli (Requirement 3) devreye girer.
