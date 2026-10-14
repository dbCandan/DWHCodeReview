# Plan — rule-management

[PRD](PRD.md) belgesinden türetildi (`Status: Accepted`, Version 1.1.0). Proje kipi `separated-web`;
sabit yığın `python-fastapi` arka uç ve `sqlalchemy-alembic` kalıcılığıdır.

## Veri modeli

Şema yetkisi `app/backend/app/domain/models/rule_set.py`; tablolar göç `202609260001` ile oluşur.

- `rule_set_draft`: kiracı başına tek kayıt (`tenant_id` tekil), `revision` değişiklik sayacı
  (Requirement 4), `next_rule_number` ilk serbest kural numarası (Requirement 3); son değiştiren ve
  zaman iskeletin `updated_by`/`updated_at` sütunlarıdır.
- `rule_set_draft_rule`: taslak kuralı; doğal anahtar (`rule_set_draft_id`, `rule_code`), grup
  (`critical`/`normal`), grup içi sıra, en çok 8.000 karakter metin, `requires_metadata`
  (Requirement 2). Kaydetmede taslaktan çıkan kural yazılımsal silinir; kullanılmış kimlik
  görünür kalır (Requirement 3).
- `rule_set_version`: `public_id`, kiracı içinde tekil `number`, `published_at`,
  `published_by_user_id` (içe aktarımda boş), `source` (`arayuz`/`ice-aktarim`), `content_sha256`
  (Requirement 5, 8). Uygulamada güncelleme ve silme yolu yoktur.
- `rule_set_version_rule`: sürümle birlikte eklenen ve değişmeyen kurallar.
- `summary` (en çok 200 karakter, boş olabilir): taslak ve sürüm kurallarına eklenir; göç
  [rule-proposals](../009-rule-proposals/plan.md) göçüdür (`202610140001`). Mevcut kurallar boş özetle
  kalır (Requirement 2, 12).
- Kural kimliği biçimi `^Kural(0[1-9]|[1-9][0-9]+)$` veritabanı kısıtıdır.

## Katmanlar ve dosyalar

| Katman | Dosyalar | Gereksinim |
|---|---|---|
| Alan kuralları | `app/backend/app/domain/rule_set.py` (kırpma, boş kural atma, kimlik biçimi, yineleme, sınırlar, özet doğrulaması ve ilk cümle yedeği, ilk serbest numara, içerik parmak izi, `PublishedRuleSet`) | Requirement 2, 3, 5, 7, 12 |
| Depo | `app/backend/app/infrastructure/repositories/rule_set_repository.py` | Requirement 1–8 |
| Hizmet | `app/backend/app/services/rule_set_service.py` (`RuleSetService.latest_published_rule_set` inceleme koşumlarının tek okuma işlevidir) | Requirement 1–8 |
| API | `app/backend/app/api/rule_set/router.py`, `app/backend/app/schemas/rule_set/contracts.py`, `app/backend/app/api/auth/dependencies.py` (`require_any_role`), `app/backend/app/api/validation.py` | API sözleşmesi, Requirement 8 |
| İçe aktarım | `schema/alembic/versions/202609260002_import_previous_review_rules.py`, `schema/alembic/data/review_rules.json` | Requirement 9, Decision 3 |
| Sözleşme | `specs/openapi/dwhcodereview-api.yaml`, üretilmiş `app/frontend/src/types/api.d.ts` | API sözleşmesi |
| Ön yüz | `app/frontend/src/pages/RulesPage.tsx`, `app/frontend/src/components/rules/RuleEditorColumn.tsx` (özet alanı), `app/frontend/src/pages/PublishedRulesPage.tsx` (süper yönetici dışında sade görünüm), `app/frontend/src/lib/rules.ts` (görünen özet), `app/frontend/src/services/ruleSet.ts` | Requirement 4, 10, 11, 12 |

## Uygulama kararları

- Kaydetme ve yayımlama kiracının taslak satırını `SELECT … FOR UPDATE` ile kilitler; taslak yoksa
  ilk yazmada `ON CONFLICT DO NOTHING` ile oluşur. Kilit altında `base_revision` karşılaştırılır
  (409 `rule_set_draft_conflict`); böylece eşzamanlı iki yayımlama sırayla çalışır ve ikincisi aynı
  içerikli sürümü 200 ile döner (Requirement 4, 5).
- Kaydetmede önce boş kurallar atılır, sonra biçim (`rule_id_invalid`), yineleme
  (`rule_id_duplicate`), metin uzunluğu (`rule_text_too_long`) ve kural sayısı
  (`rule_set_too_large`) denetlenir. Taslakta olmayan her kimlik yeni kuraldır: daha önce herhangi
  bir taslakta (silinmiş dahil) veya sürümde kullanıldıysa ya da ilk serbest numaradan küçükse
  `rule_id_reused` alır. Bu nedenle taslaktan çıkarılıp kaydedilen bir kural aynı kimlikle geri
  eklenemez; yeni kimlik alır.
- Yayımlama taslağın içerik parmak izini (grup, sıra, kimlik, metin, işaret üzerinden kanonik JSON
  SHA-256; özet yalnız girilmişse kurala eklenir, böylece özetsiz sürümlerin parmak izi değişmez) en son
  sürümle karşılaştırır; aynıysa yeni sürüm oluşmaz. Boş taslak 422
  `rule_set_empty` alır. Yayımlama taslağın `revision` değerini değiştirmez.
- `GET /rule-set` taslak yoksa `revision` 0 ve `next_rule_id` `Kural01` döner; yayımlanmış sürüm
  yoksa `draft_differs` taslağın boş olmamasıdır. Yayımlayanın görünen adı `published_by_name`,
  içe aktarımda boş ve `source` `ice-aktarim` olarak döner.
- Sürüm listesi `page` (≥1) ve `page_size` (1–100, varsayılan 20) alır, numaraya göre azalır.
- Rol denetimi her uçta arka uçtadır: taslak `kural-yoneticisi` (süper yönetici de okur), yayımlama
  (`POST /rule-set/versions`) yalnız süper yönetici; kural yöneticisi `403 publish_requires_approval`
  alır ve yayın isteği gönderir ([rule-proposals](../009-rule-proposals/plan.md)). Okuma uçları iki rol.
- Özet kırpılır; boşsa "girilmemiş" saklanır; 200 karakteri aşan veya satır sonu içeren özet
  `422 rule_summary_invalid` alır. Görünen özet: girilmişse özet, değilse metnin ilk cümlesi (ilk `.`,
  `!`, `?` ve ardından boşluk ya da metin sonu; bulunamazsa ilk satır), en çok 200 karakter. İçe
  aktarılan kurallar "KURAL ADI: … AÇIKLAMA: …" biçimindedir; metinde "AÇIKLAMA:" başlığı varsa ilk
  cümle o bölümden alınır. Hesap ön yüzde `lib/rules.ts` içindedir; API ham `summary` döner.
- Sade görünüm (Requirement 12): süper yönetici dışındaki kullanıcı "Yayımlanmış kurallar" sayfasında
  kimlik, görünen özet, öncelik ve meta veri etiketini görür; ayrıntılı metin yalnız süper yöneticide
  açılır. Bu bir görünüm kararıdır, yetki sınırı değildir; sürüm uçları metni tüm rollere döner (LLM'e
  giden kural metni gizli veri değildir).
  Biçimsiz istek 422 `invalid_request` zarfıyla döner; gövde değerleri yanıtta ve logda yer almaz.
- Log olayları: `rule_set.draft_saved` (revision, grup sayıları, kullanıcı `public_id`),
  `rule_set.version_published` (numara, sayılar, parmak izi, `created`), `rule_set.import`
  (`imported`/`skipped`/`failed`). Kural metni hiçbir olayda yoktur.

## Göç ve dağıtım bağımlılığı

- `202609260002` yalnız veri göçüdür (Decision 3): `schema/alembic/data/review_rules.json`
  kopyasını SHA-256 `2346ad4769259b5a09b4d1c742ec0a6f3d575cdb054bf126fb395cdc709a25eb` ile
  doğrular, `platform` kiracısına `published` içeriğini 1 numaralı `ice-aktarim` sürümü
  (`published_at` 2026-04-10T14:05:15Z, yayımlayan boş) ve `draft` içeriğini `revision` 0,
  `next_rule_number` 13 olan taslak olarak yazar. Kiracının taslağı veya sürümü varsa hiçbir şey
  yazmaz (`skipped`). Parmak izi tutmazsa, `KuralNN` dışı kimlik, yinelenen kimlik veya geçersiz
  alan varsa göç hata verip durur. Geri alma kuralları silmez; yeniden yükseltme tablolar dolu
  olduğu için yazmaz.
- Veri kopyası `schema/` altında olduğu için hem göç hem arka uç imajına girer. Chart ve Secret
  değişikliği yoktur.

## Doğrulama komutları

- `scripts/db.sh apply`, `scripts/db.sh validate`, `scripts/db.sh status`
- `scripts/quality-gate.sh backend` ve devir için `scripts/quality-gate.sh all`
- `scripts/export-openapi.sh --check`, `scripts/generate-types.sh --check`

## İzlenebilirlik

| Gereksinim | Kabul | Görev |
|---|---|---|
| Requirement 1, 4, 8 | Acceptance 1 | Task 2, Task 3, Task 5 |
| Requirement 2, 3 | Acceptance 1 | Task 1, Task 3 |
| Requirement 5, 6 | Acceptance 1 | Task 1, Task 3 |
| Requirement 7 | Acceptance 1, Acceptance 5 | Task 3, Task 8 |
| Requirement 9 | Acceptance 2, Acceptance 4 | Task 4, Task 7 |
| Requirement 10, 11 | Acceptance 3, Acceptance 4 | Task 6, Task 7, Task 11 |
| Requirement 2, 12 (özet) | Acceptance 1, Acceptance 3 | Task 9, Task 10, Task 11 |
| Requirement 5 (onaylı yayın) | Acceptance 1, Acceptance 4 | Task 10, Task 12 |
