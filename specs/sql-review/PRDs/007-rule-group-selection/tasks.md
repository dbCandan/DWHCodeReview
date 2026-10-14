# Görevler — rule-group-selection

[Plan](plan.md) belgesinden türetildi. Her görev önce başarısız olan testle başlar (kırmızı), sonra en
küçük uygulamayla geçer (yeşil). Kanıt satırları görev bitince doldurulur; uydurulmuş kanıt yazılmaz.

Yerel kanıt (2026-10-14, kişisel makine): `pytest` (gerçek PostgreSQL 17) 848 geçti, 1 bilinen ve bu işten bağımsız hata (`test_config.py::test_otel_process_variables_stop_start_up[otel_sdk_disabled]`); Vitest 201/201; ruff, black, isort, mypy, tsc ve eslint temiz; `alembic check` temiz. Tarayıcı senaryoları yerel önizlemede (PostgreSQL, Vite, Chromium) koştu: `sql-review/run-all.mjs` 6/6 ve `auth/run-all.mjs` 1/1 geçti. LLM adımlarında onaylı uç yerine yerel, OpenAI uyumlu bir sahte uç kullanıldı; SQL Server yoktu. `scripts/quality-gate.sh all` ve gerçek LLM/SQL Server ile L2 kanıtı kurumsal ortamda alınmalıdır.

- [x] Task 1 — Requirement 1, 4, Decision 1, 6 / Acceptance 1: alan kuralları. Grup adı doğrulama (1–80,
  tekil), 50 grup sınırı, çoklu üyelik ve kural başına tekrarsızlık, seçilen grupların ve kuralların
  birleşimiyle süzme (kritik-önce ve sürüm içi sıra, ortak kural bir kez), boş seçimin "tüm kurallar"
  olması, bilinmeyen grup/kural ve boş birleşimin reddi, grupsuz sürümün parmak izinin değişmemesi. Kanıt:
  `app/backend/tests/unit/test_rule_group_rules.py`.
- [x] Task 2 — Veri modeli, Requirement 3, 5, Decision 4 / Acceptance 2: modeller ve göç
  `202610050001_rule_groups.py`; üyeliğin aynı taslak/sürümle sınırlı olması; dolu kayıt varken
  `downgrade`'in durması, boşken geri alınıp yeniden uygulanması. Kanıt:
  `app/backend/tests/integration/test_data_model.py` ek vakaları,
  `app/backend/tests/integration/test_rule_groups_migration.py`, `scripts/db.sh validate`.
- [x] Task 3 — Requirement 1, 2, 3 / Acceptance 1, Acceptance 2: depo, hizmet ve `/rule-set` uçları; grupların
  ve `rule_group_ids[]` üyeliklerinin kilitli yazılması, 409 çakışma, `rule_group_*` 422 kodları, grup
  silinince üyeliklerin kalkması, yayında grupların ve üyeliklerin donması. Kanıt:
  `app/backend/tests/integration/test_rule_set_api.py` ek vakaları.
- [x] Task 4 — Requirement 4, 5, 6 / Acceptance 1, Acceptance 3: koşum başlatma. Nesne ve SQL metni
  koşumunda `rule_group_ids[]` ve `rule_codes[]`, akış öncesi `rule_group_unknown`, `rule_unknown`,
  `rule_group_selection_empty`, `run_started` olayında seçim, koşum kaydına seçimin ve kural sonucuna grup
  adlarının yazılması, LLM'e yalnız seçilen kuralların bir kez gitmesi. Kanıt:
  `app/backend/tests/integration/test_rule_group_reviews.py`.
- [x] Task 5 — Requirement 7 / Acceptance 3: rapor ve dışa aktarma. Koşum ayrıntısında seçim, CSV'de
  `; ` ile ayrılmış `rule_group` sütunu, SQL yorumunda virgüllü gruplar, grupsuz kuralda boş değer. Kanıt:
  `app/backend/tests/unit/test_review_export.py` ve `test_rule_group_reviews.py` ek vakaları.
- [x] Task 6 — API sözleşmesi / Acceptance 2: OpenAPI ve üretilmiş ön yüz tipleri. Kanıt:
  `scripts/export-openapi.sh --check`, `scripts/generate-types.sh --check`.
- [x] Task 7 — Requirement 1, 8 / Acceptance 4: Kurallar sayfası. Grup ekleme, yeniden adlandırma, silme;
  kural başına çoklu grup ataması; grup değişikliğinin "Kaydedilmedi"yi tetiklemesi; 422 iletileri;
  "Yayımlanmış kurallar"da grupların görünmesi. Kanıt: `app/frontend/src/pages/RulesPage.test.tsx`,
  `app/frontend/src/pages/PublishedRulesPage.test.tsx` ek vakaları.
- [x] Task 8 — Requirement 6, 7, 8 / Acceptance 4: inceleme ve sonuç ekranları. Aranabilir kural listesi,
  grupla hızlı seçim ve tek tek seçim, seçili sayı, "Tüm kurallar" varsayılanı, sonuçlarda grup etiketleri
  ve grup süzgeci, geçmişte seçimin görünmesi. Kanıt: `RuleSelectionPicker.test.tsx`,
  `ObjectReviewPage.test.tsx`, `ScriptReviewPage.test.tsx`, `ReviewResultsView.test.tsx`,
  `ReviewHistoryPage.test.tsx` ek vakaları.
- [x] Task 9 — Requirement 1–8 / Acceptance 4: L2 doğrulaması. `e2e/sql-review/04-rule-groups.mjs`: aynı
  kural iki grupta; inceleyici bir grubu hızlı seçip bir kuralı ayrıca ekler; raporda yalnız işaretli
  kurallar bir kez ve grupları görünür; hiçbir şey seçilmeyince bütün kurallar çalışır; senaryo
  eklediklerini geri alır. Yerel PostgreSQL, test SQL Server ve onaylı LLM ucu gerekir. Kanıt: 2026-10-14 yerel önizlemede sahte LLM ucuyla tam dal geçti (LLM'siz dal da ayrıca geçti).
- [ ] Task 10 — Kalite kapısı: `scripts/quality-gate.sh all` geçer; sonuç bu dosyanın başına kanıt
  olarak yazılır.

## Ortam notu

Kalite kapıları, yönetilen inceleme ve proje kancaları yalnız kurumsal ortamda, proje kökünde açılan
oturumda çalışır. Bu görevlerin L1/L2 kanıtı oradan alınmalıdır.
