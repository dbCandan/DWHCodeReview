# PRD — script-review

Status: Accepted

Version: 1.1.0

Acceptance date: 2026-09-27

Domain: [sql-review](../../DOMAIN.md)

Kabul kaydı: Proje sahibi bu PRD'yi 2026-09-27'de, açık sorulardaki önerileri ve sahip kararlarını
benimseyerek kabul etti.

**1.x revizyon notu (2026-10-15):** [directory-login](../../../application-foundation/PRDs/001-directory-login/PRD.md) 1.3.0 Decision 14 ile `kural-yoneticisi` rolü kaldırıldı; kullanıcılar `inceleyici` (arayüzde "Kullanıcı") ve süper yöneticidir. Bu belgede kural yöneticisine verilen yetkiler (taslağı düzenleme ve yayımlama, bağlantı ayarları, LLM çağrı özetleri, tüm incelemeleri görme) süper yöneticidedir; "inceleyici" geçen yerler her kullanıcıyı anlatır.

## Amaç

İnceleyici, veritabanından nesne seçmeden elindeki SQL metnini yapıştırır, isterse kısa bir ad (etiket)
verir ve metni en son yayımlanmış kural sürümüne göre kurum içi LLM (büyük dil modeli) ile inceletir.
Nesne incelemesiyle aynı canlı ilerlemeyi ve aynı satır referanslı sonuçları görür. Bu PRD yalnız nesne
incelemesinden farklı olanı tanımlar; ortak inceleme davranışının sahibi
[object-review](../003-object-review/PRD.md) PRD'sidir.

## Aktörler ve sonuçlar

- **İnceleyici (`inceleyici`):** SQL metnini ve isteğe bağlı etiketi girer, koşum başlatır, izler,
  durdurabilir, sonucu görür. Ölçülebilir sonuç: yapıştırılan metin için yayımlanmış sürümdeki her kurala
  tam bir kural sonucu döner; SQL Server erişilemese bile inceleme çalışır.
- **Kural yöneticisi (`kural-yoneticisi`):** İnceleyicinin yapabildiği her şeyi yapar; ek yetki yoktur.
- **İşletim ekibi:** Boyut sınırı ve istek gövdesi sınırını ortam yapılandırmasında ayarlar.

## Değişmezler ve sınırlar

- Koşum yalnız en son yayımlanmış kural sürümünü kullanır ve sürümü saklar
  ([rule-management](../001-rule-management/PRD.md)).
- Metin incelemesi SQL Server'a hiç bağlanmaz: tanım okuma ve nesne meta verisi yoktur.
- Yapıştırılan metin, kod parçaları ve ham LLM yanıtı günlüğe (log) yazılmaz. Yapıştırılan metin koşumla
  birlikte saklama süresi boyunca (varsayılan 90 gün) saklanır ve yalnız koşumu başlatan kullanıcıya ve
  `kural-yoneticisi` rolüne açıktır (Decision 1).
- LLM'e gidiş, eşzamanlılık sınırı ve LLM çağrı özetleri [llm-connection](../006-llm-connection/PRD.md)
  PRD'sindedir; geçmiş ve dışa aktarma [review-history-export](../005-review-history-export/PRD.md)
  PRD'sindedir; giriş ve roller
  [directory-login](../../../application-foundation/PRDs/001-directory-login/PRD.md) PRD'sindedir.
- Canlı ilerleme SSE ile gelir (SSE: sunucunun tarayıcıya tek yönlü, sürekli olay gönderdiği bağlantı).
  Akış başlamadan oturum ve rol denetlenir; bağlantı koparsa iş durur. Arayüz yalnız Türkçedir.

## Mevcut davranış

Kaynak: `~/codes/dwhcodereview`. "Hedefte" notu olan maddeler bilinçli davranış değişikliğidir.

- **Uçlar** (`backend/main.py` `POST /api/review/script`, `POST /api/review/script/stream`): Metin
  baştaki ve sondaki boşluklardan arındırılır; boşsa akış açılmadan `400` "SQL metni boş olamaz." döner.
  Arayüz yalnız akışlı ucu kullanır. **Hedefte:** akışsız uç kaldırılır; boş metin `422` olur (API
  standardındaki doğrulama durumu).
- **İstek modeli** (`backend/models/schemas.py` `ScriptReviewRequest`): `sql` 1–200.000 karakter,
  `label` en çok 200 karakter, isteğe bağlı.
- **Sessiz kesme** (`backend/services/llm_review.py` `review_sql`): İnceleme metni ilk 120.000 karakterle
  kesilir; 120.000–200.000 karakter arasındaki kısım uyarısız incelenmez. **Hedefte:** sınır 120.000
  karakterdir ve aşan metin reddedilir (Decision 2).
- **Etiket** (`backend/services/review_orchestrator.py` `_sanitize_paste_label`): Etiket boşluktan
  arındırılır; boşsa "Yapıştırılan SQL" olur; en çok 200 karakter alınır. İstek modeli 200 karakteri zaten
  sınırladığı için kesme pratikte çalışmaz.
- **Sonuç kimliği** (`review_pasted_sql`): Sonuç şema `sql`, ad = etiket, tür `SCRIPT`, veritabanı boş
  olarak döner; LLM çağrı özetindeki nesne adı "<etiket> (SCRIPT)" olur. İlerleme olayları `kind:
  "script"`, `database: ""`, `object_index: 0`, `objects_total: 1`, `schema: "sql"`, `type_code: "SCRIPT"`
  taşır.
- **Meta veri** (`llm_review.py` `_metadata_block_for_rule`): Meta veri istenmez; "nesne meta verisi
  gerekir" işaretli kuralların isteğine "yapıştırılan SQL veya bağlantı olmadığı için özet eklenemedi;
  yalnızca SQL metnine güven" notu eklenir.
- **Ortak akış:** İki parçalı analiz, kural başına çağrı, çözümleme, birleştirme ve satır referansı nesne
  incelemesiyle aynıdır ([object-review](../003-object-review/PRD.md) Mevcut davranış).
- **Arayüz** (`frontend/src/pages/ScriptReviewPage.tsx`, `contexts/ReviewAnalysisContext.tsx`): "SQL
  betiği incelemesi" sayfası; etiket alanı ("Sonuçlarda görünecek ad (isteğe bağlı)", 200 karakter),
  metin alanı, karakter sayacı ("n karakter" / "Metin yok"), "Kurallara göre incele" düğmesi. Metin boşken
  veya koşum sürerken düğme kapalıdır; koşum sürerken alanlar kilitlenir. Son metin dışa aktarım için
  bellekte tutulur.
- **Tarayıcı deposu** (`frontend/src/analysisHistoryStorage.ts`): Sonuç, yapıştırılan SQL metni dahil,
  tarayıcının kalıcı deposuna yazılır (son 50 kayıt). **Hedefte:** tarayıcı deposu kullanılmaz; metin
  tarayıcıda yalnız o oturumun belleğinde kalır, sunucuda koşumla saklanır (Decision 1).
- **Hız sınırı:** Metin incelemesi nesne incelemesiyle aynı IP sayacını paylaşır. **Hedefte:** aynı
  kullanıcı sayacını paylaşır.

## İşlevsel gereksinimler

Requirement 1: Metin baştaki ve sondaki boşluklardan arındırılır. Arındırılmış metin boşsa koşum
başlamaz; yanıt `422` ve `sql_text_empty` kodu, ileti "SQL metni boş olamaz." olur.

Requirement 2: Arındırılmış metin en çok 120.000 karakterdir. Aşan metin kesilip incelenmez; `422` ve
`sql_text_too_long` koduyla, sınırı söyleyen Türkçe iletiyle reddedilir. Arayüz karakter sayacını gösterir ve sınır aşılınca
düğmeyi kapatıp aynı iletiyi gösterir.

Requirement 3: Etiket isteğe bağlıdır; boşluktan arındırılır; boşsa "Yapıştırılan SQL" olur;
arındırılmış etiket 200 karakteri aşarsa `422` ve `label_too_long` döner. Arayüz alanı 200 karakterle
sınırlar.

Requirement 4: Sonuç tek bir sonuç nesnesidir: şema `sql`, ad = etiket, tür `SCRIPT`, veritabanı boş.
LLM çağrı özetindeki nesne adı "<etiket> (SCRIPT)" olur. Sonuç modeli
[object-review](../003-object-review/PRD.md) Requirement 13'tür.

Requirement 5: Metin incelemesi SQL Server'a hiçbir bağlantı açmaz. SQL Server erişilemezken de
başarıyla tamamlanır. "Nesne meta verisi gerekir" işaretli kuralların isteğine Mevcut davranış'taki not
eklenir; diğer kurallara meta veri bloğu eklenmez.

Requirement 6: Kural sürümü sabitleme, kural başına çağrı ve eşzamanlılık, 120.000 karakterlik metin ve
satır numaralama, iki parçalı analiz, yanıt çözümleme, satır referansı, uyarı birleştirme ve kural
düzeyi hata davranışı [object-review](../003-object-review/PRD.md) Requirement 4, 7, 8, 9, 10, 11, 12 ve
17'dir. Sınırı aşan metin Requirement 2 ile reddedildiği için metin koşumunda kesme olmaz. Satır
numaraları arındırılmış metne göredir.

Requirement 7: Canlı ilerleme API sözleşmesindeki olayları sırasıyla üretir; tanım okuma ve meta veri
olayları üretilmez. Her olay `kind: "script"`, `database: ""`, `object_index: 0`, `objects_total: 1`,
`schema: "sql"`, `type_code: "SCRIPT"` ve `object_label` alanlarını taşır.

Requirement 8: Durdurma ve bağlantı kopması [object-review](../003-object-review/PRD.md) Requirement
15'teki gibidir: 5 saniye içinde yeni LLM çağrısı başlamaz, koşum "iptal edildi" olur, kısmi sonuç
saklanmaz.

Requirement 9: Koşum kaydı [object-review](../003-object-review/PRD.md) Requirement 16'daki gibi
PostgreSQL'e yazılır; tür "metin", nesne sayısı 1'dir ve etiket saklanır. Arındırılmış yapıştırılan
metin, tek koşum nesnesinin incelenen SQL metni olarak sonuçlarla aynı işlemde yazılır; saklama süresi
boyunca (varsayılan 90 gün) tutulur, günlüğe yazılmaz ve yalnız koşumu başlatan kullanıcıya ve
`kural-yoneticisi` rolüne okunur (Decision 1).

Requirement 10: Koşum başlatma, nesne incelemesiyle aynı kullanıcı sayacını paylaşır
([object-review](../003-object-review/PRD.md) Requirement 18).

Requirement 11: Arayüz Mevcut davranış'taki sayfa, alan, sayaç ve düğme davranışını korur; canlı pencere,
"Analizi durdur" ve sonuç penceresi nesne incelemesiyle aynıdır. Yapıştırılan metin tarayıcının kalıcı
deposuna yazılmaz. Metin alanının yanında sabit bir not görünür: "Metin kurum içi LLM'e gönderilir ve
inceleme geçmişinde saklanır; kişisel veri ve parola içermemelidir." (Decision 3). Tüm ileti ve etiketler
Türkçedir.

Requirement 12: Metin incelemesi, nesne incelemesiyle aynı `services` katmanı inceleme hizmetini
kullanır; ayrı bir çözümleme veya birleştirme kopyası yoktur. Metin incelemesi giriş noktası SQL Server
uyarlayıcısına bağımlı değildir.

## API sözleşmesi

Ön ek `/api/dwhcodereview/v1`. Geçerli oturum belirteci (JWT) ve `inceleyici` veya `kural-yoneticisi`
rolü gerekir. Hata zarfı `{"detail":{"code":"...","message":"..."}}` biçimindedir.

- `POST /script-reviews` (yanıt `text/event-stream`) → istek: `sql` (metin), `label` (isteğe bağlı).
  Akış öncesi hatalar normal JSON yanıttır: `401`, `403`, `409 no_published_rule_set`, `422
  sql_text_empty` / `sql_text_too_long` / `label_too_long`, `429 rate_limited`.
- Olay sırası: `run_started` (`run_id`, `rule_version`, `objects_total: 1`), `object_start`, `sql_ready`
  (`sql_length`), `rules_batch_start`, `rule_start`, `llm_stream`, `rule_done`, `object_done`, `complete`
  (`run_id`, tek sonuç; bu oturumdaki gösterim için `source_sql`) veya `error` (`code`,
  `message`). Alanların anlamı [object-review](../003-object-review/PRD.md) API sözleşmesindedir.
- Kaldırılan: kaynaktaki akışsız `POST /api/review/script`.

## Güvenlik ve yetkilendirme

- Akış, ilk olaydan önce belirteç ve rol denetler; başarısızsa akış açılmaz.
- Metin yalnız istek gövdesindedir; URL'ye, günlüğe ve hata iletisine girmez.
- Yapıştırılan metin kişisel veri veya parola içerebilir. Yalnız onaylı kurum içi LLM ucuna gider
  ([llm-connection](../006-llm-connection/PRD.md)) ve koşumla saklanır (Requirement 9); sayfadaki sabit
  not kullanıcıyı uyarır, içerik taraması yapılmaz. `rules/55-prompt-veri-guvenligi.md` geliştirici
  asistanına yazılan mesajları kapsar; uygulamanın LLM çağrılarını taramaz (Decision 3).
- Metin hiçbir yerde çalıştırılmaz; yalnız inceleme için modele gönderilir.

## Veri ve geçiş

- Yeni tablo veya sütun yoktur; [object-review](../003-object-review/PRD.md) tablolarını tür "metin",
  etiket ve koşum nesnesinin incelenen SQL metni sütunuyla kullanır. Geçmiş ve dışa aktarım bu kayıtları
  [review-history-export](../005-review-history-export/PRD.md) ile okur.
- Kaynaktaki tarayıcı deposundaki geçmiş ve metinler taşınmaz.

## Gözlemlenebilirlik

- Koşum olayları [object-review](../003-object-review/PRD.md) Gözlemlenebilirlik bölümündeki alanları
  taşır; ek olarak metin uzunluğu ve iki parçalı analiz kullanılıp kullanılmadığı yazılır.
- Etiket günlüğe yazılmaz (kullanıcının yazdığı serbest metindir); metin, kod parçası ve LLM yanıtı
  yazılmaz.
- Ölçüm ve izler [object-review](../003-object-review/PRD.md) Gözlemlenebilirlik bölümündekilerdir;
  metin incelemesi `kind=script` etiketiyle sayılır. Etiket ve metin hiçbir ize veya ölçüme girmez.
  Tüketen test: `app/backend/tests/integration/test_telemetry_signals.py`.

## Dağıtım etkisi

- Yeni ortam ayarı: metin sınırı (120.000 karakter). Sır değildir; chart değer dosyasında belgelenir.
- Ingress istek gövdesi sınırı 120.000 karakterlik metni (UTF-8'de en çok yaklaşık 480 KB) kabul etmelidir.
- SSE için tamponlama ve okuma süresi gereği [object-review](../003-object-review/PRD.md) Dağıtım
  etkisindedir.

## Test stratejisi

- Çözümleme ve birleştirme altın testleri (golden test: sabit girdiye beklenen sabit çıktı) ortaktır ve
  [object-review](../003-object-review/PRD.md) Test stratejisinde tanımlıdır; bu PRD ayrı kopya eklemez.
- Hizmet testleri: SQL Server uyarlayıcısı test ikamesiyle sıfır çağrı; işaretli kurala not, işaretsize
  blok yok; etiket arındırma ve varsayılan; 45.000 karakter üstü metinde iki parçalı analiz; olay alanları.
- API testleri: akış öncesi `401`/`403`/`409`/`422`/`429`; 120.000 ve 120.001 karakter sınırı; olay sırası;
  yapıştırılan metnin günlükte bulunmaması ve veritabanında yalnız koşum nesnesinin incelenen SQL metni
  olarak bulunması; iptal edilen koşumda metnin saklanmaması.
- Ön yüz testleri: düğme durumları, sayaç, sınır iletisi, sabit not, durdurma, tarayıcı deposuna
  yazılmaması.

## Vektör ve gömme sözleşmesi (uygulanabilirse)

- Sağlayıcı / dağıtım sınırı: Uygulanamaz
- Model kimliği ve değişmez sürüm: Uygulanamaz
- Boyut ve normalleştirme: Uygulanamaz
- Uzaklık metriği ve indeks stratejisi: Uygulanamaz
- Getirim kalitesi/duyarlılık ve gecikme eşikleri: Uygulanamaz
- Kaynak sınıflandırması, en aza indirme ve saklama: Uygulanamaz
- Yeniden gömme, geçiş ve geri alma: Uygulanamaz

## Kabul kriterleri

- [ ] Acceptance 1: L1 — Otomatik testlerden geçti: SQL Server'a sıfır çağrı, meta veri notu, etiket,
  sonuç kimliği ve olay alanları hizmet testleri geçer (Requirement 3–7, 12).
- [ ] Acceptance 2: L1 — Otomatik testlerden geçti: boş metin, boyut ve etiket sınırları, akış öncesi
  yetki hataları, hız sınırı, iptal, metnin günlükte bulunmaması ve yalnız koşum kaydında saklanması
  API testleri geçer (Requirement 1–3, 8–10).
- [ ] Acceptance 3: L1 — Otomatik testlerden geçti: `OpenAPI` ve ön yüz tip sapması kapıları ile ön yüz
  testleri geçer (Requirement 2, 11).
- [ ] Acceptance 4: L2 — Gerçek istemci/ortamda doğrulandı: yerel PostgreSQL ve onaylı LLM ucuyla, SQL
  Server bağlantısı yokken tarayıcıda etiketli metin incelenir, canlı ilerleme ve satır referanslı
  bulgular görünür, sayfadaki sabit not görünür, koşum kaydında kural sürümü, etiket ve yapıştırılan
  metin bulunur, log çıktısında metin bulunmaz (Requirement 4–7, 9, 11).
- [ ] Acceptance 5: L2 — Gerçek istemci/ortamda doğrulandı: 120.001 karakterlik metin tarayıcıda
  gönderilemez ve API'de `422` alır; "Analizi durdur" sonrası 5 saniyeden sonra yeni LLM çağrı özeti
  oluşmaz (Requirement 2, 8).

## Kararlar

- Decision 1: Yapıştırılan metin koşumla birlikte saklama süresi boyunca (varsayılan 90 gün) saklanır;
  yalnız koşumu başlatan kullanıcı ve `kural-yoneticisi` görür, günlüğe yazılmaz (Requirement 9). Böylece
  geçmişten düzeltme yorumlu SQL dışa aktarımı yapılabilir
  ([review-history-export](../005-review-history-export/PRD.md)).
- Decision 2: 120.000 karakteri aşan metin `422` ile reddedilir (Requirement 2); kısmen incelenmiş metin
  eksiksiz sanılabileceği için kaynaktaki gibi kesilip incelenmez.
- Decision 3: Sayfada metnin kurum içi LLM'e gönderildiğini ve saklandığını söyleyen sabit bir Türkçe not
  gösterilir (Requirement 11); içerik taraması bu PRD'de yoktur.

## Teslim akışı

Belirtim → Plan → Görevler → Uygulama

## Riskler

- Yapıştırılan metin kişisel veri veya sır içerebilir; LLM'e gider ve 90 gün PostgreSQL'de saklanır.
  Sabit not uyarır ama içeriği denetlemez.
- Sınırın 200.000'den 120.000'e inmesi daha önce kabul edilen uzun metinleri reddeder.
- Saklanan metne erişim denetimi veya saklama işi bozulursa metin gereğinden geniş kitleye veya uzun süre
  açık kalır.
