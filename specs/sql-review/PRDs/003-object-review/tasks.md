# Görevler — object-review

[Plan](plan.md) belgesinden türetildi. Kanıt: `scripts/quality-gate.sh all` 2026-10-02'de yerel
Compose yığınında geçti (arka uç 726/726, ön yüz 144/144 test; göç, OpenAPI, üretilmiş tip, yönetişim
sapması ve chart adımı dahil). Bu, L1 (otomatik testlerden geçti) kanıtıdır; otomatik testler sahte
katalog ve sahte LLM ile koşar, gerçek SQL Server ve kurum içi LLM ile yapılan gözlem Task 9 ve
Task 11'dedir.

- [x] Task V1 — Requirement 3, 4, 8, 13, 16 / Acceptance 2: koşum, koşum nesnesi, kural sonucu ve
  bulgu tabloları (göç `202609260001`); önemin yalnız `FAIL` sonucunda dolu olması ve 500
  karakterlik satır referansı (göç `202609260003`). Kanıt:
  `app/backend/tests/integration/test_data_model.py`.
- [x] Task V2 — Requirement 8, 9, 18: tipli ayar alanları. Kanıt:
  `app/backend/tests/unit/test_config.py`.
- [x] Task 1 — Requirement 8–13 / Acceptance 1: kaynaktaki `test_parse_review_response.py`
  testlerinin 11'i aynı girdi ve beklenen çıktıyla taşındı; eklenen altın testler `L012`,
  `L012–L015`, `line_numbers`, `line_number` ve kod parçasından satır çıkarımı, "ihlal değil"
  süzgeci, tek ve çok kurallı istekte boş `rule_code`, bilinmeyen kural kodu uyarısı, kural
  sonucu biçiminde geçersiz durum ve önem, iki parçada tek ve iki parça hatası, tekrar ayıklama,
  durum birleşimi ve uyarı birleştirmeyi kapsar. Kanıt:
  `app/backend/tests/unit/test_review_response_parser.py`.
- [x] Task 2 — Requirement 6, 7, 9, 12, 17 / Acceptance 2: kural başına çağrı ve sıra, meta verinin
  yalnız işaretli kurala gitmesi ve üç not, iki parça çağrı sayısı ve parça kimliği, ikinci
  parçanın özgün satır numarası, LLM hatasında sabit ileti ve tek satır uyarı, akış sayaçları;
  gerçek `httpx` uyarlayıcısı ve gerçek TCP sahte uçla koşum sınırının nesneler arasında ve süreç
  sınırının koşumlar arasında korunması. Kanıt: `app/backend/tests/unit/test_review_engine.py`.
- [x] Task 3 — Requirement 4, 5, 6, 16, 17 / Acceptance 2: sürüm sabitleme, koşum ve seçim
  satırları, tamamlanan koşumda sonuçlar ve incelenen metin, nesne hatası kodları, meta veri
  hatasında not, metin sınırında kesme ve uyarı, koşum sırasında LLM kaybında `failed`, açılışta
  `interrupted`, LLM çağrı özetlerinin koşuma ve parçaya bağlanması. Kanıt:
  `app/backend/tests/integration/test_object_review_api.py`.
- [x] Task 4 — Requirement 3, 14, 15, 18 / Acceptance 3: akış öncesi `401`, `403
  database_not_allowed`, `409 no_published_rule_set`, `422` (`selection_empty`,
  `object_type_invalid`, `invalid_request`), `429 rate_limited` ve metin
  incelemesiyle ortak sayaç, `503 llm_not_configured`; olay sırası; kopan
  bağlantıda 5 saniye içinde `cancelled`, yeni çağrı olmaması ve kısmi sonuç yazılmaması; günlükte
  SQL ve model metni olmaması. Kanıt: `app/backend/tests/integration/test_object_review_api.py`,
  `app/backend/tests/unit/test_review_throttle.py`.
- [x] Task 5 — Requirement 1, 2 / Acceptance 4 (arka uç): `/databases` ve
  `/databases/{database}/objects` sayfaları, metin, tür ve tarih süzgeçleri, `403`, `422`,
  `503`/`504` hata sınıfları. Kanıt: `app/backend/tests/integration/test_review_catalog_api.py`.
- [x] Task 6 — Requirement 20, API sözleşmesi / Acceptance 4 (arka uç): katmanlara bölme,
  `OpenAPI` ve üretilmiş ön yüz tipleri. Kanıt: `scripts/quality-gate.sh all` (`ruff`, `mypy`,
  `scripts/export-openapi.sh --check`, `scripts/generate-types.sh --check`).
- [x] Task 7 — Requirement 1–3, 14, 15, 19 / Acceptance 4: inceleme sayfası, canlı pencere,
  "Analizi durdur", sonuç penceresi ve Vitest testleri. Kanıt:
  `app/frontend/src/pages/ObjectReviewPage.test.tsx` (sunucuda süzgeç, çoklu veritabanı seçimi,
  SQL Server hatasında Türkçe ileti ve "Listeyi yenile"),
  `app/frontend/src/lib/eventStream.test.ts` (akış çözümleyici, parça sınırları, erken durma,
  kopma), `app/frontend/src/lib/reviewProgress.test.ts` (olay birleştirme),
  `app/frontend/src/contexts/ReviewSessionContext.test.tsx` (`fetch` akışı ve oturum başlığı,
  durdurma, kapanamayan canlı pencere, son olaysız kopma, akış öncesi 409/422/429/503),
  `app/frontend/src/components/review/ReviewResultsView.test.tsx` (sonuç, satır referansı, yanlış
  pozitif işareti). Yerel tarayıcıda SQL Server yokken sayfanın iletisi gözlendi
  (`e2e/sql-review/03-settings-objects-users.mjs`).
- [x] Task 8 — Gözlemlenebilirlik: koşum başladı/bitti ve süre, kural çağrısı ve kural sonucu
  ölçümleri; isteğe, LLM çağrılarına ve PostgreSQL komutlarına bağlanan `review_run` izi; SQL
  metni, kod parçası, model yanıtı, nesne ve veritabanı adı yok. OpenTelemetry altyapısı
  [directory-login](../../../application-foundation/PRDs/001-directory-login/tasks.md) Task 13'tedir.
  Kanıt: `app/backend/tests/integration/test_telemetry_signals.py`,
  `app/backend/tests/unit/test_telemetry.py`, `scripts/quality-gate.sh all`.
- [ ] Task 9 — Acceptance 5, Acceptance 6: test SQL Server'ı ve onaylı LLM ucuyla tarayıcıda L2
  (gerçek ortamda doğrulama). 2026-09-27'de yerel Compose'da şema kopyası SQL Server'ı ve geliştirici
  makinesindeki yerel model (`qwen3.6:35b`, OpenAI uyumlu uç; onaylı kurum LLM'i değil) ile nesne
  koşumları tamamlandı: tarayıcıda tek görünüm, API ile iki veritabanından üç nesne (biri iki parçalı,
  46.544 karakter); canlı ilerlemede belirteç sayısı, satır referanslı bulgular, koşum kaydında kural
  sürümü ve saklanan SQL metni görüldü; uygulama logunda SQL metni yoktu; istemci bağlantısı
  kapanınca koşum "iptal edildi" oldu. Onaylı kurum LLM ucu yerelden erişilemediği için açık.
- [x] Task 10 — Requirement 3, 14, 21, Decision 3, 7, 8 / Acceptance 3, Acceptance 4: nesne sınırının
  kaldırılması ve süzgece uyan bütün nesnelerin seçilmesi. Arka uç: göç `202610020001` (geri alınıp
  yeniden uygulanır; 50'den çok nesneli koşum varken geri alma durur), 51 ve 1.000 nesnelik
  koşumların tamamlanıp saklanması, teknik sınırı aşan istekte `422 invalid_request`, aynı anda
  işlenen nesne sayısının ve tanım okumalarının sınırlı kalması (sahte kataloğun eşzamanlı çağrı
  sayacı), yavaş okuyan bağlantının koşumu bekletmesi, büyük koşumda iptalin kalan nesneleri
  okumaması, `complete` olayının yalnız 50 nesneye kadar sonuç taşıması. Kanıt:
  `app/backend/tests/integration/test_object_review_api.py`,
  `app/backend/tests/integration/test_review_run_object_limit_migration.py`. Ön yüz: sınırsız seçim,
  sayfalar arasından "tümünü seç" (1.234 nesne), sayının gösterilmesi, yarıda bırakma, temizleme,
  teknik sınır iletisi, canlı pencerenin 400 nesnelik koşumda yalnız işlenen ve son biten nesneleri
  çizmesi, büyük koşumda sonuçların geçmişte açılması, `413` iletisi. Kanıt:
  `app/frontend/src/pages/ObjectReviewPage.test.tsx`,
  `app/frontend/src/contexts/ReviewSessionContext.test.tsx`,
  `app/frontend/src/lib/reviewProgress.test.ts`. Bu, L1 (otomatik testlerden geçti) kanıtıdır;
  sahte katalog ve sahte LLM ile koşuldu.
- [ ] Task 11 — Acceptance 7: gerçek SQL Server ve onaylı LLM ucuyla tarayıcıda 50'den çok nesnelik
  koşum, backend belleğinin gözlenmesi ve küme ingress'inin istek gövdesi sınırının doğrulanması;
  açık.

## 1.3.0 revizyonu (2026-10-15)

- [x] T-R15.1 Requirement 15, Decision 9: `POST /review-runs/{id}/cancel`; `ReviewRunRegistry` koşum kimliğiyle görevi bulur ve iptal eder; görevi olmayan koşum doğrudan "iptal edildi" olur; olay okuyucusu koşum bitince hemen kapanır.
- [x] T-R15.2 Acceptance 6 (L1 kısmı): `tests/integration/test_review_cancel_api.py`.
- [x] T-R15.3 Ön yüz: "Analizi durdur" önce durdurma isteği gönderir, "Durduruluyor…" ve sunucu onayını gösterir; Vitest ve e2e 02.
- [x] T-R15.4 Nesne incelemesi tek ekran: nesneler solda, kural seçimi ve başlat düğmesi sağ panelde; sayfa kaydırması yok.
