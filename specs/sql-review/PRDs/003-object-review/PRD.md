# PRD — object-review

Status: Accepted

Version: 1.3.0

Acceptance date: 2026-10-15

Domain: [sql-review](../../DOMAIN.md)

Kabul kaydı: Proje sahibi bu PRD'yi 2026-10-02'de, bir koşumdaki nesne sayısı sınırının kaldırılması
ve süzgece uyan bütün nesnelerin tek adımda seçilebilmesi kararıyla (Decision 3) ve önceki sahip
kararlarıyla kabul etti. 1.3.0 revizyonunu (Requirement 15, Decision 9: açık
durdurma isteği) proje sahibi 2026-10-15'te kabul etti.

**1.x revizyon notu (2026-10-15):** [directory-login](../../../application-foundation/PRDs/001-directory-login/PRD.md) 1.3.0 Decision 14 ile `kural-yoneticisi` rolü kaldırıldı; kullanıcılar `inceleyici` (arayüzde "Kullanıcı") ve süper yöneticidir. Bu belgede kural yöneticisine verilen yetkiler (taslağı düzenleme ve yayımlama, bağlantı ayarları, LLM çağrı özetleri, tüm incelemeleri görme) süper yöneticidedir; "inceleyici" geçen yerler her kullanıcıyı anlatır.

## Amaç

İnceleyici, SQL Server'daki bir veya daha çok veritabanından nesne (saklı yordam, görünüm, fonksiyon)
seçer ve bunları en son yayımlanmış kural sürümüne göre kurum içi LLM (büyük dil modeli) ile inceletir.
İnceleme sürerken her nesne ve her kural için canlı ilerleme görür; bitince her kural için sonucu ve
satır referanslı bulguları görür. Koşum, sonuçları, incelenen SQL metni ve kullanılan kural sürümü
sunucuda saklanır.

## Aktörler ve sonuçlar

- **İnceleyici (`inceleyici`):** Veritabanı ve nesne seçer, koşum başlatır, canlı ilerlemeyi izler,
  durdurabilir, sonuçları görür. Ölçülebilir sonuç: seçilen her nesne için yayımlanmış sürümdeki her
  kurala tam bir kural sonucu (veya nesne düzeyinde açık hata) döner.
- **Kural yöneticisi (`kural-yoneticisi`):** İnceleyicinin yapabildiği her şeyi yapar; bu PRD ona ek
  yetki vermez.
- **İşletim ekibi:** Eşik ve sınır ayarlarını ortam yapılandırmasından verir; uygulama içi rol değildir.

## Değişmezler ve sınırlar

- Koşum yalnız en son yayımlanmış kural sürümünü kullanır; sürüm koşum başında bir kez sabitlenir ve
  koşum kaydında saklanır. Kural kümesinin sahibi [rule-management](../001-rule-management/PRD.md).
- SQL Server'a yalnız salt okunur katalog ve tanım sorguları gider; bağlantı ve sorgular
  [sql-server-connection](../002-sql-server-connection/PRD.md) PRD'sindedir.
- LLM'e gidiş, ağ politikası, yeniden deneme, eşzamanlılık sınırının değeri ve LLM çağrı özetleri
  [llm-connection](../006-llm-connection/PRD.md) PRD'sindedir.
- Geçmiş listesi ve CSV/SQL dışa aktarma [review-history-export](../005-review-history-export/PRD.md)
  PRD'sindedir. Giriş ve roller [directory-login](../../../application-foundation/PRDs/001-directory-login/PRD.md)
  PRD'sindedir.
- Ham SQL metni, kod parçası ve ham LLM yanıtı günlüğe (log) yazılmaz. İncelenen SQL metni koşumla
  birlikte PostgreSQL'de saklama süresi boyunca (varsayılan 90 gün) tutulur ve yalnız koşumu başlatan
  kullanıcıya ve `kural-yoneticisi` rolüne açıktır (Decision 2).
- Canlı ilerleme SSE ile gelir (SSE: sunucunun tarayıcıya tek yönlü, sürekli olay gönderdiği bağlantı).
  Akış başlamadan oturum ve rol denetlenir; bağlantı koparsa iş durur.
- Arayüz yalnız Türkçedir.

## Mevcut davranış

Kaynak: `~/codes/dwhcodereview`. "Hedefte" notu olan maddeler bilinçli davranış değişikliğidir.

- **Seçim** (`frontend/src/pages/ReviewPage.tsx`, `components/ObjectTable.tsx`, `backend/main.py`
  `GET /api/databases`, `GET /api/objects`, `backend/db/queries.py`): Veritabanı listesi yalnız çevrimiçi
  veritabanlarını ada göre verir. Nesne listesi `P`, `V`, `FN`, `IF`, `TF`, `SF` türündeki kullanıcı
  nesnelerini şema ve ada göre sıralı verir; sütunlar şema, ad, tür, oluşturulma, son değişiklik.
  Metin araması (şema/ad/tür içinde, büyük-küçük harf duyarsız) ve tür filtresi tarayıcıda, tarih filtresi
  ("bu günden sonra oluşturulan veya değişen") sunucuda uygulanır. Veritabanı değiştirilince önceki
  seçimler korunur; bir koşum birden çok veritabanından nesne içerebilir. **Hedefte:** filtrelerin
  tümü sunucuda uygulanır ve liste sayfalı döner.
- **Koşum** (`backend/services/review_orchestrator.py`): Seçilen tüm nesneler aynı anda işlenir. Her
  nesnede tanım okunur, gerekirse nesne meta verisi alınır, sonra `review_sql` çağrılır. Tanım okunamazsa
  nesne `error` ile döner ve diğer nesneler sürer. Hata metni ham istisna metnini (`Database error: ...`)
  içerir. **Hedefte:** istemciye yalnız kararlı kod ve güvenli Türkçe ileti gider.
- **Kural sürümü** (`backend/services/rules_store.py`): Yayımlanmış kurallar koşum içinde birkaç kez ayrı
  ayrı okunur; dosya yoksa varsayılan kurallar kullanılır; yayımlanmış kural yoksa nesne boş sonuçla döner.
  **Hedefte:** sürüm bir kez sabitlenir; yayımlanmış sürüm yoksa koşum başlamaz.
- **Kural başına çağrı ve eşzamanlılık** (`backend/services/llm_review.py` `review_sql`): Her kural için
  ayrı LLM çağrısı yapılır; sıra önce kritik sonra normal kurallardır. Eşzamanlılık sınırı
  (`sql_review_max_concurrent_rules`, varsayılan 6) her nesne için ayrı uygulanır; 10 nesnede 60 çağrı
  aynı anda gidebilir. **Hedefte:** sınır koşumun tamamına uygulanır (Decision 4).
- **Metin sınırı:** İncelenen metin sessizce ilk 120.000 karakterle kesilir. **Hedefte:** kesilirse nesne
  sonucunda uyarı görünür.
- **İki parçalı analiz** (`_split_sql_into_two_parts`, `_two_part_scope_notices`,
  `_merge_two_part_single_rule`): Metin eşik uzunluğu (`sql_review_two_part_threshold_chars`, varsayılan
  45.000 karakter) aşarsa her kural için iki çağrı yapılır ve sonuç birleştirilir (Requirement 9).
- **Yanıt çözümleme ve birleştirme** (`parse_review_response`, `_merge_violations_format`,
  `_merge_rule_results`, `_line_ref_from_violation_item`, `_infer_line_reference_from_snippet`) ve
  bunların testleri (`backend/tests/test_parse_review_response.py`): Requirement 10–12'de korunur.
- **Canlı ilerleme** (`backend/main.py` `POST /api/review/stream`, `frontend/src/reviewProgress.ts`,
  `GlobalReviewProgress.tsx`, `LiveReviewModal.tsx`): Olaylar `data:` satırında `phase` alanlı JSON
  olarak gelir; son olay `complete` (tüm sonuçlar) veya `error`. Canlı pencere, koşum sürerken yalnız
  "Analizi durdur" ile kapanır. Akış öncesinde kimlik denetimi yalnız isteğe bağlı sabit API anahtarıdır.
  **Hedefte:** oturum belirteci ve rol denetimi zorunludur.
- **İptal** (`contexts/ReviewAnalysisContext.tsx`): "Analizi durdur" isteği keser; sunucu bağlantı
  kopunca işi iptal eder; arayüz "İnceleme durduruldu." gösterir ve kısmi sonuç göstermez.
- **Sonuçlar** (`ReviewResults.tsx`, `ReviewResultsModal.tsx`): Nesne kartlarında kural sonuçları ve
  bulgular gösterilir; kullanıcı bulgu veya kural sonucunu "Yanlış pozitif" işaretleyebilir (yalnız
  tarayıcı belleğinde). Sonuçlar tarayıcı deposuna (`analysisHistoryStorage.ts`) yazılır. **Hedefte:**
  sonuçlar ve incelenen SQL metni PostgreSQL'de saklanır; tarayıcı deposu kullanılmaz; yanlış pozitif
  işareti sunucuda saklanır (Decision 5).
- **Düzeltme önerisi:** Kaynakta ayrı bir düzeltme önerisi alanı yoktur; bulgunun açıklaması (`reason`)
  kullanılır ve sistem istemi modelden öneri yazmamasını ister. **Hedefte:** aynı kalır (Decision 1).
- **Hız sınırı** (`backend/main.py`): İnceleme uçlarında IP başına 60 saniyede 30 istek. **Hedefte:**
  sınır oturumdaki kullanıcıya uygulanır.
- **Akışsız uç:** `POST /api/review` arayüzde kullanılmaz. **Hedefte:** kaldırılır.

## İşlevsel gereksinimler

Requirement 1: Veritabanı listesi bağlantı hesabının erişebildiği bütün çevrimiçi veritabanlarını,
sistem veritabanları olmadan, ada göre sıralı döndürür ([sql-server-connection](../002-sql-server-connection/PRD.md) Requirement 7). SQL Server
erişilemezse veya sorgu başarısızsa yanıt o PRD'nin Requirement 8 hata sınıfıdır (örneğin `503`
`sql_server_unreachable`, zaman aşımında `504` `sql_timeout`); arayüz Türkçe ileti ve "Listeyi yenile"
düğmesi gösterir.

Requirement 2: Nesne listesi seçilen veritabanında yalnız `P`, `V`, `FN`, `IF`, `TF`, `SF` türündeki
kullanıcı nesnelerini şema, ad, tür, tür kodu, oluşturulma ve son değişiklik tarihiyle döndürür. Sıra
şema, ad, tür kodudur. Metin filtresi şema/ad/tür içinde büyük-küçük harf duyarsız arar; tür filtresi tür
koduyla eşleşir; tarih filtresi oluşturulma veya son değişikliği o günün başlangıcına eşit ya da sonra
olan nesneleri bırakır. Yanıt sayfalama bilgisi (sayfa, sayfa boyutu, toplam) taşır.

Requirement 3: İnceleyici bir koşuma farklı veritabanlarından nesne ekleyebilir; veritabanı değişince
önceki seçimler korunur ve seçim sayısı ile veritabanı sayısı gösterilir. Her seçim veritabanı, şema, ad
ve tür kodu taşır. Bir koşumdaki nesne sayısı için ürün sınırı yoktur (Decision 3). Tablo başlığındaki
kutu yalnız listelenen sayfadaki nesneleri seçer. "Süzgece uyan N nesnenin tümünü seç" eylemi, seçili
veritabanında geçerli arama, tür ve tarih süzgecine uyan bütün nesneleri, sayfalar arasında dolaşmadan
seçime ekler; arayüz bunun için nesne listeleme ucunu en büyük sayfa boyutuyla (500) sayfa sayfa çağırır,
toplanan sayıyı gösterir, işlem yarıda bırakılabilir ve binlerce nesne tabloya çizilmez. "Seçimi
temizle" bütün seçimi kaldırır. Boş seçim veya izinli küme dışındaki tür kodu `422` ile, sistem
veritabanı (`master`, `tempdb`, `model`, `msdb`) `403` `database_not_allowed` ile reddedilir. Tek
isteğin gövdesi teknik olarak en çok 10.000 seçim taşır; bu bir ürün sınırı değil, istek boyutunun
sonlu kalması için konmuş teknik sınırdır (Decision 7). Daha uzun liste `422` `invalid_request` alır ve
arayüz bunu "teknik sınır" olarak adlandırıp incelemeyi başlatmaz.

Requirement 4: Koşum başında en son yayımlanmış kural sürümü bir kez okunur ve koşum kaydına yazılır;
koşumdaki tüm nesneler ve tüm kurallar bu sürümle incelenir. Yayımlanmış sürüm yoksa koşum başlamaz;
yanıt `409` ve `no_published_rule_set` kodudur ([rule-management](../001-rule-management/PRD.md) ile
aynı kod).

Requirement 5: Her nesnenin tanımı okunur. Tanım boşsa nesne `object_not_found` koduyla ve "Tanım
alınamadı (nesne yok veya yetki yok)." iletisiyle; okuma başarısızsa
[sql-server-connection](../002-sql-server-connection/PRD.md) Requirement 8 sınıfıyla ve güvenli Türkçe
iletiyle döner. İki durumda da diğer nesneler incelenmeye devam eder.

Requirement 6: Sabitlenen sürümde en az bir kural "nesne meta verisi gerekir" işaretliyse meta veri nesne
başına bir kez alınır ve yalnız işaretli kuralların isteğine eklenir. Meta veri alınamazsa inceleme
sürer; işaretli kuralların isteğine "özet alınamadı, yalnız SQL metnine güven" notu eklenir.

Requirement 7: Her kural için ayrı LLM çağrısı yapılır; sonuç sırası önce kritik, sonra normal
kurallardır ve yayımlanmış sürümdeki sırayı izler. Koşumdaki nesne sayısından bağımsız olarak, bir
koşumda aynı anda süren LLM çağrısı sayısı koşum sınırını, süreçteki tüm koşumların toplamı süreç geneli
sınırı hiçbir anda aşmaz; iki sınırın değeri [llm-connection](../006-llm-connection/PRD.md) Requirement
7'dedir (Decision 4).

Requirement 8: İncelenen metin en fazla 120.000 karakterdir; fazlası incelenmez ve nesne sonucunda
"Metnin yalnız ilk 120.000 karakteri incelendi." uyarısı görünür. Modele giden metin `L001` biçiminde
satır numaralıdır (numara genişliği en az 3 hane).

Requirement 9: Metin, ayarlanabilir eşiği (varsayılan 45.000 karakter) aşarsa her kural için iki parçalı
analiz yapılır: çok satırlı metin satır sayısının yarısından, tek satırlı metin karakter ortasından
bölünür; ikinci parçanın numaraları özgün satır numarasından başlar; her parçaya "yalnız bu bölüme uygula"
notu eklenir; iki çağrı aynı eşzamanlılık yuvasında sırayla yapılır ve LLM çağrı özetinde kural kimliği
`#1/2` ve `#2/2` ekini taşır. Birleştirme şöyledir: iki parça da başarısızsa `UNKNOWN`; biri başarısızsa
diğerinin sonucu ve "Parça n/2 LLM isteği başarısız; yalnızca parça m değerlendirildi." uyarısı;
ikisinde toplam bulgu varsa kod parçası ve açıklamanın ilk 200 karakterine göre tekrarlar ayıklanır ve
sonuç `FAIL` olur; bulgu yoksa biri `UNKNOWN` ise `UNKNOWN`, biri `FAIL` ise `FAIL`, ikisi
`NOT_APPLICABLE` ise `NOT_APPLICABLE`, aksi halde `PASS`.

Requirement 10: Yanıt çözümleme kaynak davranışını korur: kod çiti (```) atılır; metindeki ilk geçerli
JSON değeri alınır, öncesindeki ve sonrasındaki yazı yok sayılır; `violations` alanı dizi veya dizi
metni olabilir; kökte dizi gelirse öğeler `rule_id` taşıyorsa kural sonucu biçimi, `rule_code` taşıyorsa
ihlal biçimi sayılır; kural sonucu dizisi `rule_results`, `rule_checks`, `results`, `rules`, `checks` gibi
anahtarlarda veya `data`/`response`/`output`/`result`/`payload`/`message` altında aranır. İhlal biçiminde
`rule_code` boş öğe yalnız tek kurallı istekte kabul edilir; "ihlal değil", "ihlal sayılmaz", "kapsam
dışı ... uygulanmaz" gibi ifadeler içeren öğe bulgu sayılmaz; bilinmeyen kural kodları uyarıyla yok
sayılır; önem kritik kuralda `HIGH`, normal kuralda `LOW` olur. Kural sonucu biçiminde geçersiz durum
`UNKNOWN`, geçersiz önem `LOW` olur. Hiç çözülemeyen yanıt kuralı `UNKNOWN` yapar.

Requirement 11: Bulgunun satır referansı şu sırayla bulunur: modelin `line_reference` alanı (`L012`
→ "Satır 12", `L012–L015` → "Satır 12–15"); `line_numbers` listesi (ardışıksa aralık, değilse virgüllü
liste); `line_number`; en son kod parçasının kaynak metinde aranması (ilk 5 dolu satır, boşluklar
sadeleştirilerek). Bulunamazsa satır referansı boş kalır. Satır numaraları her zaman özgün metne göredir.

Requirement 12: Nesne uyarısı (`parse_warning`) kural uyarılarını "[KuralKimliği] uyarı" biçiminde
birleştirir; aynı bağlantı hatasını alan kurallar tek satırda toplanır; eski çıktı biçimine ait uyarılar
gösterilmez.

Requirement 13: Sonuç modeli: nesne başına veritabanı, şema, ad, tür, kural sonuçları, bulgular, hata ve
uyarı. Kural sonucu: kural kimliği, öncelik grubu, durum (`PASS` uyumlu, `FAIL` ihlal var,
`NOT_APPLICABLE` kapsam dışı, `UNKNOWN` değerlendirilemedi), önem, karar dayanağı, açıklama (en çok 500
karakter), satır referansı, kod parçası (en çok 500 karakter). Bulgu: kural kimliği, önem, açıklama
("nesne adı: neden", en çok 4.000 karakter), satır referansı, kod parçası (en çok 4.000 karakter).
Arayüz `NOT_APPLICABLE` sonucunu kaynaktaki gibi uyumlu grubunda gösterir.

Requirement 14: Canlı ilerleme, API sözleşmesindeki olayları sırasıyla üretir. `llm_stream` olayı bir
çağrı için en sık 0,2 saniyede bir gelir ve yalnız belirteç (token) ve karakter sayısı taşır; model
yanıtının içeriğini taşımaz. Arayüz nesne kartlarında aşama, kural sayacı ve kural durumunu gösterir.
Canlı pencere yalnız o anda incelenen nesneleri ve son biten 20 nesneyi listeler; diğerleri "n / toplam
nesne tamamlandı" ve hata sayacıyla özetlenir. Koşum 50 nesneden büyükse `complete` olayı sonuçları
taşımaz (`results_omitted: true`); arayüz sonuçları saklanan koşumdan,
[review-history-export](../005-review-history-export/PRD.md) Requirement 3'teki sayfalı uçla açar.

Requirement 15: İnceleyici "Analizi durdur" dediğinde veya bağlantı koptuğunda sunucu 5 saniye içinde
yeni LLM çağrısı başlatmayı bırakır ve süren çağrıları keser. Koşum "iptal edildi" durumuyla saklanır,
kısmi sonuç saklanmaz ve gösterilmez; arayüz "İnceleme durduruldu." yazar. "Analizi durdur" ayrıca açık bir
durdurma isteği gönderir (`POST /review-runs/{id}/cancel`); durdurma, araya giren vekil sunucunun
bağlantı kapanışını arka uca iletmesine bağlı kalmaz. Arayüz istek sürerken "Durduruluyor…" yazar ve
sunucu onaylayınca durumu gösterir (Decision 9).

Requirement 16: Koşum başlarken PostgreSQL'e koşum kaydı (dış kimlik `public_id`, başlatan kullanıcı,
kural sürümü, tür "nesne", nesne sayısı, durum "sürüyor", başlangıç zamanı) yazılır. Başarıyla biten
koşumun nesne sonuçları, kural sonuçları, bulguları ve her nesnenin incelenen SQL metni (modele giden,
satır numarası eklenmemiş metin; en çok 120.000 karakter) tek işlemde yazılır ve durum "tamamlandı"
olur. Beklenmeyen hata "hata", iptal "iptal edildi" durumudur; bitiş zamanı ve hata varsa kararlı hata
kodu ile güvenli Türkçe ileti koşum kaydına yazılır. Uygulama açılışında "sürüyor" kalmış koşumlar
"yarıda kesildi" olarak işaretlenir. Saklanan SQL metni saklama süresi boyunca (varsayılan 90 gün,
[review-history-export](../005-review-history-export/PRD.md) Requirement 6) tutulur, günlüğe yazılmaz
ve yalnız koşumu başlatan kullanıcıya ve `kural-yoneticisi` rolüne okunur (Decision 2).

Requirement 17: Kural düzeyindeki LLM hatası kuralı `UNKNOWN` yapar; açıklama LLM adresini, ayar dosyası
adını veya sunucu ayrıntısını içermeyen kısa Türkçe iletidir. Bir kuralın hatası aynı nesnenin diğer
kurallarını durdurmaz.

Requirement 18: Koşum başlatma, oturumdaki kullanıcı başına 60 saniyede en çok 30 istekle sınırlıdır;
aşılırsa `429` ve `rate_limited` kodu döner; sayaç IP adresine göre değil kullanıcıya göredir. Pencere ve
sayı ortam ayarıdır.

Requirement 19: Sonuç penceresi koşum bitince açılabilir; bulgu ve kural sonucu "Yanlış pozitif"
işaretlenebilir ve işaret [review-history-export](../005-review-history-export/PRD.md) Requirement 4
ucuyla sunucuda saklanır (Decision 5). Tüm ileti ve etiketler Türkçedir.

Requirement 20: Kaynaktaki tek büyük `llm_review.py` katmanlara bölünür: alan modelleri (kural sonucu,
bulgu, durum ve önem değerleri) `domain` katmanında; koşum yönetimi, istem (prompt) oluşturma, iki
parçaya bölme, yanıt çözümleme, birleştirme ve satır referansı çıkarımı `services` katmanında; LLM'e HTTP
çağrısı `infrastructure` uyarlayıcısında. Çözümleme ve birleştirme işlevleri ağ, veritabanı ve dosya
erişimi yapmaz.

Requirement 21: Koşum büyük seçimlerde de güvenli kalır; belleği seçimin büyüklüğüyle değil, aynı
anda işlenen nesne sayısıyla ve biten nesnelerin saklanacak sonuçlarıyla büyür.

- Aynı anda en çok koşumun LLM eşzamanlılık sınırı kadar nesne işlenir
  ([llm-connection](../006-llm-connection/PRD.md) Requirement 7, varsayılan 6; Decision 8). Bir nesnenin
  tanımı ve meta verisi ancak sırası geldiğinde SQL Server'dan okunur; sıradaki nesnelerin SQL metni
  bellekte tutulmaz. Nesneler seçim sırasıyla başlar; nesne içi olay sırası (Requirement 14) ve
  Requirement 7'deki iki LLM sınırı değişmez.
- Olay kuyruğu en çok 256 olay tutar; okuyan bağlantı yavaşsa koşum onu bekler, olaylar bellekte
  birikmez.
- İptal ve kopan bağlantı (Requirement 15) aynı çalışır: sırası gelmemiş nesneler hiç okunmaz.
- Biten koşum Requirement 16'daki tek işlemde, 100'er nesnelik parçalar hâlinde yazılır.
- Her nesnenin sonucu ve incelenen SQL metni koşum bitene kadar sunucu belleğinde durur; bu, seçimle
  birlikte büyüyen tek paydır (Riskler).

## API sözleşmesi

Ön ek `/api/dwhcodereview/v1`. Tüm uçlar geçerli oturum belirteci (JWT) ve `inceleyici` veya
`kural-yoneticisi` rolü ister. Hata zarfı `{"detail":{"code":"...","message":"..."}}` biçimindedir.

- `GET /databases` → veritabanı adları ve sayfalama bilgisi. Hata: `503 sql_connection_not_configured`
  ve [sql-server-connection](../002-sql-server-connection/PRD.md) Requirement 8 sınıfları (`504
  sql_timeout`).
- `GET /databases/{database}/objects?q=&type=&from_date=&page=&page_size=` → nesne satırları (`schema`,
  `name`, `type`, `type_code`, `created_at`, `last_modified`) ve sayfalama bilgisi. `database` 1–128,
  `q` en çok 200 karakterdir. Hata: `403 database_not_allowed`, `422` geçersiz tarih/tür/uzunluk,
  `503`/`504` Requirement 8 sınıfları.
- `POST /object-reviews` (yanıt `text/event-stream`) → istek: `selections[]` (`database`, `schema`,
  `name`, `type_code`); nesne sayısı için ürün sınırı yoktur, liste teknik olarak en çok 10.000 öğe
  taşır. Akış öncesi hatalar normal JSON yanıttır: `401`, `403` (rol veya
  `database_not_allowed`), `409 no_published_rule_set`, `422` (`selection_empty`,
  `object_type_invalid`, teknik sınırı aşan ya da biçimsiz istekte `invalid_request`), `429
  rate_limited`. Akış başladıktan sonra her olay tek `data:`
  satırında `phase` alanlı JSON'dur:
  - `run_started` (yeni): `run_id` (`public_id`), `rule_version`, `objects_total`.
  - Nesne olayları (`database`, `object_index`, `objects_total`, `object_label`, `schema`, `name`,
    `type_code` ile): `object_start`, `definition_fetch`, `sql_ready` (`sql_length`), `metadata_fetch`,
    `metadata_ready`, `object_error` (`code`, `message`), `object_done`.
  - Kural olayları: `rules_batch_start` (`rules_total`), `rule_start` (`rule_id`, `tier`, `rule_index`,
    `sql_two_part`), `llm_stream` (`rule_id`, `completion_tokens`, `total_chars`), `rule_done` (`ok`,
    `completion_tokens`, `total_chars`).
  - `complete`: `run_id`, `results_omitted` ve Requirement 13'teki sonuç listesi; bu oturumdaki
    gösterim için nesnenin SQL metni (`source_sql`) de gelir. Aynı metin Requirement 16 ile koşumda
    saklanır. Koşum 50 nesneden büyükse `results` boştur ve `results_omitted` `true`'dur
    (Requirement 14).
  - `error`: `code`, `message`; akış kapanır, koşum "hata" olur.
- Kaldırılan: kaynaktaki akışsız `POST /api/review`. Koşum ve sonuçların sonradan okunması
  [review-history-export](../005-review-history-export/PRD.md) PRD'sindedir.

## Güvenlik ve yetkilendirme

- Akışlı uç, ilk olayı göndermeden önce belirteci ve rolü denetler; başarısızsa akış hiç açılmaz.
- Belirteç yalnız `Authorization` başlığındadır; URL'ye belirteç, SQL metni veya nesne tanımı konmaz.
- Hata iletileri istisna metni, bağlantı dizesi, LLM adresi veya sunucu yolu içermez.
- Veritabanı ve nesne adları SQL Server sorgularına yalnız parametre olarak gider
  ([sql-server-connection](../002-sql-server-connection/PRD.md)).
- İncelenen kod hiçbir yerde çalıştırılmaz; yalnız metin olarak modele gönderilir.

## Veri ve geçiş

- Yeni tablolar (Alembic göçüyle): inceleme koşumu, koşum nesnesi, kural sonucu, bulgu. Bu PRD bu
  tabloların ve sütunlarının sahibidir: koşumda `public_id`, başlatan kullanıcı, tür (`nesne` veya
  `metin`), metin koşumunun etiketi, kural sürümü, nesne sayısı, durum, başlangıç ve bitiş zamanı, hata
  kodu ve iletisi; koşum nesnesinde veritabanı, şema, ad, tür, nesne hatası, uyarı ve incelenen SQL
  metni. [script-review](../004-script-review/PRD.md) aynı tablolara metin koşumunu yazar;
  [review-history-export](../005-review-history-export/PRD.md) bunları okur, yalnız yanlış pozitif
  işaret sütunlarını ekler ve koşumu siler. Koşum kaydı yayımlanmış kural sürümüne bağlanır
  ([rule-management](../001-rule-management/PRD.md)); LLM çağrı özetleri koşuma bağlanır
  ([llm-connection](../006-llm-connection/PRD.md)).
- İncelenen SQL metni ve bulgulardaki kod parçaları saklama süresi boyunca saklanır (Requirement 16).
- Koşumdaki nesne sayısı sütunu yalnız "en az 1" denetimi taşır (göç `202610020001`). Göç yalnız
  genişleticidir: denetim gevşer, satır değişmez, önceki uygulama sürümü bu şemayla çalışır. Geri alma,
  50'den çok nesneli koşum saklıyken hata verip durur, çünkü önceki denetim o satırı kabul etmez.
- Kaynaktaki tarayıcı deposundaki geçmiş taşınmaz; sunucu geçmişi boş başlar.

## Gözlemlenebilirlik

- Yapılandırılmış günlük: koşum başladı/bitti/iptal/hata olayları; `run_id`, kullanıcı kimliği, kural
  sürümü, nesne ve kural sayısı, süre, `UNKNOWN` sonuç sayısı.
- Nesne düzeyinde yalnız kimlik bilgisi (veritabanı, şema, ad) ve hata kodu yazılır. SQL metni, kod
  parçası, meta veri metni ve LLM yanıtı yazılmaz.
- Ölçümler: `dwhcodereview_review_runs_started_total{kind}`,
  `dwhcodereview_review_runs_finished_total{kind,status}`,
  `dwhcodereview_review_run_duration_seconds{kind,status}`, kural başına LLM yanıtı alınıp
  alınmadığını sayan `dwhcodereview_review_rule_calls_total{kind,outcome}` ve tamamlanan koşumların
  kural sonuçlarını sayan `dwhcodereview_review_rule_results_total{kind,status}`. `kind` `object`
  veya `script`; bitişte `status` `completed`, `failed`, `cancelled` veya `interrupted`; `outcome`
  `ok` veya `failed`; kural sonucunda `status` `PASS`, `FAIL`, `NOT_APPLICABLE` veya `UNKNOWN`.
  Kullanıcı, koşum, nesne ve veritabanı ölçüme girmez.
- İz (trace): koşum başına `review_run` aralığı (tür, nesne ve kural sayısı, son durum); isteğin
  sunucu aralığına, altındaki LLM çağrılarına ve PostgreSQL komutlarına bağlanır. Ortak kurallar ve
  saklama süresi [application-foundation alanında](../../../application-foundation/DOMAIN.md)
  tanımlıdır. Tüketen test: `app/backend/tests/integration/test_telemetry_signals.py`.

## Dağıtım etkisi

- Yeni göç; yeni ortam ayarları: iki parça eşiği (45.000), metin sınırı (120.000), hız sınırı penceresi ve
  sayısı. Sır değildir; chart değer dosyasında belgelenir.
- Ingress ve vekil sunucu SSE yanıtını tamponlamamalı (`X-Accel-Buffering: no`) ve okuma süresi en uzun
  LLM çağrısını karşılamalıdır ([llm-connection](../006-llm-connection/PRD.md)).
- İstek gövdesi boyutu: 10.000 seçimlik istek ortalama ad uzunluğuyla yaklaşık 1 MB'tır. Yerel vekil
  4 MB kabul eder. Chart'ın ingress kaynağı gövde boyutu için ek açıklama taşımaz; kümede ingress
  denetleyicisinin varsayılanı (ingress-nginx'te 1 MB) geçerlidir ve daha büyük istek uygulamaya
  ulaşmadan `413` alır; arayüz bunu "seçim tek istekte kabul edilen boyutu aşıyor" iletisiyle gösterir.
- Yeni ayar yoktur; aynı anda işlenen nesne sayısı mevcut `DWHCODEREVIEW_LLM_MAX_CONCURRENT_CALLS`
  ayarından gelir.

## Test stratejisi

- **Altın testler (golden test: sabit girdiye beklenen sabit çıktıyı karşılaştıran test):** Kaynaktaki
  `test_parse_review_response.py` testlerinin tamamı aynen taşınır: sonrasında yazı olan JSON, önünde
  yazı olan JSON, `violations` metin dizisi, kod çiti sonrası yazı, kökte `rule_code` dizisi, kökte boş
  dizi, satır numaralandırma başlangıcı, satırdan ikiye bölme, iki parçanın `PASS` birleşimi.
- Eklenen altın testler: `L012`/`L012–L015`/`line_numbers`/kod parçasından satır çıkarımı; "ihlal
  değil" süzgeci; boş `rule_code` tek ve çok kurallı; bilinmeyen kural kodu uyarısı; kural sonucu
  biçiminde geçersiz durum ve önem; iki parçada tek parça hatası, iki parça hatası, tekrar ayıklama; uyarı
  birleştirme.
- Hizmet testleri LLM test ikamesiyle (sahte uç): sürüm sabitleme, meta veri yalnız işaretli kurala,
  koşum ve süreç geneli eşzamanlılık üst sınırı, iki parça çağrı sayısı, iptalde yeni çağrı olmaması,
  kalıcılık (incelenen SQL metni dahil) ve durumlar.
- API testleri: akış öncesi `401`/`403`/`409`/`422`/`429`; 51 nesnelik ve 1.000 nesnelik seçimin
  tamamlanıp saklanması; teknik sınırı aşan isteğin `invalid_request` alması; aynı anda işlenen nesne
  sayısının sınırı aşmaması ve tanımların yalnız sırası gelen nesneler için okunması (sahte kataloğun
  eşzamanlı çağrı sayacıyla); yavaş okuyan bağlantının koşumu bekletmesi; büyük koşumda iptal;
  `complete` olayının 50 nesneye kadar sonuç taşıması; olay sırası; günlükte SQL metni olmaması; göçün
  geri alınıp yeniden uygulanması.
- Ön yüz testleri: filtreler, çoklu veritabanı seçimi, 50'den çok nesne seçimi, süzgece uyan bütün
  nesnelerin sayfalar arasından seçilmesi, sayının gösterilmesi, yarıda bırakma ve temizleme, teknik
  sınır iletisi, canlı pencerenin yalnız işlenen ve son biten nesneleri listelemesi, büyük koşumda
  sonuçların geçmişten açılması, olay birleştirme, durdurma, Türkçe hata iletileri.

## Vektör ve gömme sözleşmesi (uygulanabilirse)

- Sağlayıcı / dağıtım sınırı: Uygulanamaz
- Model kimliği ve değişmez sürüm: Uygulanamaz
- Boyut ve normalleştirme: Uygulanamaz
- Uzaklık metriği ve indeks stratejisi: Uygulanamaz
- Getirim kalitesi/duyarlılık ve gecikme eşikleri: Uygulanamaz
- Kaynak sınıflandırması, en aza indirme ve saklama: Uygulanamaz
- Yeniden gömme, geçiş ve geri alma: Uygulanamaz

## Kabul kriterleri

- [ ] Acceptance 1: L1 — Otomatik testlerden geçti: taşınan ve eklenen altın testler geçer
  (Requirement 8–13).
- [ ] Acceptance 2: L1 — Otomatik testlerden geçti: LLM test ikamesiyle sürüm sabitleme, meta veri,
  eşzamanlılık üst sınırı, iki parçalı analiz, kalıcılık ve durum testleri geçer (Requirement 4–7, 9, 16,
  17).
- [ ] Acceptance 3: L1 — Otomatik testlerden geçti: akış öncesi yetki ve doğrulama hataları, nesne
  sınırı olmadan 51 ve 1.000 nesnelik koşumların tamamlanması, aynı anda işlenen nesne sayısının ve
  olay kuyruğunun sınırlı kalması, hız sınırı, olay sırası, iptal ve günlükte SQL metni bulunmaması API
  testleri geçer (Requirement 3, 14, 15, 18, 21).
- [ ] Acceptance 4: L1 — Otomatik testlerden geçti: katman yapısı, `OpenAPI` ve ön yüz tip sapması
  kapıları ile ön yüz testleri geçer (Requirement 1–3, 19, 20).
- [ ] Acceptance 5: L2 — Gerçek istemci/ortamda doğrulandı: yerel PostgreSQL, test SQL Server'ı ve onaylı
  LLM ucuyla tarayıcıda iki veritabanından nesne seçilip koşum çalışır, canlı ilerleme görünür, satır
  referanslı bulgular gösterilir; koşum kaydında kural sürümü ve her nesnenin incelenen SQL metni
  bulunur, log çıktısında SQL metni bulunmaz (Requirement 1–7, 11, 13, 14, 16).
- [ ] Acceptance 6: L2 — Gerçek istemci/ortamda doğrulandı: tarayıcıda "Analizi durdur" sonrasında 5
  saniyeden sonra yeni LLM çağrı özeti oluşmaz ve koşum "iptal edildi" görünür (Requirement 15).
- [ ] Acceptance 7: L2 — Gerçek istemci/ortamda doğrulandı: gerçek SQL Server ve onaylı LLM ucuyla
  tarayıcıda bir veritabanının süzgece uyan bütün nesneleri (50'den çok) seçilip koşum çalışır; canlı
  pencere yalnız işlenen ve son biten nesneleri listeler, backend belleği koşum boyunca sınırının
  altında kalır, sonuçlar geçmişte sayfa sayfa açılır ve dışa aktarılır (Requirement 3, 14, 21).

## Kararlar

- Decision 1: Bulguda ayrı bir "düzeltme önerisi" alanı yoktur; düzeltme bilgisi bulgu açıklamasıdır
  ve sistem istemi kaynaktaki gibi kalır. [Alan belgesi](../../DOMAIN.md) bu anlamı taşır.
- Decision 2: İncelenen SQL metni koşumla birlikte saklama süresi boyunca (varsayılan 90 gün) saklanır;
  yalnız koşumu başlatan kullanıcı ve `kural-yoneticisi` görür, günlüğe yazılmaz (Requirement 16).
  Geçmişten SQL dışa aktarımı nesne tanımını SQL Server'dan yeniden okumaz, saklanan metni kullanır
  ([review-history-export](../005-review-history-export/PRD.md)).
- Decision 3: Proje sahibinin 2026-10-02 kararı: bir koşumdaki nesne sayısı için ürün sınırı yoktur ve
  süzgece uyan bütün nesneler tek adımda seçilebilir (Requirement 3). Koşumun arka planda sürmesi,
  kaldığı yerden devam etmesi ve sonuçların nesne nesne saklanması bu kararın kapsamında değildir;
  sahibin sonra karar verebileceği ayrı bir iştir (Riskler).
- Decision 4: LLM eşzamanlılık sınırı nesne başına değil koşumun tamamına uygulanır; ayrıca süreç geneli
  bir sınır vardır (Requirement 7). Nesne başına uygulama LLM sunucusunu aşırı yükleyebilir.
- Decision 5: Bu PRD yanlış pozitif işaretini saklamaz; kalıcı işaretleme
  [review-history-export](../005-review-history-export/PRD.md) kapsamındadır ve canlı sonuç penceresi
  de o ucu kullanır (Requirement 19).
- Decision 6: Veritabanı ve nesne listeleme uçları ve filtreleri bu PRD'dedir; SQL Server sorguları,
  veritabanı listesinin kapsamı, hata sınıfları ve bağlantı [sql-server-connection](../002-sql-server-connection/PRD.md)
  PRD'sindedir.

- Decision 7: İstek gövdesindeki seçim listesi teknik olarak 10.000 öğeyle sınırlıdır. Gerekçe: güvenli
  kodlama tabanı (rules/57) her girdinin boyutunun sınırlı olmasını ister; sınırsız liste tek istekle
  sunucu belleğini tüketebilir. 10.000, tek koşumda incelenebilecek gerçekçi seçimin çok üstündedir
  (25 kuralla 250.000 LLM çağrısı) ve küme ingress'inin varsayılan 1 MB gövde sınırına yakın en büyük
  yuvarlak değerdir. Bu sınır kullanıcıya ürün sınırı olarak gösterilmez.
- Decision 8: Aynı anda işlenen nesne sayısı için yeni ayar eklenmez; koşumun LLM eşzamanlılık sınırı
  kullanılır. Gerekçe: her nesne bütün kurallarını o sınırın yuvalarında çalıştırır; sınır kadar nesne
  bütün yuvaları dolu tutmaya yeter, daha fazlası yalnız bekleyen SQL metnini bellekte tutar.
- Decision 9: Durdurma açık bir istekle de yapılır: koşumun sahibi (süper yönetici her koşumu) `POST
  /review-runs/{id}/cancel` ile koşumu durdurur; bu süreçte görevi olmayan "sürüyor" koşum doğrudan
  "iptal edildi" olur. Bitmiş koşum `409 review_run_not_running` alır. Proje sahibinin 2026-10-15
  bildirimi ("analiz durdur çalışmıyor"). Gerekçe: kurumsal giriş/vekil katmanı akış kapanışını
  geciktirebilir; LLM çağrıları kullanıcı durdurduğu anda kesilmelidir.

## Teslim akışı

Belirtim → Plan → Görevler → Uygulama

## Riskler

- Çözümleme mantığı modelin kural dışı çıktılarına göre biçimlenmiş; katmanlara bölerken davranış
  kayabilir. Önlem: altın testler bölmeden önce kaynağa karşı doğrulanır.
- "İhlal değil" süzgeci Türkçe ifadelere dayanır; gerçek bir ihlali yanlışlıkla eleyebilir.
- Kod parçasından satır çıkarımı ilk eşleşen satırı seçer; tekrar eden kodda yanlış satırı gösterebilir.
- Kural sayısı × nesne sayısı çağrı üretir; uzun koşumlar SSE bağlantısının vekil zaman aşımına takılabilir.
- **Çok büyük koşum saatler sürer.** Nesne sınırı olmadığı için bir koşum kural sayısı × nesne sayısı
  kadar LLM çağrısı yapar (25 kural ve 1.000 nesneyle 25.000 çağrı) ve saatlerce, daha büyük seçimde
  günlerce sürebilir.
- **Sonuç yalnız sonda saklanır.** Koşum bitmeden tarayıcı bağlantısı koparsa, sekme kapanırsa ya da
  backend yeniden başlarsa (her dağıtım backend'i yeniden başlatır) koşum kaybolur: "iptal edildi" ya
  da "yarıda kesildi" olur ve o ana kadar yapılan bütün LLM çağrılarının sonucu atılır. Koşumun arka
  planda sürmesi, kaldığı yerden devam etmesi ve sonuçların nesne nesne saklanması yapılmamıştır;
  sahibin ayrıca karar vereceği bir sonraki iştir (Decision 3).
- **LLM payı.** Bir kullanıcının büyük koşumu, o süre boyunca süreç geneli LLM sınırından kendi koşum
  payını (varsayılan 12 yuvanın 6'sı) doldurur; aynı anda çalışan diğer koşumlar yavaşlar.
- **Bellek.** Her nesnenin sonucu ve incelenen SQL metni koşum bitene kadar backend belleğinde durur.
  Backend podunun bellek sınırı 512 MiB'tir; ortalama 10 KB'lık nesnelerle birkaç bin nesnelik koşum
  bu sınırın içinde kalır, 10.000 nesneye yaklaşan ya da çok uzun tanımlı nesnelerden oluşan koşum
  sınırı aşıp podu yeniden başlatabilir ve o anda süren bütün koşumlar kaybolur. SQL dışa aktarımı da
  koşumun bütün SQL metnini bir kerede bellekte kurar.
- **Seçim sırasında katalog değişirse** "tümünü seç" sayfalar arasında bir nesneyi atlayabilir ya da
  silinmiş bir nesneyi seçebilir; silinmiş nesne koşumda `object_not_found` sonucunu alır.
- İncelenen SQL metni ve kod parçaları kurum içi kaynak koddur ve PostgreSQL'de saklama süresi boyunca
  durur; erişim denetimi veya saklama işi bozulursa kod gereğinden geniş kitleye veya uzun süre açık
  kalır.
- Kaynakta iptal edilen koşumun sonuçları atılır; hedefte de atılır, bu nedenle uzun koşumu durdurmak
  emeği kaybettirir.
