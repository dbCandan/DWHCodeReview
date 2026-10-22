# PRD — rule-group-selection

Status: Accepted

Version: 2.0.0

Acceptance date: 2026-10-14

Domain: [sql-review](../../DOMAIN.md)

Kabul kaydı: Proje sahibi bu PRD'yi 2026-10-14'te çoklu grup üyeliği (Decision 1), öncelik ile grubun
ayrı boyut kalması (Decision 2), grupların kurum geneli olması (Decision 3), geri almanın veri kaybında
durması (Decision 4), yeni ölçüm eklenmemesi (Decision 5) ve tek tek kural seçimi (Decision 6) kararlarıyla
kabul etti.

**1.x revizyon notu (2026-10-15):** [directory-login](../../../application-foundation/PRDs/001-directory-login/PRD.md) 1.3.0 Decision 14 ile `kural-yoneticisi` rolü kaldırıldı; kullanıcılar `inceleyici` (arayüzde "Kullanıcı") ve süper yöneticidir. Bu belgede kural yöneticisine verilen yetkiler (taslağı düzenleme ve yayımlama, bağlantı ayarları, LLM çağrı özetleri, tüm incelemeleri görme) süper yöneticidedir; "inceleyici" geçen yerler her kullanıcıyı anlatır.

**2.x revizyon notu (2026-10-19):** [rule-proposals](../009-rule-proposals/PRD.md) 2.0.0 Decision 8 ile kural ve grup önerileri ile onayları kaldırıldı. Kuralları, grupları ve taslağı yalnız süper yönetici düzenler ve doğrudan yayımlar; bu belgede öneri, onay veya yayın isteğinden söz eden yerler artık geçerli değildir.

## Amaç

İnceleyici, bir inceleme koşumunu başlatırken **kural kümesinin tamamı yerine** bir veya daha çok
**adlandırılmış kural grubu** ya da **tek tek seçtiği kurallar** ile çalışır; koşum yalnız seçilen
kuralları kullanır ve sonucu, seçimi ve kuralların gruplarını gösteren bir rapor olarak sunar. Böylece
farklı ekipler (örneğin performans, adlandırma, güvenlik) yalnız kendilerini ilgilendiren kurallara göre
inceleme yapabilir. Bu yetenek, mevcut [nesne incelemesi](../003-object-review/PRD.md) ve
[SQL metni incelemesi](../004-script-review/PRD.md) davranışını, "hiçbir şey seçilmezse tüm kurallar"
varsayılanıyla geriye uyumlu biçimde genişletir.

## Aktörler ve sonuçlar

- **İnceleyici (`inceleyici`):** Koşum başlatırken sıfır, bir veya daha çok kural grubu ve sıfır, bir veya
  daha çok tek kural seçer. Ölçülebilir sonuç: koşum yalnız seçilen grupların kuralları ile seçilen
  kuralların birleşimini çalıştırır; hiçbir şey seçilmezse yayımlanmış sürümün bütün kuralları çalışır
  (bugünkü davranış).
- **Kural yöneticisi (`kural-yoneticisi`):** İnceleyicinin yaptıklarına ek olarak taslakta kural gruplarını
  tanımlar ve kuralları gruplara atar. Taslağın yayımlanması süper yönetici onayına tabidir
  ([rule-proposals](../009-rule-proposals/PRD.md)). Ölçülebilir sonuç: yayımlanan sürüm, grup tanımlarını
  ve her kuralın grup üyeliklerini değişmez biçimde taşır.
- **Kural önericisi ve süper yönetici:** Yeni grup önerisi ve onayı
  [rule-proposals](../009-rule-proposals/PRD.md) PRD'sindedir; onaylanan grup bu PRD'nin grup modeline
  yazılır.
- **İşletim ekibi:** Uygulama içi rol değildir; bu PRD ona iş vermez.

## Değişmezler ve sınırlar

- **Kural grubu:** Kiracı içinde tekil kimliği (`public_id`), görünen adı ve isteğe bağlı açıklaması olan
  adlandırılmış kural kümesidir. Grup, kuralların **öncelik grubundan** (kritik/normal) bağımsız bir
  boyuttur (Decision 2). Bir kural **sıfır, bir veya daha çok** gruba üye olabilir (Decision 1). Hiçbir
  gruba üye olmayan kural "grupsuz"tur; tek tek seçilerek veya "tüm kurallar" koşumunda çalışır.
- Kural grupları **kural kümesi sürümünün parçasıdır**: grup tanımları ve üyelikler taslakta düzenlenir,
  yayımlanınca sürümle birlikte donar ([rule-management](../001-rule-management/PRD.md) sürüm
  değişmezliği). Yayımlanmış bir sürümün grupları değiştirilemez.
- Koşum, sabitlediği yayımlanmış sürümün gruplarını ve kurallarını kullanır; sürüm koşum başında bir kez
  sabitlenir (object-review Requirement 4). Seçilen grup veya kural o sürümde yoksa koşum başlamaz.
- Seçilen grupların kuralları ile seçilen tek kuralların **birleşimi** çalışır; birden çok seçimde bulunan
  bir kural koşumda **bir kez** çalışır. Çalışma sırası yine önce kritik sonra normal, sürüm içi sıradır
  (object-review Requirement 7).
- Öncelik (kritik/normal) ile adlandırılmış grup **iki ayrı boyut** olarak kalır (Decision 2); önem
  eşlemesi (kritikte `HIGH`, normalde `LOW`) değişmez.
- Seçim (gruplar ve tek kurallar) koşum kaydında saklanır; rapor ve dışa aktarma
  ([review-history-export](../005-review-history-export/PRD.md)) seçimi ve her kuralın gruplarını gösterir.
- Bütün gruplar kurum genelidir ve her role açıktır; ekip veya kullanıcı bazlı grup kapsamı yoktur
  (Decision 3).
- SQL Server yalnız salt okunur sorgulanır; LLM yalnız onaylı kurum içi uca gider; ham SQL ve ham LLM
  yanıtı loga yazılmaz (alan değişmezleri korunur).
- Arayüz yalnız Türkçedir.

## İşlevsel gereksinimler

Requirement 1: Kural yöneticisi taslakta kural grubu oluşturur, adlandırır, açıklar, siler ve her kurala
sıfır veya daha çok grup üyeliği atar. Grup adı kiracı içinde tekildir (büyük-küçük harf ve Türkçe
İ/ı duyarsız), 1–80 karakterdir; bir sürümde en çok 50 grup bulunur. Silinen grup yalnız taslaktan kalkar
(yayımlanmış sürümlerdeki kopyası değişmez); kuralların diğer üyelikleri sürer.

Requirement 2: `GET /rule-set` yanıtı grup tanımlarını ve her kuralın grup üyeliklerini (`rule_group_ids[]`)
taşır. `PUT /rule-set/draft` grup tanımlarını ve üyelikleri kabul eder; bilinmeyen gruba üyelik, tekrarlı
grup adı, aynı kuralda tekrarlı üyelik veya biçimsiz ad `422` ile reddedilir ve hiçbir değişiklik yazılmaz
([rule-management](../001-rule-management/PRD.md) Requirement 2–4 çakışma/sürüm kuralları aynen geçerli).

Requirement 3: Yayımlama, grup tanımlarını ve üyelikleri sürümün değişmez içeriğine yazar. Sürüm okuma
uçları (`GET /rule-set/versions/{number}`, `.../latest`) grupları ve üyelikleri döner. Hiç grubu olmayan
sürüm geçerlidir. İçerik parmak izi grup tanımlarını ve üyelikleri yalnız sürümde grup varsa içerir;
grupsuz sürümün parmak izi değişmez.

Requirement 4: Koşum başlatma isteği isteğe bağlı `rule_group_ids[]` ve `rule_codes[]` alanlarını taşır.
İkisi de boş veya yoksa koşum yayımlanmış sürümün bütün kurallarını kullanır (bugünkü davranış). Doluysa
koşum, seçilen grupların kurallarının ve seçilen kuralların birleşimini kullanır. Sabitlenen sürümde
bulunmayan grup `422 rule_group_unknown`, bulunmayan kural `422 rule_unknown` ile; birleşim boşsa
`422 rule_group_selection_empty` ile reddedilir; koşum başlamaz.

Requirement 5: Koşum kaydı seçilen grupları (kimlik ve sabitlenen sürümdeki ad) ve seçilen tek kural
kodlarını saklar. Hiçbir şey seçilmemişse "tüm kurallar" olarak işaretlenir. Bu bilgi koşum süresince
değişmez.

Requirement 6: Canlı ilerleme (object-review Requirement 14) ve sonuç modeli (object-review Requirement
13), her kural sonucunun sabitlenen sürümdeki gruplarının adlarını (`rule_group_names[]`, grupsuzsa boş)
taşır. Arayüz sonuç satırında kuralın gruplarını etiket olarak gösterir ve sonuçları bir gruba göre
süzmeye izin verir. Grup bilgisi yalnız gösterim içindir; kural sonucu sözleşmesini başka yönden
değiştirmez.

Requirement 7: Rapor ve dışa aktarma ([review-history-export](../005-review-history-export/PRD.md)): koşum
raporu başlığında seçilen grupları, seçilen tek kural sayısını ya da "tüm kurallar"ı gösterir; CSV ve SQL
dışa aktarımı kural gruplarını taşır: CSV'de son `rule_group` sütununda adlar `; ` ile ayrılır, SQL
yorumunda kural kimliğinin yanında parantez içinde virgülle ayrılır; grupsuz kuralda boştur (biçimin sahibi
review-history-export Requirement 7-8 ve Decision 9).

Requirement 8: Koşum başlatma ekranı, sabitlenecek en son yayımlanmış sürümün kurallarını tek, aranabilir
bir listede onay kutularıyla ve grupları "hızlı seçim" olarak gösterir: bir grubu seçmek o grubun bütün
kurallarını işaretler, kaldırmak işaretleri kaldırır; inceleyici kuralları ayrıca tek tek işaretleyip
kaldırabilir. Hiçbir kural işaretlenmezse "Tüm kurallar" çalışır; ekran seçili kural sayısını gösterir.
Kurallar süper yönetici dışındaki kullanıcılara tek cümlelik özetleriyle gösterilir
([rule-management](../001-rule-management/PRD.md) Requirement 12). Kural yöneticisinin "Kurallar"
sayfası, mevcut düzene (kritik/normal sütunları) grup yönetimi ve kural başına çoklu grup ataması ekler.
Tüm metinler Türkçedir.

## API sözleşmesi

Ön ek `/api/dwhcodereview/v1`. Tüm uçlar geçerli oturum (JWT) ve uygun rolü ister; hata zarfı
`{"detail":{"code":"...","message":"..."}}`.

- `GET /rule-set` ve `GET /rule-set/versions/{number}` / `.../latest` yanıtlarına eklenir:
  `groups[]` (`id`, `name`, `description`) ve her kuralda `rule_group_ids[]`.
- `PUT /rule-set/draft` gövdesine eklenir: `groups[]` ve her kuralda `rule_group_ids[]`. Hata kodları:
  `422 rule_group_name_invalid`, `rule_group_name_duplicate`, `rule_group_unknown_membership`,
  `rule_group_too_many`.
- `POST /object-reviews` ve `POST /script-reviews` isteğine eklenir: isteğe bağlı `rule_group_ids[]` ve
  `rule_codes[]`. Akış öncesi hatalar: `422 rule_group_unknown`, `422 rule_unknown`,
  `422 rule_group_selection_empty`. `run_started` olayı `selected_rule_groups[]` (id, name),
  `selected_rule_codes[]` ve hiçbir şey seçilmemişse `all_rules: true` taşır. Kural sonucu öğesi
  `rule_group_names[]` taşır.
- Koşum ayrıntısı (`GET /review-runs/{id}`) `selected_rule_groups[]`, `selected_rule_codes[]` ve
  `all_rules` taşır.
- Dışa aktarma uçlarının (review-history-export) çıktısına "kural grubu" sütunu/yorumu eklenir; uç yolları
  değişmez.

## Güvenlik ve yetkilendirme

- Taslakta grup tanımlama ve üyelik yalnız `kural-yoneticisi` rolündedir; inceleyicinin taslak/grup yazma
  isteği `403` alır. Yeni grup önerisi [rule-proposals](../009-rule-proposals/PRD.md) yetkisine bağlıdır.
- Grup ve kural seçimi her role açıktır; bütün gruplar kurum genelidir (Decision 3).
- Grup adları ve açıklamaları LLM istemine girmez; yalnız kuralların metni modele gider (bugünkü sınır).
- Tüm sorgular parametreli ve etkin kiracı kapsamındadır.

## Veri ve geçiş

- Yeni tablolar (Alembic göçü): **taslak kural grubu** (kiracı, `public_id`, ad, açıklama, sıra),
  **sürüm kural grubu** (yayımlanınca yazılan değişmez kopya), **taslak kural–grup üyeliği** ve **sürüm
  kural–grup üyeliği** (çoklu üyelik, Decision 1), **koşum–seçilen grup** (grup kimliği, o sürümdeki ad,
  sıra) ve **koşum–seçilen kural** (kural kodu). Kural sonucuna grup adları (`rule_group_names`) eklenir.
  Şemanın sahibi bu PRD'dir; tablolar [rule-management](../001-rule-management/PRD.md) sürüm tablolarına
  ve koşum tablolarına bağlanır.
- Göç yalnız genişleticidir: yeni tablolar ve isteğe bağlı sütunlar eklenir; mevcut koşumlar "tüm
  kurallar" sayılır, mevcut sürümler grupsuz kalır. Geri alma yeni tabloları düşürür; grup veya seçim
  verisi varken geri alma, veri kaybını bildiren bir denetimle durur (Decision 4).

## Gözlemlenebilirlik

- Log olayları: `rule_set.group_created`/`group_deleted` (grup `public_id`, kullanıcı `public_id`; grup adı
  ve kural metni yazılmaz). Koşum loguna seçilen grup sayısı ve seçilen tek kural sayısı eklenir (ad ve
  metin yazılmaz).
- Yeni ölçüm veya ölçüm etiketi eklenmez (Decision 5).

## Dağıtım etkisi

- Yeni göç; yeni sır, ağ çıkışı veya chart değişikliği yoktur.
- İstek gövdesi az büyür; grup kimlikleri ve kural kodları küçüktür ve sayıları sınırlıdır (en çok 50 grup,
  en çok 200 kural).

## Test stratejisi

- Arka uç birim: grup adı doğrulama, çoklu üyelik doğrulama, seçilen grupların ve kuralların birleşimi,
  ortak kuralın bir kez çalışması, kritik-önce sıralaması, parmak izinin grupsuz sürümde değişmemesi.
- Gerçek PostgreSQL: grup tanımlarının ve çoklu üyeliğin sürümle donması, grupsuz eski sürümün çalışması,
  koşumda seçimin saklanması, seçimli ve seçimsiz koşumun doğru kural kümesini kullanması, göçün geri
  alınması.
- API: `rule_group_unknown`, `rule_unknown`, `rule_group_selection_empty`, rol başına `403`, akışta
  `selected_rule_groups` ve `selected_rule_codes`.
- Ön yüz (Vitest): grup yönetimi ve çoklu atama, koşum ekranında aranabilir kural listesi, grupla hızlı
  seçim ve tek tek seçim, "Tüm kurallar" varsayılanı, sonuçlarda grup etiketleri ve grup süzgeci, dışa
  aktarımda grup sütunu.

## Vektör ve gömme sözleşmesi (uygulanabilirse)

- Sağlayıcı / dağıtım sınırı: Uygulanamaz
- Model kimliği ve değişmez sürüm: Uygulanamaz
- Boyut ve normalleştirme: Uygulanamaz
- Uzaklık metriği ve indeks stratejisi: Uygulanamaz
- Getirim kalitesi/duyarlılık ve gecikme eşikleri: Uygulanamaz
- Kaynak sınıflandırması, en aza indirme ve saklama: Uygulanamaz
- Yeniden gömme, geçiş ve geri alma: Uygulanamaz

## Kabul kriterleri

- [ ] Acceptance 1: L1 — Otomatik testlerden geçti: grup doğrulama, çoklu üyelik, birleşim hesabı ve
  sıralama birim testleri geçer (Requirement 1, 4).
- [ ] Acceptance 2: L1 — Otomatik testlerden geçti: grupların ve çoklu üyeliğin sürümle donması, koşumda
  seçimin saklanması ve doğru kural kümesinin kullanılması gerçek PostgreSQL testleriyle geçer
  (Requirement 3, 5); OpenAPI kayıtlı yapıtla aynıdır.
- [ ] Acceptance 3: L1 — Otomatik testlerden geçti: akış öncesi `rule_group_unknown`, `rule_unknown` ve
  `rule_group_selection_empty`, rol denetimi ve dışa aktarımda grup sütunu testleri geçer (Requirement 4,
  7).
- [ ] Acceptance 4: L2 — Gerçek istemci/ortamda doğrulandı: aynı kural iki grupta yer alır; inceleyici bir
  grubu hızlı seçimle işaretleyip bir kuralı ayrıca ekler ve koşum yalnız işaretli kuralları bir kez
  çalıştırır; raporda kuralın grupları görünür; hiçbir şey seçilmeyince bütün kurallar çalışır
  (Requirement 1–8).

## Kararlar

- Decision 1: Bir kural sıfır, bir veya daha çok adlandırılmış gruba üye olabilir (çoklu üyelik). Proje
  sahibinin 2026-10-14 kararı. Gerekçe: kullanıcılar istedikleri kuralları toplayarak grup oluşturabilir
  ([rule-proposals](../009-rule-proposals/PRD.md)); aynı kural birden çok ekibi ilgilendirebilir. Birden
  çok seçimde bulunan kural koşumda bir kez çalışır.
- Decision 2: Öncelik (kritik/normal) ile adlandırılmış grup iki ayrı boyut olarak kalır; kritik/normal
  gruplara katılmaz. Proje sahibinin 2026-10-05 kararı. Gerekçe: mevcut Kurallar düzeni, önem eşlemesi
  ve raporlar değişmez.
- Decision 3: Bütün gruplar kurum genelidir ve her role açıktır; ekip veya kullanıcı bazlı grup kapsamı
  yoktur. Proje sahibinin 2026-10-14 kararı.
- Decision 4: Grup veya seçim verisi varken göç geri alma, veri kaybını bildirip durur; grup bilgisi
  sessizce silinmez. Proje sahibinin 2026-10-05 kararı.
- Decision 5: Bu yetenek için yeni ölçüm eklenmez; log olayları yeterlidir. Proje sahibinin 2026-10-05
  kararı.
- Decision 6: İnceleyici koşumu grupların yanında tek tek seçtiği kurallarla da başlatabilir; gruplar
  koşum ekranında "hızlı seçim" olarak kalır. Proje sahibinin 2026-10-14 kararı.

## Açık sorular

Açık soru kalmadı.

## Teslim akışı

Belirtim → Plan → Görevler → Uygulama ([Plan](plan.md), [Görevler](tasks.md)).

## Riskler

- Grup üyeliğinin sürümle donması, eski koşumların yeniden üretilebilirliğini korur ama grupların sık
  değişmesi çok sayıda sürüm üretebilir.
- Yanlış seçim, bir ekibin önemli bir kuralı atlamasına yol açabilir; "Tüm kurallar" varsayılanı bu riski
  azaltır.
- Çoklu üyelikte bir kural birden çok grubun sayımına girer; grup başına kural sayısı toplamı kural
  sayısından büyük olabilir. Rapor kural sonucunu bir kez gösterir, gruplarını etiket olarak taşır.
