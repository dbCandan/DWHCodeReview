# PRD — rule-management

Status: Accepted

Version: 1.1.0

Acceptance date: 2026-10-14

Domain: [sql-review](../../DOMAIN.md)

Kabul kaydı: Proje sahibi bu PRD'yi 2026-10-14'te, kural özeti ve sade görünüm (Decision 5) ile yayının
süper yönetici onayına bağlanması (Decision 6) dahil Decision 1–6 ile kabul etti.

## Amaç

Kural yöneticisi inceleme kurallarını bir taslakta düzenler; taslak süper yöneticinin onayıyla numaralı
bir sürüm olarak yayımlanır. Her inceleme koşumu, başladığı anda en son yayımlanmış sürümü kullanır ve bu sürümün
numarasını saklar. Böylece hangi sonucun hangi kurallarla üretildiği her zaman bellidir.

## Aktörler ve sonuçlar

- **Kural yöneticisi** (`kural-yoneticisi`): Kuralları ekler, siler, metnini ve "nesne meta verisi
  gerekir" işaretini ve tek cümlelik özetini değiştirir, grup içinde sıralar; taslağı kaydeder ve
  yayımlanmak üzere süper yönetici onayına gönderir ([rule-proposals](../009-rule-proposals/PRD.md)).
  Sonuç: onaylanan yayından sonra başlayan her inceleme yeni sürümü kullanır.
- **Süper yönetici:** Taslağı doğrudan yayımlar veya kural yöneticisinin yayın isteğini onaylar; kuralları
  ayrıntılı metinleriyle görür (Decision 6).
- **İnceleyici** (`inceleyici`): Kuralları değiştiremez; yayımlanmış sürümleri "Yayımlanmış kurallar"
  sayfasında tek cümlelik özetleriyle yalnız okur (Requirement 12). Sonuç: bulgudaki `Kural05` gibi kimliğin hangi metne karşılık geldiğini
  görebilir.
- **İşletim ekibi**: Kaynak uygulamadaki kural dosyasının bir kez ve kayıpsız PostgreSQL'e (uygulamanın
  veritabanı) aktarıldığını doğrular.

## Değişmezler ve sınırlar

- Kural kümesinin tek bir **taslağı** ve sıfır veya daha çok **yayımlanmış sürümü** vardır. Yayımlanmış
  sürüm hiçbir zaman değiştirilmez veya silinmez.
- İnceleme yalnız yayımlanmış sürümü kullanır; taslak hiçbir LLM (büyük dil modeli) isteğine girmez.
- Bir koşum boyunca kural sürümü sabittir; koşum sırasında yapılan yayımlama o koşumu etkilemez.
- Kural kimliği `KuralNN` biçimindedir (`Kural01` … `Kural99`, sonra `Kural100` …). Bir kimlik bir kez
  kullanıldıktan sonra başka bir kurala verilmez.
- Kurallar iki grupta durur: **kritik** (`critical`) ve **normal** (`normal`). Grup içi sıra korunur ve
  LLM'e bu sırayla gider.
- Her kuralın **tek cümlelik özeti** (1–200 karakter, satır sonu içermez) vardır; özet kullanıcıya
  gösterim içindir, LLM'e ayrıntılı kural metni gider. Özeti girilmemiş kuralda metnin ilk cümlesi (en çok
  200 karakter) özet yerine gösterilir (Decision 5).
- Kural metni, özet ve taslak içeriği günlüklere (log) yazılmaz.
- Sahip olunan veri: taslak, yayımlanmış sürümler ve içe aktarım kaydı. LLM isteğinin kurulması ve
  koşumun sürüm numarasını saklaması
  [nesne incelemesi](../003-object-review/PRD.md) ile [SQL metni incelemesi](../004-script-review/PRD.md)
  PRD'lerinindir; bu PRD onlara "en son yayımlanmış sürüm" bilgisini verir.
- Kimlik ve oturum [dizin girişi PRD'sinindir](../../../application-foundation/PRDs/001-directory-login/PRD.md).

## Mevcut davranış

Kaynak: `~/codes/dwhcodereview`.

- Kurallar tek dosyadadır: `backend/data/review_rules.json`, alanları `draft`, `published`,
  `published_at` (`backend/services/rules_store.py`). Yayımlanmış kurallardan yalnız bir kopya
  vardır, her yayın öncekinin üzerine yazar, yayımlayan kaydedilmez. **Hedefte değişir:** her yayın
  numaralı, değişmez bir sürümdür; yayımlayan ve zaman saklanır.
- Uçlar `GET /api/rules`, `PUT /api/rules/draft`, `POST /api/rules/publish` (`backend/main.py`);
  yönetici anahtarı tanımlıysa `X-Admin-Key` başlığı ister. **Hedefte değişir:** Active Directory
  girişi ve rol denetimi; yol `/api/dwhcodereview/v1/rule-set`.
- Kaydederken boş metinli kurallar atılır, metinler kırpılır, kimliksiz kurala sıradaki `KuralNN`
  verilir (`_normalize_bundle`); yinelenen kimlik reddedilmez. Ekran yeni kurala "en büyük numara + 1"
  verir (`frontend/src/pages/RulesPage.tsx`, `nextRuleId`); en yüksek numaralı kural silinip yenisi
  eklenirse kimlik yeniden kullanılır. Eşzamanlı kaydetmede son yazan kazanır. **Hedefte değişir:**
  Requirement 3 ve Requirement 4.
- Kurallar sayfası: iki sütun ("Kritik — HIGH", "Normal — LOW / MEDIUM"), kimlik veya metinle arama,
  kapalı satırda metnin ilk 100 karakteri, açılınca metin kutusu ve işaret kutusu, grup içinde
  yukarı/aşağı taşıma, silme, "+ Kural"; alt çubukta "Taslağı kaydet", "Yayınla", "Kaydedilmedi".
  "Yayınla" kaydedilmemiş değişikliği önce kaydeder. Gruplar arası taşıma yoktur. Bu düzen korunur.
- İnceleme sırasında yayımlanmış kurallar her nesnede yeniden okunur (`review_orchestrator.py`,
  `llm_review.py`, `published_bundle()`); koşum ortasındaki yayın aynı koşumda farklı kurallar
  kullandırabilir. **Hedefte değişir:** sürüm koşum başında bir kez seçilir.
- Dosya yoksa koddaki 25 varsayılan kural yazılır (`_default_bundle`). **Hedefte değişir:** varsayılan
  kural yoktur; başlangıç içeriği yalnız içe aktarımdır (Requirement 9).
- `requires_metadata` ("nesne meta verisi gerekir") açık kuralda, veritabanından çekilen nesnenin
  bağımlılık ve sütun özeti yalnız o kuralın LLM isteğine eklenir; yapıştırılan SQL'de eklenmez.
  Bu anlam korunur.

## İşlevsel gereksinimler

Requirement 1: Kural yöneticisi, taslağı ve en son yayımlanmış sürümü tek istekte görür: iki grup
halinde kurallar (kimlik, metin, özet, işaret, sıra), taslağın değişiklik numarası (`revision`), en son
sürümün numarası, yayın zamanı ve yayımlayanın görünen adı, taslağın en son sürümden farklı olup
olmadığı ve yeni kurala verilecek ilk serbest kimlik.

Requirement 2: Taslak kaydedildiğinde boş metinli kurallar atılır, metinlerin başındaki ve sonundaki
boşluklar kırpılır, grup ve sıra aynen saklanır. Kural metni en çok 8.000 karakterdir; taslak en çok
200 kural içerir (**yeni sınır**, kaynakta sayı sınırı yoktu). Özet kırpılır; boş özet "girilmemiş"
sayılır; 200 karakteri aşan veya satır sonu içeren özet `422 rule_summary_invalid` alır.

Requirement 3: Kaydedilen her kimlik ya taslakta zaten vardır ya da ilk serbest kimlikten büyük veya
ona eşit yeni bir `KuralNN` değeridir. Yinelenen, biçime uymayan veya daha önce herhangi bir taslakta
ya da sürümde kullanılmış bir kimliğin yeni kurala verilmesi 422 ile reddedilir; hiçbir değişiklik
yazılmaz.

Requirement 4: Kaydetme ve yayımlama isteği, istemcinin gördüğü taslak değişiklik numarasını taşır.
Numara güncel değilse istek 409 ile reddedilir ve ekran "Kurallar başka biri tarafından değiştirildi;
sayfayı yenileyin" iletisini gösterir. Başarılı her kaydetme numarayı bir artırır.

Requirement 5: Yayımlamayı süper yönetici yapar: taslağı doğrudan yayımlar veya kural yöneticisinin yayın
isteğini onaylar ([rule-proposals](../009-rule-proposals/PRD.md) Requirement 6). Yayımlama, taslağın o
anki içeriğini bir sonraki tam sayı numarasıyla (1, 2, 3 …) yeni ve değişmez bir sürüm olarak saklar; yayımlayan kişiyi ve zamanı kaydeder. Taslak en son sürümle
aynıysa yeni sürüm oluşmaz, var olan sürüm döner (tekrarlanan yayımlama aynı sonucu verir).
**Yeni davranış:** kaynakta aynı içerik de yeniden yayımlanıyor ve yalnız zaman değişiyordu.

Requirement 6: Hiç kural içermeyen taslak yayımlanamaz (422). **Yeni davranış:** kaynak boş kural
kümesini yayımlıyor ve incelemeler sonuçsuz bitiyordu.

Requirement 7: İnceleme servisleri için tek bir okuma işlevi vardır: en son yayımlanmış sürümün
numarasını ve kurallarını döner. Yayımlanmış sürüm yoksa "yayımlanmış kural yok" sonucunu döner ve
inceleme başlatılmaz. Koşum bu işlevi başlangıçta bir kez çağırır.

Requirement 8: Her iki rol yayımlanmış sürümlerin listesini (numara, zaman, yayımlayan, kritik ve
normal kural sayısı) ve tek bir sürümün tam içeriğini okuyabilir. Taslağı kural yöneticisi okur ve
değiştirir; süper yönetici okur.

Requirement 9: Kaynaktaki `backend/data/review_rules.json` dosyasının depoya alınmış kopyası
(SHA-256 parmak izi `2346ad4769259b5a09b4d1c742ec0a6f3d575cdb054bf126fb395cdc709a25eb`) veritabanı
göçüyle bir kez içe aktarılır: `published` içeriği 1 numaralı sürüm olur, yayın zamanı dosyadaki
`published_at` değeridir (`2026-04-10T14:05:15Z`), yayımlayan "içe aktarım" olarak kaydedilir;
`draft` içeriği taslak olur. Kimlikler, gruplar, sıra, metinler ve işaretler birebir korunur.
Kural tabloları boş değilse içe aktarım hiçbir şey yazmaz. Parmak izi tutmazsa veya dosyada
`KuralNN` dışında kimlik varsa göç hata verip durur.

Requirement 10: Kurallar sayfası kaynaktaki düzeni ve işlemleri korur (Mevcut davranış bölümü).
Ek olarak başlıkta "Son yayın: sürüm N · tarih · yayımlayan" ve taslak farklıysa "Taslakta
yayımlanmamış değişiklik var" yazar. Tüm metinler Türkçedir. Sayfa ve menü öğesi yalnız kural
yöneticisine görünür; bu gizleme yetki denetiminin yerini tutmaz.

Requirement 11: "Yayımlanmış kurallar" sayfası her iki role görünür ve Requirement 8'deki okuma
uçlarını kullanır: en son sürümün kurallarını gösterir (Requirement 12), kimlik, özet veya metinle
arama sunar ve sürüm listesinden eski bir sürümü açmaya izin verir. Sayfada
düzenleme, kaydetme veya yayımlama denetimi yoktur. Yayımlanmış sürüm yoksa "Henüz yayımlanmış kural
yok" yazar (Decision 1).

Requirement 12: Süper yönetici dışındaki kullanıcılar "Yayımlanmış kurallar" sayfasında ve inceleme
başlatma ekranında kuralları sade bir listede, kimlik ve tek cümlelik özetle görür; öncelik ve meta veri
işareti küçük etiket olarak durur, ayrıntılı metin gösterilmez. Süper yönetici aynı sayfalarda ayrıntılı
metni de görür; kural yöneticisi ayrıntılı metni Kurallar sayfasında düzenler. Kurallar sayfası her kural
için özet alanı sunar.

## API sözleşmesi

Tüm uçlar `/api/dwhcodereview/v1` altındadır, geçerli oturum ister ve hatayı
`{"detail":{"code":"...","message":"..."}}` biçiminde döner (`message` Türkçe ve güvenlidir).

| Yöntem ve yol | Rol | İstek → yanıt |
|---|---|---|
| `GET /rule-set` | kural-yoneticisi | → taslak (`revision`, `critical[]`, `normal[]`), `latest_version` (yoksa `null`), `draft_differs`, `next_rule_id` |
| `PUT /rule-set/draft` | kural-yoneticisi | `{base_revision, critical[], normal[]}`; her kural `{id, text, summary, requires_metadata}` → güncel taslak |
| `POST /rule-set/versions` | süper yönetici | `{base_revision}` → yeni sürüm (201) veya aynı içerikli var olan sürüm (200); kural yöneticisi `403 publish_requires_approval` alır ve [rule-proposals](../009-rule-proposals/PRD.md) yayın isteğini kullanır |
| `GET /rule-set/versions` | inceleyici, kural-yoneticisi | `page`, `page_size` → numaraya göre azalan sürüm özeti ve sayfa bilgisi |
| `GET /rule-set/versions/latest` | inceleyici, kural-yoneticisi | → en son sürümün tam içeriği; yoksa 404 `no_published_rule_set` |
| `GET /rule-set/versions/{number}` | inceleyici, kural-yoneticisi | → o sürümün tam içeriği; yoksa 404 `rule_set_version_not_found` |

Hata kodları: 401 `not_authenticated`; 403 `forbidden`; 409 `rule_set_draft_conflict`
(Requirement 4); 422 `rule_id_invalid`, `rule_id_duplicate`, `rule_id_reused`, `rule_text_too_long`,
`rule_set_too_large`, `rule_summary_invalid` (Requirement 2–3), `rule_set_empty` (Requirement 6). Sürüm
ve taslak yanıtlarında her kural `summary` taşır (girilmemişse boş). Yeni kural için `id`
istemcide `next_rule_id`'den başlayarak verilir; sunucu Requirement 3'e göre doğrular.

## Güvenlik ve yetkilendirme

- Rol denetimi arka uçta, her uçta yapılır. İnceleyicinin taslak uçlarına isteği 403 alır.
- Kural metni LLM isteğine olduğu gibi girer; bu nedenle yalnız kural yöneticisi değiştirebilir ve yayın
  süper yönetici onayından geçer (Decision 6).
  Metinde LLM'i yönlendiren ifadeler olabilir; bu, kural yöneticisinin sorumluluğunda kabul edilen
  bir güven sınırıdır.
- Tüm sorgular parametrelidir ve etkin kiracı (kurum) kapsamında çalışır. Taslak ve sürüm
  kimlikleri dışarıya iç sayı olarak verilmez; sürüm numarası iş anlamlı bir değerdir.
- Kural metni, özet, taslak içeriği ve istek gövdesi loga yazılmaz.

## Veri ve geçiş

- **Taslak:** kiracı başına bir kayıt; `revision`, sonraki serbest kural numarası, son değiştiren ve
  zaman. **Taslak kuralları:** kimlik, grup, sıra, metin, özet, işaret.
- **Sürüm:** `public_id`, kiracı içinde tekil `number`, `published_at`, yayımlayan kullanıcı (içe
  aktarımda boş), kaynak (`arayuz` veya `ice-aktarim`), içerik parmak izi. **Sürüm kuralları:** taslak
  kurallarıyla aynı alanlar. Sürüm satırları için uygulamada güncelleme ve silme yolu yoktur.
- Şemanın sahibi SQLAlchemy modelleridir; tablolar Alembic göçüyle (veritabanı yapısını sürüm sürüm
  kuran betik) oluşur. İçe aktarım ayrı bir veri göçüdür (Requirement 9); kaynak dosyanın kopyası
  parmak iziyle birlikte depoya girer. Kaynak dosyada 11 kural vardır (10 kritik, 1 normal;
  `Kural02` yoktur, sıra numara sırası değildir) ve taslak yayımlanmış içerikle aynıdır.
- Koddaki 25 varsayılan kural taşınmaz. Kaynak dosya salt okunur kalır.
- Özet sütunu taslak ve sürüm kurallarına isteğe bağlı olarak eklenir (genişletici göç,
  [rule-proposals](../009-rule-proposals/PRD.md) göçüyle birlikte); mevcut kurallar özetsiz kalır ve
  metnin ilk cümlesiyle gösterilir. Özet içerik parmak izine yalnız girilmişse katılır; özetsiz
  sürümlerin parmak izi değişmez.

## Gözlemlenebilirlik

- Yapılandırılmış log olayları: `rule_set.draft_saved` (revision, grup başına sayı, kullanıcı
  `public_id`), `rule_set.version_published` (numara, sayılar, parmak izi, yeni mi var olan mı),
  `rule_set.import` (sonuç: aktarıldı / atlandı / hata). Kural metni yer almaz.
- 409 ve 422 yanıtları hata kodlarıyla standart istek loguna düşer. Yeni ölçüm (metrik) eklenmez.

## Dağıtım etkisi

- Yeni tablolar ve içe aktarım göçü, dağıtımdaki göç adımıyla uygulanır
  ([Kubernetes dağıtımı PRD'si](../../../application-foundation/PRDs/002-kubernetes-delivery/PRD.md)).
  Uygulama açılırken şema değiştirmez.
- Yeni sır, yeni ağ çıkışı veya chart değişikliği yoktur. Kaynak dosyanın kopyası arka uç imajına
  girer.

## Test stratejisi

- Arka uç birim testleri: kırpma, boş kural atma, kimlik kuralları, sınırlar, özet doğrulaması ve ilk
  cümle yedeği, aynı içerikte yayımlama.
- Gerçek PostgreSQL testleri: 409 çakışması, eşzamanlı iki yayımlamada tek sürüm, sürüm
  değişmezliği, rol başına 401/403, sürüm yokken okuma işlevinin sonucu, içe aktarım göçünün boş,
  dolu ve bozuk kopya durumları.
- Ön yüz testleri (Vitest): arama, taşıma, silme, ekleme kimliği, "Kaydedilmedi", yayımlamadan önce
  kaydetme, 409 iletisi, Kurallar sayfasının inceleyiciye görünmemesi, "Yayımlanmış kurallar"
  sayfasının salt okunur ve süper yönetici dışında özetle görünmesi, özet alanı.

## Vektör ve gömme sözleşmesi (uygulanabilirse)

- Sağlayıcı / dağıtım sınırı: Uygulanamaz
- Model kimliği ve değişmez sürüm: Uygulanamaz
- Boyut ve normalleştirme: Uygulanamaz
- Uzaklık metriği ve indeks stratejisi: Uygulanamaz
- Getirim kalitesi/duyarlılık ve gecikme eşikleri: Uygulanamaz
- Kaynak sınıflandırması, en aza indirme ve saklama: Uygulanamaz
- Yeniden gömme, geçiş ve geri alma: Uygulanamaz

## Kabul kriterleri

- [ ] Acceptance 1: L1 — Otomatik testlerden geçti: arka uç birim ve gerçek PostgreSQL testleri
  Requirement 1–8'i kapsar ve geçer; OpenAPI (API tanım dosyası) kayıtlı yapıtla aynıdır.
- [ ] Acceptance 2: L1 — Otomatik testlerden geçti: içe aktarım göç testi Requirement 9'un üç
  durumunu (boş, dolu, bozuk kopya) doğrular.
- [ ] Acceptance 3: L1 — Otomatik testlerden geçti: Kurallar ve "Yayımlanmış kurallar" sayfalarının
  Vitest testleri Requirement 4, 10, 11 ve 12'yi doğrular.
- [ ] Acceptance 4: L2 — Gerçek istemci/ortamda doğrulandı: yerel PostgreSQL ve tarayıcıyla kural
  yöneticisi içe aktarılmış 1 numaralı sürümü görür, özetiyle kural ekleyip kaydeder ve onaya gönderir,
  süper yönetici onaylar ve 2 numaralı sürüm görünür; inceleyici aynı oturum düzeninde Kurallar
  sayfasını göremez, taslak ucundan 403 alır ve "Yayımlanmış kurallar" sayfasında 2 numaralı sürümü özetleriyle salt okunur görür
  (Requirement 1, 4, 5, 8, 9, 10, 11, 12).
- [ ] Acceptance 5: L2 — Gerçek istemci/ortamda doğrulandı: yayımlamadan sonra başlatılan bir nesne
  incelemesi koşum kaydında 2 numaralı sürümü taşır; koşum sürerken yapılan yayımlama o koşumun
  sürümünü değiştirmez (Requirement 7). Nesne incelemesi PRD'si uygulanmadan bu kabul açık kalır.

## Kararlar

- Decision 1: İnceleyici için salt okunur "Yayımlanmış kurallar" sayfası vardır (Requirement 11);
  bulgudaki kural kimliğinin hangi metne karşılık geldiğini anlamayı kolaylaştırır.
- Decision 2: Eski bir sürümü taslağa geri yükleme bu PRD'de yoktur; ihtiyaç olursa ayrı gereksinim
  olarak eklenir.
- Decision 3: İçe aktarım işletim ekibinin elle çalıştırdığı bir komut değil, veri göçüdür
  (Requirement 9); `nonprod`'da elle adım gerektirmez ve her veritabanında bir kez çalışır.
- Decision 4: Taslak en çok 200 kural, kural metni en çok 8.000 karakterdir (Requirement 2); bugün 11
  kural var ve en uzun metin 3.504 karakter.
- Decision 5: Her kuralın tek cümlelik özeti vardır; süper yönetici dışındaki kullanıcılar kuralları
  özetle görür, özet girilmemişse metnin ilk cümlesi gösterilir. Proje sahibinin 2026-10-14 kararı.
- Decision 6: Kural yöneticisi taslağı düzenler ama yayımlayamaz; yayın süper yönetici onayına tabidir
  ([rule-proposals](../009-rule-proposals/PRD.md) Decision 3). Proje sahibinin 2026-10-14 kararı.

## Teslim akışı

Belirtim → Plan → Görevler → Uygulama ([Plan](plan.md), [Görevler](tasks.md)).

## Riskler

- İçe aktarım yanlış dosya kopyasıyla çalışırsa inceleme kuralları sessizce değişir; parmak izi
  denetimi ve göç testi bunu önler.
- Kimliklerin yeniden kullanılmaması geçmiş sonuçlarla karışıklığı önler, ama numaralarda boşluk
  bırakır (bugün de `Kural02` yok).
- Kural metinleri LLM'e doğrudan gider; kötü yazılmış bir metin tüm incelemelerin kalitesini düşürür.
  Sürüm geçmişi sorunun hangi yayımla başladığını gösterir, ancak geri alma bu PRD'de yoktur.
- Koşumun sürümü başta sabitlemesi, uzun bir koşumun yeni yayımlanan kuralları kullanmaması demektir;
  bu bilinçli bir davranış değişikliğidir.
