# Plan — rule-group-selection

[PRD](PRD.md) belgesinden türetildi (`Status: Accepted`, Version 2.0.0). Proje kipi `separated-web`;
sabit yığın `python-fastapi` arka uç ve `sqlalchemy-alembic` kalıcılığıdır.

## Veri modeli

Şema yetkisi `app/backend/app/domain/models/rule_set.py` ve `app/backend/app/domain/models/review.py`;
değişiklik tek göçle gelir: `schema/alembic/versions/202610050001_rule_groups.py`.

- `rule_set_draft_group` (yeni): `rule_set_draft_id`, `public_id`, `name` (1–80), `description`,
  `position`. Silinen grup yazılımsal silinir (Requirement 1).
- `rule_set_version_group` (yeni): `rule_set_version_id`, `rule_group_public_id` (taslak grubunun kimliği
  aynen kopyalanır), `name`, `description`, `position`; uygulamada güncelleme ve silme yolu yoktur.
- `rule_set_draft_rule_group` (yeni): taslak kuralı ile aynı taslağın grubu arasındaki üyelik; bileşik
  yabancı anahtarlar üyeliği aynı taslakla sınırlar (Decision 1).
- `rule_set_version_rule_group` (yeni): sürüm kuralı (sürüm + kural kodu) ile aynı sürümün grubu (sürüm +
  grup `public_id`) arasındaki donmuş üyelik.
- `review_run_rule_group` (yeni): koşum, grup `public_id`, sabitlenen sürümdeki ad, sıra (Requirement 5).
- `review_run_rule` (yeni): koşum, seçilen kural kodu, sıra (Requirement 5).
- `review_rule_result.rule_group_names` (yeni, JSONB dizi, varsayılan boş): kural sonucunun koşum
  anındaki grup adları (Requirement 6, 7).

## Katmanlar ve dosyalar

| Katman | Dosyalar | Gereksinim |
|---|---|---|
| Alan kuralları | `app/backend/app/domain/rule_set.py` (grup adı doğrulama, 50 grup sınırı, çoklu üyelik ve tekrarsızlık, parmak izine grup ve üyeliklerin yalnız grup varsa girmesi, `PublishedRuleSet.select(group_ids, rule_codes)` birleşimi, kritik-önce sıra) | Requirement 1, 3, 4, Decision 1, 6 |
| Modeller | `app/backend/app/domain/models/rule_set.py`, `app/backend/app/domain/models/review.py` | Veri modeli |
| Depo | `app/backend/app/infrastructure/repositories/rule_set_repository.py`, `app/backend/app/infrastructure/repositories/review_repository.py` | Requirement 1–5 |
| Hizmet | `app/backend/app/services/rule_set_service.py`, `app/backend/app/services/review_run_service.py`, `app/backend/app/services/review_export.py`, `app/backend/app/services/review_history_service.py`, `app/backend/app/services/scheduled_review_scheduler.py` (özet e-postada grup sayımı) | Requirement 2–7 |
| API | `app/backend/app/schemas/rule_set/contracts.py`, `app/backend/app/schemas/reviews/contracts.py`, `app/backend/app/schemas/reviews/events.py`, `app/backend/app/schemas/review_runs/contracts.py`, `app/backend/app/api/reviews/router.py` | API sözleşmesi |
| Göç | `schema/alembic/versions/202610050001_rule_groups.py` | Veri ve geçiş, Decision 4 |
| Sözleşme | `specs/openapi/dwhcodereview-api.yaml`, üretilmiş `app/frontend/src/types/api.d.ts` | API sözleşmesi |
| Ön yüz | `app/frontend/src/components/rules/RuleEditorColumn.tsx` (kural başına çoklu grup seçimi), `app/frontend/src/lib/rules.ts`, `app/frontend/src/components/review/RuleSelectionPicker.tsx` (aranabilir kural listesi, grupla hızlı seçim), `ObjectReviewPage.tsx`, `ScriptReviewPage.tsx`, `ReviewResultsView.tsx` (grup etiketleri, grup süzgeci), `ReviewHistoryPage.tsx`, `services/reviews.ts`, `contexts/ReviewSessionContext.tsx` | Requirement 1, 6–8 |
| Tarayıcı senaryosu | `e2e/sql-review/04-rule-groups.mjs` | Acceptance 4 |

## Uygulama kararları

- **Parmak izi uyumu:** Kanonik JSON'a grup tanımları ve her kuralın sıralı grup kimlikleri yalnız en az bir
  grup varsa eklenir; grupsuz sürümün parmak izi değişmez.
- **Süzme yeri:** `review_run_service.py` sürümü bir kez sabitler, sonra `PublishedRuleSet.select` ile
  seçilen grupların ve kuralların birleşimine süzer. Hata sırası: `no_published_rule_set`, sonra
  `rule_group_unknown`, `rule_unknown`, `rule_group_selection_empty`; hepsi akış açılmadan döner. Süzülmüş
  küme kritik-önce ve sürüm içi sırayı korur; ortak kural bir kez yer alır.
- **Taslak kaydı:** `PUT /rule-set/draft` grupları ve üyelikleri aynı kilitli işlemde yazar; bilinmeyen
  gruba üyelik `rule_group_unknown_membership`, aynı kuralda tekrarlı grup aynı kodla reddedilir.
- **Grup silme:** Silinen grubun üyelik satırları aynı işlemde silinir; kuralların diğer üyelikleri sürer.
- **Sonuçta gruplar:** Kural sonucu sabitlenen sürümdeki grup adlarını sürüm içi grup sırasıyla taşır;
  CSV'de `; `, SQL yorumunda virgülle birleştirilir (review-history-export Decision 9).
- **Ön yüz:** Koşum ekranındaki `RuleSelectionPicker` kural kodlarını tutar; grup "hızlı seçim" düğmesi o
  grubun kodlarını ekler veya çıkarır. İsteğe seçili kurallar `rule_codes[]` olarak gider; arayüz
  `rule_group_ids[]` göndermez (grup seçimi kurallara açılır). API grup kimliğini de kabul etmeye devam
  eder (zamanlanmış inceleme ve doğrudan API kullanımı).
- **Geri alma (Decision 4):** `downgrade`, grup tanımı, üyelik, koşum seçimi veya dolu
  `rule_group_names` varken açıklayıcı hatayla durur.
- Log olayları: `rule_set.group_created` / `group_deleted`; koşum loguna seçilen grup ve kural sayısı. Ad ve
  metin loga girmez; yeni ölçüm yoktur (Decision 5).

## Göç ve dağıtım bağımlılığı

- `202610050001` yalnız genişleticidir; mevcut sürümler grupsuz, mevcut koşumlar "tüm kurallar" görünür.
- Yeni sır, ağ çıkışı veya chart değişikliği yoktur.

## Doğrulama komutları

- `scripts/db.sh apply`, `scripts/db.sh validate`, `scripts/db.sh status`
- `scripts/quality-gate.sh backend`, `scripts/quality-gate.sh frontend`, devir için `scripts/quality-gate.sh all`
- `scripts/export-openapi.sh --check`, `scripts/generate-types.sh --check`
- `scripts/e2e.sh` (Acceptance 4)

## İzlenebilirlik

| Gereksinim | Kabul | Görev |
|---|---|---|
| Requirement 1, 2 | Acceptance 1, Acceptance 4 | Task 1, Task 2, Task 3, Task 7 |
| Requirement 3 | Acceptance 2 | Task 2, Task 3 |
| Requirement 4 | Acceptance 1, Acceptance 3 | Task 1, Task 4 |
| Requirement 5 | Acceptance 2 | Task 2, Task 4 |
| Requirement 6 | Acceptance 4 | Task 4, Task 8 |
| Requirement 7 | Acceptance 3 | Task 5, Task 8 |
| Requirement 8 | Acceptance 4 | Task 7, Task 8, Task 9 |
| Decision 4 (geri alma) | Acceptance 2 | Task 2 |
