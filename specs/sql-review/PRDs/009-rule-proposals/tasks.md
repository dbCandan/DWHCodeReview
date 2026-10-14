# Görevler — rule-proposals

[Plan](plan.md) belgesinden türetildi. Her görev önce başarısız olan testle başlar (kırmızı), sonra en
küçük uygulamayla geçer (yeşil). Kanıt satırları görev bitince doldurulur; uydurulmuş kanıt yazılmaz.
[Kural grubu seçimi](../007-rule-group-selection/tasks.md) çoklu üyeliği bu görevlerden önce yapılır.

Yerel kanıt (2026-10-14, kişisel makine): `pytest` (gerçek PostgreSQL 17) 848 geçti, 1 bilinen ve bu işten bağımsız hata (`test_config.py::test_otel_process_variables_stop_start_up[otel_sdk_disabled]`); Vitest 201/201; ruff, black, isort, mypy, tsc ve eslint temiz; `alembic check` temiz. Tarayıcı senaryoları yerel önizlemede (PostgreSQL, Vite, Chromium) koştu: `sql-review/run-all.mjs` 6/6 ve `auth/run-all.mjs` 1/1 geçti. LLM adımlarında onaylı uç yerine yerel, OpenAI uyumlu bir sahte uç kullanıldı; SQL Server yoktu. `scripts/quality-gate.sh all` ve gerçek LLM/SQL Server ile L2 kanıtı kurumsal ortamda alınmalıdır.

- [x] Task 1 — Requirement 2, 3, 5, 6 / Acceptance 1: alan kuralları. Kural önerisi doğrulaması (özet
  1–200 ve satır sonu yok, metin 1–8.000, öncelik), grup önerisi doğrulaması (ad, açıklama, boş olmayan
  tekrarsız kodlar), öneriyi yayımlanmış içeriğe ekleme (yeni `KuralNN`, grubun sonuna ekleme, üyelikler,
  200 kural, 50 grup, ad çakışması, bilinmeyen kod veya grupta çakışma), yayın isteği farkı. Kanıt:
  `app/backend/tests/unit/test_rule_proposal_rules.py`.
- [x] Task 2 — Veri modeli / Acceptance 2: modeller ve göç `202610140001_rule_proposals.py` (üç tablo ve
  `summary` sütunları), CHECK kısıtları, kiracıda tek bekleyen yayın isteği; dolu kayıt varken
  `downgrade`'in durması, boşken geri alınıp yeniden uygulanması. Kanıt:
  `app/backend/tests/integration/test_data_model.py` ek vakaları,
  `app/backend/tests/integration/test_rule_proposals_migration.py`, `scripts/db.sh validate`.
- [x] Task 3 — Requirement 1, 2, 3, 4 / Acceptance 2, Acceptance 3: öneri yetkisi uçları
  (`/rule-proposers`), öneri oluşturma, listeleme (`mine`, `pending`, `all`), ayrıntı ve geri çekme;
  yetkisiz `403 proposal_forbidden`, başkasının önerisine `404`, `422` kodları. Kanıt:
  `app/backend/tests/integration/test_rule_proposals_api.py`.
- [x] Task 4 — Requirement 5 / Acceptance 2: onay ve ret. Onayın yeni sürümü yayımlaması ve taslağa
  yazması, taslaktaki yayımlanmamış değişikliklerin yayına girmemesi, yanıtta sürüm numarası ve yeni kural
  kimliği, ret gerekçesi, `409 proposal_not_pending` ve `409 proposal_conflict`, eşzamanlı iki onayda
  tekil sürüm numaraları, karar uçlarının yalnız süper yöneticide olması. Kanıt:
  `test_rule_proposals_api.py` ek vakaları.
- [x] Task 5 — Requirement 6 / Acceptance 2, Acceptance 3: yayın istekleri. Oluşturma, öncekini geçersiz
  kılma, farkla ayrıntı, onayla yayımlama, taslak değişince `409 publish_request_stale`, ret, kural
  yöneticisinin `POST /rule-set/versions` çağrısına `403 publish_requires_approval`, onaylanan önerinin
  bekleyen isteği bayatlatması. Kanıt: `app/backend/tests/integration/test_rule_publish_requests_api.py`,
  `test_rule_set_api.py` güncellenen vakaları.
- [x] Task 6 — API sözleşmesi / Acceptance 2: OpenAPI ve üretilmiş ön yüz tipleri; ön yüz hizmeti
  `services/ruleProposals.ts`. Kanıt: `scripts/export-openapi.sh --check`,
  `scripts/generate-types.sh --check`.
- [x] Task 7 — Requirement 1, 6, 7 / Acceptance 4: ön yüz. "Kural önerilerim" (özet ve ayrıntı ayrı ve
  zorunlu, grup önerisinde özetlerle aranabilir kural listesi, öneri geçmişi, durum, ret gerekçesi, geri
  çekme), "Kural onayları" (öneri, grup önerisi ve yayın isteği sekmeleri, ayrıntılı metin, fark görünümü,
  onay, gerekçeli ret, öneri yetkisi listesi), menüde bekleyen sayı, Kurallar sayfasında "Onaya gönder".
  Kanıt: `RuleProposalsPage.test.tsx`, `RuleApprovalsPage.test.tsx`, `RulesPage.test.tsx`,
  `AppShell.test.tsx` ek vakaları.
- [x] Task 8 — Requirement 1–7 / Acceptance 4: L2 doğrulaması. `e2e/sql-review/06-rule-proposals.mjs`:
  süper yönetici inceleyiciye yetki verir; inceleyici özet ve ayrıntıyla kural ve o kuralı içeren grup
  önerir; süper yönetici onaylar, kural ve grup yeni sürümde görünür; reddedilen öneride gerekçe sahibine
  görünür; kural yöneticisinin yayın isteği onaylanır. Senaryo eklediklerini geri alır. QUALITY_MANIFEST
  satırı eklenir. Kanıt: 2026-10-14 yerel önizlemede geçti; kural yöneticisinin yayın isteği akışı
  `01-rules-and-roles.mjs` içinde doğrulandı.
- [ ] Task 9 — Kalite kapısı: `scripts/quality-gate.sh all` geçer; sonuç bu dosyanın başına kanıt
  olarak yazılır.

## Ortam notu

Kalite kapıları, yönetilen inceleme ve proje kancaları yalnız kurumsal ortamda, proje kökünde açılan
oturumda çalışır. Bu görevlerin L1/L2 kanıtı oradan alınmalıdır.
