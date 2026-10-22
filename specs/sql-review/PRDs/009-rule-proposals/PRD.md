# PRD — rule-proposals

Status: Accepted

Version: 2.0.0

Acceptance date: 2026-10-19

Domain: [sql-review](../../DOMAIN.md)

Kabul kaydı: Proje sahibi bu PRD'yi 2026-10-14'te Decision 1–5 ile kabul etti. Kural özetinin veri ve
gösterim kuralları [rule-management](../001-rule-management/PRD.md) 1.1.0'dadır. 1.1.0 revizyonunu
proje sahibi 2026-10-15'te "herkes onaya yollayabilsin" kararıyla kabul etti (Decision 6): öneri
yetkisi listesi kalkar, her inceleyici ve kural yöneticisi öneri gönderir. 1.2.0 revizyonunu proje
sahibi 2026-10-15'te kabul etti (Decision 7): kural yöneticisi rolü kalktığı için yayın isteği akışı
(Requirement 6) kaldırılır; taslağı yalnız süper yönetici düzenler ve doğrudan yayımlar.

**2.0.0 — yetenek kaldırıldı (2026-10-19, Decision 8):** Proje sahibinin "onay ve öneri kısımlarını tamamen kaldır" talimatıyla kural ve grup önerileri ile onayları tümüyle kalktı. Bu belgedeki Requirement 1–7 ve Acceptance 1–4 artık uygulanmaz; belge, tabloların ve geçmiş kayıtların neden yerinde durduğunu anlatmak için kalır.

## Amaç

Kural kümesine yapılan her değişiklik süper yöneticinin onayından geçerek yayımlanır. Her inceleyici ve
kural yöneticisi yeni **kural** ve yeni **kural grubu** önerir; kural yöneticisi taslağını
yayımlamak için **onaya gönderir**. Süper yönetici bekleyen istekleri ayrıntılarıyla görür, onaylar veya
gerekçesiyle reddeder; onaylanan öneri hemen yeni bir sürüm olarak yayımlanır. Böylece kurallar kurumda
genişleyebilir, ama yayımlanan her kural tek bir yetkili denetimden geçer.

## Aktörler ve sonuçlar

- **Kural önericisi:** Rolü `inceleyici` veya `kural-yoneticisi` olan her kullanıcıdır; ayrı bir yetki
  gerekmez (Decision 6). Yeni kural (tek cümlelik özet ve ayrıntılı
  metinle) ve yayımlanmış kurallardan oluşan yeni kural grubu önerir; kendi önerilerinin durumunu ve ret
  gerekçesini görür; bekleyen önerisini geri çeker. Ölçülebilir sonuç: onaylanan önerisi yeni sürümde
  herkesin kullanımına açılır.
- **Kural yöneticisi (`kural-yoneticisi`):** Taslağı bugünkü gibi düzenler
  ([rule-management](../001-rule-management/PRD.md)), ama yayımlayamaz; taslağı **onaya gönderir**
  (Decision 3). Ölçülebilir sonuç: onaylanan yayın isteği taslağı yeni sürüm olarak yayımlar.
- **Süper yönetici:** Bekleyen kural önerilerini, grup önerilerini ve yayın isteklerini ayrıntılarıyla
  görür; onaylar veya gerekçesiyle reddeder. Taslağı
  kendisi doğrudan yayımlayabilir. Ölçülebilir sonuç: onayladığı her istek aynı işlemde yayımlanır.
- **İnceleyici:** Bu PRD ona yeni iş vermez; onaylanan kural ve grupları incelemede kullanır.

## Değişmezler ve sınırlar

- Yayımlanan her kural değişikliği süper yönetici kararından geçer: süper yöneticinin kendi yayını, onaylanan
  öneri veya onaylanan yayın isteği. Kural yöneticisinin doğrudan yayın isteği `403` alır.
- **Kural önerisi:** tek cümlelik **özet** (1–200 karakter, satır sonu içermez), **ayrıntılı metin**
  (1–8.000 karakter; LLM'e giden kural metni), **öncelik** (kritik/normal), "nesne meta verisi gerekir"
  işareti ve isteğe bağlı olarak katılacağı yayımlanmış gruplar. Özet ve ayrıntılı metin zorunludur
  (Decision 4).
- **Grup önerisi:** ad (1–80 karakter, kiracıda tekil), isteğe bağlı açıklama (en çok 500 karakter) ve en son
  yayımlanmış sürümden en az bir kural kodu. Bir kural birden çok grupta olabilir
  ([rule-group-selection](../007-rule-group-selection/PRD.md) Decision 1).
- **Onay hemen yayımlar** (Decision 2): onaylanan öneri, en son yayımlanmış sürümün içeriğine eklenerek yeni
  sürüm olarak aynı işlemde yayımlanır ve aynı değişiklik taslağa da yazılır. Taslaktaki yayımlanmamış
  diğer değişiklikler bu yayına girmez. Yeni kurala taslağın sıradaki kural kimliği (`KuralNN`) verilir.
- **Yayın isteği:** Kural yöneticisi taslağın o anki revizyonunu onaya gönderir. Aynı anda en çok bir
  bekleyen yayın isteği vardır; yenisi öncekini geçersiz kılar. Onay, istekteki revizyonu yayımlar; taslak
  istekten sonra değiştiyse onay `409 publish_request_stale` alır ve istek geçersiz olur.
- Ret, 1–500 karakter gerekçe ister; gerekçe öneri sahibine görünür. Öneri yalnız `bekliyor` durumunda
  onaylanır, reddedilir veya geri çekilir; sonuçlanmış öneri değişmez.
- Öneriyi yalnız oturum açmış inceleyici veya kural yöneticisi gönderir; rolsüz kullanıcı `403` alır.
- Kural metni ve özeti LLM'e yalnız kural olarak gider (bugünkü sınır); öneri gerekçesi, grup adı ve ret
  gerekçesi LLM'e gitmez ve loga yazılmaz.
- Arayüz yalnız Türkçedir.

## İşlevsel gereksinimler

Requirement 1: Her inceleyici ve kural yöneticisi öneri gönderebilir; ayrı bir öneri yetkisi ve yetki
listesi yoktur (Decision 6). `GET /rule-proposals/capabilities` bu kullanıcılara `can_propose: true`
döndürür.

Requirement 2: Kullanıcı yeni kural önerisi gönderir (özet, ayrıntılı metin, öncelik, meta veri
işareti, isteğe bağlı gruplar ve isteğe bağlı kısa gerekçe). Biçim ve sınır ihlalleri `422` ile, bilinmeyen
grup `422 rule_group_unknown` ile reddedilir.

Requirement 3: Kullanıcı yeni grup önerisi gönderir (ad, açıklama, en son yayımlanmış sürümden kural
kodları, isteğe bağlı kısa gerekçe). Mevcut grup adıyla çakışan ad `422 rule_group_name_duplicate`,
yayımlanmış sürümde olmayan kod `422 rule_unknown`, boş kural listesi `422 proposal_rules_empty` alır.

Requirement 4: Öneri sahibi kendi önerilerini durumlarıyla (bekliyor, onaylandı, reddedildi, geri çekildi),
ret gerekçesiyle ve onaylandıysa yayımlandığı sürüm numarasıyla görür; bekleyen önerisini geri çeker.

Requirement 5: Süper yönetici bekleyen kural ve grup önerilerini ayrıntılı metinleriyle görür. Onay, öneriyi
en son yayımlanmış sürüme ekleyerek yeni sürüm yayımlar ve aynı değişikliği taslağa yazar (Decision 2);
yanıt yeni sürüm numarasını ve yeni kural kimliğini taşır. Onay anında grup adı artık çakışıyorsa, sürüm
200 kurala ulaştıysa veya önerinin kuralları artık yayımlanmış sürümde yoksa onay `409 proposal_conflict`
ile durur ve öneri bekliyor kalır.

Requirement 6: Kural yöneticisi taslağı yayımlamak için "Onaya gönder" der; istek taslak revizyonunu,
gönderen kişiyi ve en son yayımlanmış sürüme göre farkı (eklenen, değişen ve silinen kurallar; eklenen,
değişen ve silinen gruplar) taşır. Süper yönetici farkı görür; onay istekteki revizyonu yayımlar, ret
gerekçesi kural yöneticisine görünür. Kural yöneticisinin doğrudan yayın isteği
`403 publish_requires_approval` alır; süper yönetici doğrudan yayımlayabilir.

Requirement 7: Süper yöneticinin menüsünde "Kural onayları" sayfası ve bekleyen istek sayısı görünür; sayfa
kural önerilerini, grup önerilerini ve yayın isteklerini ayrı sekmelerde gösterir. Her inceleyici ve
kural yöneticisi "Kural önerilerim" sayfasını görür: yeni kural önerisi, yeni grup
önerisi ve öneri geçmişi. Kural önerisi formu özet ve ayrıntılı metni ayrı alanlarda ister; grup önerisi
formu yayımlanmış kuralları özetleriyle aranabilir listede seçtirir. Tüm metinler Türkçedir.

## API sözleşmesi

Ön ek `/api/dwhcodereview/v1`. Tüm uçlar geçerli oturum ister; hata zarfı
`{"detail":{"code":"...","message":"..."}}`.

- `GET /rule-proposals/capabilities` → `{can_propose: bool, can_decide: bool}` (arayüzün menüsü için).
- `GET /rule-proposals?scope=mine|pending|all&page=&page_size=` → öneriler; `pending` ve `all` yalnız süper
  yönetici. Öğe: `id`, `kind` (`rule`/`group`), durum, öneren, zaman, özet veya grup adı, karar veren, karar
  zamanı, ret gerekçesi, yayımlandığı sürüm, yeni kural kimliği.
- `POST /rule-proposals` → öneri oluşturur (201). Gövde: `kind` ve türüne göre alanlar. Hatalar:
  `403 proposal_forbidden`, `422 rule_summary_invalid`, `rule_text_invalid`, `rule_text_too_long`,
  `rule_group_name_invalid`, `rule_group_name_duplicate`, `rule_group_unknown`, `rule_unknown`,
  `proposal_rules_empty`.
- `GET /rule-proposals/{id}` → ayrıntı (sahip ve süper yönetici; diğerleri `404`).
- `POST /rule-proposals/{id}/withdraw` (sahip), `POST /rule-proposals/{id}/approve` ve
  `POST /rule-proposals/{id}/reject` `{reason}` (süper yönetici). Hatalar: `409 proposal_not_pending`,
  `409 proposal_conflict`, `422 rejection_reason_invalid`.
- `POST /rule-set/publish-requests` `{base_revision}` (kural yöneticisi; 201),
  `GET /rule-set/publish-requests?status=` , `GET /rule-set/publish-requests/{id}` (fark dahil),
  `POST /rule-set/publish-requests/{id}/approve` ve `.../reject` `{reason}` (süper yönetici). Hatalar:
  `409 rule_set_draft_conflict`, `409 publish_request_stale`, `409 publish_request_not_pending`,
  `422 rule_set_empty`.
- `POST /rule-set/versions` yalnız süper yöneticiye açık kalır; kural yöneticisi
  `403 publish_requires_approval` alır.
- 1.1.0 ile `/rule-proposers` uçları kaldırıldı (Decision 6).

## Güvenlik ve yetkilendirme

- Onay ve ret yalnız süper yöneticidedir. Denetimler arka uçta
  her uçta yapılır; menü gizlemek yetki denetimi değildir.
- Öneri sahibi yalnız kendi önerilerini görür; başkasının önerisi `404`.
- Onay ve yayın aynı veritabanı işleminde yapılır; taslak ve en son sürüm satır kilidiyle okunur, iki onay
  aynı sürüm numarasını üretemez.
- Ayrıntılı metin kural metni olarak saklanır ve LLM'e gider; özet, gerekçe ve grup adı LLM'e gitmez.
  Kişisel veri veya parola içermemesi gerektiği formda yazılır (rules/55).

## Veri ve geçiş

- Yeni tablolar (Alembic göçü): **kural önerisi** (kiracı, `public_id`, tür, öneren, durum, özet, ayrıntılı
  metin, öncelik, meta veri işareti, grup adı ve açıklaması, kural kodları, grup kimlikleri, gerekçe, karar
  veren, karar zamanı, ret gerekçesi, yayımlanan sürüm, yeni kural kodu), **yayın isteği** (kiracı,
  `public_id`, isteyen, taslak revizyonu, durum, karar veren, karar zamanı, ret gerekçesi, yayımlanan sürüm)
  ve **kural önericisi** (kiracı, kullanıcı, yetkiyi veren, zaman). 1.1.0 ile kural önericisi tablosu
  kullanılmaz; geçmiş kayıtlar sessizce silinmesin diye tablo yerinde ve salt okunur kalır.
- Kural özetinin taslak ve sürüm kurallarındaki sütunu [rule-management](../001-rule-management/PRD.md)
  revizyonundadır ve aynı göçte eklenir.
- Göç genişleticidir; geri alma, öneri veya yayın isteği kaydı varken veri kaybını bildirip durur.

## Gözlemlenebilirlik

- Log olayları: `rule_proposal.created/withdrawn/approved/rejected` (öneri `public_id`, tür, kullanıcı
  `public_id`, onayda sürüm numarası), `rule_publish_request.created/approved/rejected/stale`,
  `rule_proposer.granted/revoked`. Kural metni, özet, grup adı ve gerekçeler loga yazılmaz.
- Yeni ölçüm eklenmez (Decision 5).

## Dağıtım etkisi

- Yeni göç; yeni sır, ağ çıkışı veya chart değişikliği yoktur.
- Kural yöneticilerinin yayın alışkanlığı değişir: yayın artık süper yönetici onayıyla olur.

## Test stratejisi

- Arka uç birim: özet/metin/ad doğrulaması, öneriyi en son sürüme ekleme (kural kimliği ataması, grup
  üyeliği), yayın isteği farkının hesabı.
- Gerçek PostgreSQL: önerinin onayla yeni sürüm olarak yayımlanması ve taslağa yazılması; taslaktaki
  yayımlanmamış değişikliklerin bu yayına girmemesi; reddin gerekçesi; geri çekme; çakışan onayda
  `409 proposal_conflict`; yayın isteğinin onayı ve taslak değişince `publish_request_stale`; eşzamanlı iki
  onayda tek sürüm numarası; göçün geri alınması.
- API: yetkisiz öneri `403`, başkasının önerisine `404`, kural yöneticisinin doğrudan yayınına `403`,
  onay/retin yalnız süper yöneticide olması, her inceleyici ve kural yöneticisinin öneri gönderebilmesi.
- Ön yüz (Vitest): öneri formları (özet ve ayrıntı zorunlu), öneri geçmişi ve durumları, Kural onayları
  sekmeleri, fark görünümü, ret gerekçesi, Kurallar sayfasında "Onaya gönder".

## Vektör ve gömme sözleşmesi (uygulanabilirse)

- Sağlayıcı / dağıtım sınırı: Uygulanamaz
- Model kimliği ve değişmez sürüm: Uygulanamaz
- Boyut ve normalleştirme: Uygulanamaz
- Uzaklık metriği ve indeks stratejisi: Uygulanamaz
- Getirim kalitesi/duyarlılık ve gecikme eşikleri: Uygulanamaz
- Kaynak sınıflandırması, en aza indirme ve saklama: Uygulanamaz
- Yeniden gömme, geçiş ve geri alma: Uygulanamaz

## Kabul kriterleri

- [ ] Acceptance 1: L1 — Otomatik testlerden geçti: öneri doğrulaması, en son sürüme ekleme ve yayın isteği
  farkı birim testleri geçer (Requirement 2, 3, 5, 6).
- [ ] Acceptance 2: L1 — Otomatik testlerden geçti: onayla yayımlama, taslağın yayımlanmamış
  değişikliklerinin dışarıda kalması, ret ve geri çekme, çakışmada `409`, bayat yayın isteği ve eşzamanlı
  onay gerçek PostgreSQL testleriyle geçer (Requirement 4, 5, 6); OpenAPI kayıtlı yapıtla aynıdır.
- [ ] Acceptance 3: L1 — Otomatik testlerden geçti: rol denetimleri (`403`, `404`) ve her inceleyici ile
  kural yöneticisinin yetki almadan öneri gönderebilmesi testleri geçer (Requirement 1, 2, 6).
- [ ] Acceptance 4: L2 — Gerçek istemci/ortamda doğrulandı: inceleyici yetki almadan özet ve ayrıntıyla kural, ardından o kuralı içeren grup önerir; süper yönetici
  ayrıntıları görüp onaylar ve kural ile grup yeni sürümde yayımlanır; reddedilen öneride gerekçe sahibine
  görünür; kural yöneticisinin yayın isteği onaylanınca taslak yayımlanır (Requirement 1–7).

## Kararlar

- Decision 1: (1.1.0 ile Decision 6'ya bırakıldı) Kural ve grup önerisi, süper yöneticinin "kural
  önerebilir" yetkisi verdiği kullanıcılara açıktı. Proje sahibinin 2026-10-14 kararı.
- Decision 2: Onaylanan öneri hemen yayımlanır: en son yayımlanmış sürüme eklenerek yeni sürüm olur ve
  taslağa da yazılır. Proje sahibinin 2026-10-14 kararı. Gerekçe: tek onayla canlıya geçer; taslaktaki
  onaylanmamış değişiklikler bu yolla yayımlanmaz.
- Decision 3: Kural yöneticisi taslağı düzenlemeye devam eder ama yayımlayamaz; yayın süper yönetici
  onayına tabidir. Proje sahibinin 2026-10-14 kararı. Gerekçe: yayımlanan her kural değişikliği tek
  yetkiliden geçer.
- Decision 4: Kural önerisi tek cümlelik özet ve ayrıntılı metin ister; süper yönetici dışındaki
  kullanıcılar kuralları özetleriyle görür ([rule-management](../001-rule-management/PRD.md) Requirement
  12). Proje sahibinin 2026-10-14 kararı.
- Decision 5: Bu yetenek için yeni ölçüm eklenmez; log olayları yeterlidir.
- Decision 6: Öneri yetkisi kalkar; her inceleyici ve kural yöneticisi kural ve grup önerisini onaya
  gönderir. Karar yine yalnız süper yöneticidedir. Proje sahibinin 2026-10-15 kararı ("kuralı eskiden
  herkes öneremiyordu … herkes yollayabilsin onaya"). Gerekçe: öneri yalnız onaya düşer; yayın yine tek
  yetkili denetimden geçer.
- Decision 7: Yayın isteği (Requirement 6) kaldırılır: [directory-login](../../../application-foundation/PRDs/001-directory-login/PRD.md)
  Decision 14 ile kural yöneticisi rolü kalktı; taslağı süper yönetici düzenler ve doğrudan yayımlar.
  `/rule-set/publish-requests` uçları ve "Yayın istekleri" sekmesi kalkar; yayın isteği tablosu
  geçmiş kayıtlar sessizce silinmesin diye yerinde kalır, artık yazılmaz. Kural onaylarında yalnız kural ve grup önerileri kalır. Proje sahibinin
  2026-10-15 kararı.
- Decision 8: Kural ve grup önerileri ile onayları kaldırılır. `/rule-proposals` uçları, öneri hizmeti,
  deposu, şemaları ve kuralları; ön yüzde "Kural önerilerim", "Kural onayları", onay akışı kartları ve
  menü sayaçları kalkar; e2e 06 senaryosu silinir. Kuralları, grupları ve taslağı yalnız süper yönetici
  düzenler ve doğrudan yayımlar ([rule-management](../001-rule-management/PRD.md),
  [directory-login](../../../application-foundation/PRDs/001-directory-login/PRD.md) Decision 14).
  `rule_proposal`, `rule_publish_request` ve `rule_proposer` tabloları geçmiş kayıtlar sessizce
  silinmesin diye yerinde kalır, artık okunmaz ve yazılmaz (rules/41); eski adresler
  (`/kural-onerilerim`, `/kural-onaylari`) kural kitaplığına ve Yönetim'e yönlendirir. Proje
  sahibinin 2026-10-19 kararı ("onay ve öneri kısımlarını tamamen kaldır"). Gerekçe: küçük ekipte kural değişikliği doğrudan tek
  yetkiliden geçer; öneri kuyruğu bakım yükü getirir.

## Açık sorular

Açık soru kalmadı.

## Teslim akışı

Belirtim → Plan → Görevler → Uygulama ([Plan](plan.md), [Görevler](tasks.md)).

## Riskler

- Süper yönetici tek onay noktasıdır; yoğun dönemde onay beklemesi kural yayınını yavaşlatır. Menüdeki
  bekleyen istek sayısı bunu görünür kılar.
- Onaylanan öneri en son sürüme eklenirken taslakta bekleyen yayın isteği varsa, o istek taslak değiştiği
  için bayatlar ve kural yöneticisi yeniden gönderir.
- Özet ile ayrıntılı metin birbirini tutmayabilir; LLM ayrıntılı metni uygular. Süper yönetici onayda ikisini
  birlikte görür.
