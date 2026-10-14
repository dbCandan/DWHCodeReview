# Görevler — review-history-export

[Plan](plan.md) belgesinden türetildi. Kanıt: `scripts/quality-gate.sh all` 2026-10-02'de yerel
Compose yığınında geçti (arka uç 726/726, ön yüz 144/144 test). Bu, L1 (otomatik testlerden geçti)
kanıtıdır.

- [x] Task V1 — Requirement 4, 5, 6 / Acceptance 1: yanlış pozitif sütunları, fiziksel silme
  basamaklaması, `finished_at` dizini ve saklama süresi ayarı. Kanıt:
  `app/backend/tests/integration/test_data_model.py`, `app/backend/tests/unit/test_config.py`.
- [x] Task 1 — Requirement 1–6, 10 / Acceptance 1: gerçek PostgreSQL ile liste, başlık ve sayılar,
  sayfalama ve `422`, kapsam ve rol başına `401`/`403`/`404`, kiracı yalıtımı, ayrıntıda SQL metni
  olmaması, işaret tekrarı, kural sonucu işaret kuralı, silme kapsamı ve LLM özetinin bağının
  boşalması, süren koşumda `409`, "tümünü sil" kapsamı, saklama işinin yalnız süresi dolanı silmesi
  ve kilitte tek kopya, saklanmış metni olmayan koşumda `409`; `OpenAPI` kayıtlı yapıtla aynı ve
  koşum özetinde ve ayrıntısında zorunlu `title` alanını taşır.
  Kanıt: `app/backend/tests/integration/test_review_history_api.py`,
  `app/backend/tests/unit/test_api_baseline.py` (`test_openapi_export_keeps_properties_named_title`),
  `app/backend/tests/unit/test_openapi_export.py`, `scripts/export-openapi.sh --check`.
- [x] Task 2 — Requirement 7–9 / Acceptance 2: CSV'nin kaynaktaki `buildReviewResultsCsv` çıktısıyla
  bayt bayt aynı olması (kaynak işlev Node ile aynı girdide çalıştırılıp beklenen baytlar
  sabitlendi), formül koruması, hata satırı; SQL yorum bloğundaki her satır numarasının dosyadaki
  gerçek satırı göstermesi (nesne ve metin koşumu, CRLF ve baştaki boş satırlar), yanlış pozitifin
  yorumdan çıkması. Kanıt: `app/backend/tests/unit/test_review_export.py`,
  `app/backend/tests/integration/test_review_history_api.py`.
- [x] Task 3 — Requirement 3, 4, 5, 10, 11 / Acceptance 3: geçmiş sayfası, onaylar, indirme
  düğmeleri, pasif SQL düğmesi ve Vitest testleri. Kanıt:
  `app/frontend/src/pages/ReviewHistoryPage.test.tsx` (liste, kapsam seçimi yalnız kural
  yöneticisinde, ayrıntı, yanlış pozitif işareti, CSV indirme, SQL metni yokken pasif SQL düğmesi,
  tek ve toplu silme onayı, süren koşumda 409 iletisi, `localStorage` kullanılmaması),
  `app/frontend/src/components/review/ReviewResultsView.test.tsx`,
  `app/frontend/src/services/reviews.test.ts` (oturum başlığıyla indirme, sunucunun dosya adı).
- [x] Task 4 — Gözlemlenebilirlik: `dwhcodereview_review_exports_total{format}`,
  `dwhcodereview_review_history_retention_deleted_runs_total` ve
  `dwhcodereview_review_history_retention_last_success_timestamp_seconds` ölçümleri ile günlük
  olayları. Kanıt: `app/backend/tests/integration/test_telemetry_signals.py`
  (`test_exports_and_retention_record_their_metrics`), `scripts/quality-gate.sh all`; saklama işinin iki ölçümü
  yerel gözlemlenebilirlik yığınında Prometheus'ta gözlendi.
- [x] Task 5 — Acceptance 4 ve Acceptance 5'in görme/yetki bölümü: `e2e/sql-review/02-script-review-history.mjs`
  2026-09-26'da Chromium'da geçti (metin koşumu yerel yedek LLM ucuyla,
  [script-review](../004-script-review/tasks.md) Task 4): canlı sonuçta işaretlenen bulgu ikinci
  tarayıcıda işaretli görünür; CSV UTF-8 BOM, CRLF ve sütun sırasıyla iner, işaretli bulgu
  `false_positive=true` taşır; SQL dosyasındaki "Satır N" indirilen dosyadaki `NOLOCK` satırını
  gösterir ve işaretli bulgu yorumdan çıkar; ikinci inceleyici koşumu ve SQL dışa aktarımını 404 ile
  göremez; kural yöneticisi "Tüm incelemeler"de salt okunur görür, SQL indirir, işaret değiştiremez
  (403) ve silemez (403); sahip onaylı silme yapar.
- [ ] Task 6 — Acceptance 4 ve 5'in kalan bölümü: CSV'nin Excel'de Türkçe karakterlerle açıldığının
  kişi tarafından görülmesi ve saklama süresi 1 güne ayarlanıp bitiş zamanı geçmişe çekilen koşumun
  saklama işiyle silinmesinin gözlenmesi; açık. 2026-09-27'de yerel yığında varsayılan 90 günle, bitişi
  91 gün öncesine çekilen koşum ve başlangıcı 91 gün öncesine çekilen LLM çağrı özeti arka uç
  açılışındaki saklama işiyle silindi; 1 günlük ayarla koşum ve Excel gözlemi yapılmadı.
- [x] Task 7 — Requirement 3, 12 / Acceptance 1, Acceptance 3: nesne sınırı olmayan koşumlarda geçmiş.
  Büyük koşumun ayrıntısı sayfa sayfa okunur; liste nesne satırlarını ve SQL metnini okumaz (çalışan
  SQL komutları yakalanarak doğrulandı); sürücü parametre sınırından büyük koşum (1.100 nesne × 30
  kural) okunur, CSV ve SQL olarak dışa aktarılır. Kanıt:
  `app/backend/tests/integration/test_review_history_api.py`. Ön yüz: ayrıntıda nesne sayfaları
  arasında gezinme ve bağlantıdaki koşumun seçili açılması. Kanıt:
  `app/frontend/src/pages/ReviewHistoryPage.test.tsx`. Bu, L1 (otomatik testlerden geçti) kanıtıdır.
- [x] Task 8 — Decision 8 / Acceptance 6: zamanlanmış koşum alıcısının erişimi (PRD sürüm 1.3.0).
  `GET /review-runs/{run_id}` ve iki dışa aktarım ucunda alıcı denetimi (koşumla saklanan alıcı
  listesi ile kullanıcının e-postasının büyük-küçük harf duyarsız eşleşmesi); işaretleme ve silmede
  alıcıya `404`. Alıcı listesi [zamanlanmış inceleme](../008-scheduled-review-email/tasks.md) göreviyle
  yazılır; bu görev ondan sonra yapılır. Kanıt: alıcı listesi zamanlayıcıyla yazıldığı için
  `app/backend/tests/integration/test_scheduled_review_scheduler.py::test_a_recipient_reads_the_report_but_cannot_change_it`
  (yerel PostgreSQL ile geçti).
- [x] Task 9 — Requirement 7, 8, Decision 9 / Acceptance 2: CSV'nin son `rule_group` sütunu ve SQL
  yorumunda kural yanında grup adı (PRD sürüm 1.4.0); sabit örnek dosyalar yeni biçimle güncellenir.
  [Kural grubu seçimi Task 5](../007-rule-group-selection/tasks.md) ile birlikte yapılır. Kanıt:
  `app/backend/tests/unit/test_review_export.py` (yerel `pytest` geçti).
- [x] Task 10 — Requirement 7, 8, Decision 9 / Acceptance 2: çoklu grup (PRD sürüm 1.5.0). Kuralın birden
  çok grubu CSV'nin `rule_group` sütununda `; ` ile, SQL yorumunda virgülle birleşir; grupsuz kuralda boş
  kalır. [Kural grubu seçimi Task 5](../007-rule-group-selection/tasks.md) ile birlikte yapılır. Kanıt:
  `app/backend/tests/unit/test_review_export.py` ek vakaları. Yerel `pytest` geçti (2026-10-14); `e2e/sql-review/02-script-review-history.mjs` CSV
  beklentisi `rule_group` sütunuyla güncellendi ve yerel önizlemede geçti.
