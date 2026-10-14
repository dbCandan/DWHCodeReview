# Plan — review-history-export

[PRD](PRD.md) belgesinden türetildi (`Status: Accepted`, Version 1.5.0). Proje kipi `separated-web`;
sabit yığın `python-fastapi` arka uç ve `React`/`Vite` ön yüzdür.

## Veri modeli ve ayarlar

Bu PRD'nin sütunları `review_rule_result` ve `review_finding` üzerindedir: `false_positive`,
`false_positive_changed_by`, `false_positive_changed_at` (Requirement 4). Koşum silindiğinde koşum
nesneleri, kural sonuçları, bulgular ve saklanan SQL metni `ON DELETE CASCADE` ile aynı işlemde
kalıcı silinir (Requirement 5); LLM çağrı özetinin koşum bağı `ON DELETE SET NULL` ile boşalır.
Saklama işi için `review_run.finished_at` üzerinde dizin vardır (Requirement 6). Saklama süresi ayarı
`DWHCODEREVIEW_REVIEW_HISTORY_RETENTION_DAYS` (1–365, varsayılan 90) tipli ayarlardadır. Göç:
`schema/alembic/versions/202609260001_directory_login_and_review_data_model.py`.

## Katmanlar ve dosyalar

| Katman | Dosyalar | Gereksinim |
|---|---|---|
| Hizmet | `app/backend/app/services/review_history_service.py` (liste, ayrıntı, işaret, silme, dışa aktarım, saklama işi) | Requirement 1–6, 10, 12 |
| Dışa aktarım biçimleri | `app/backend/app/services/review_export.py` (kaynaktaki `ExportMenu.tsx` taşıması) | Requirement 7–9 |
| Kalıcılık | `app/backend/app/infrastructure/repositories/review_repository.py` | Requirement 1–6, 12 |
| API | `app/backend/app/api/review_runs/router.py`, `app/backend/app/schemas/review_runs/contracts.py` | API sözleşmesi |
| Ön yüz | `app/frontend/src/pages/ReviewHistoryPage.tsx`, `app/frontend/src/components/review/ReviewResultsView.tsx`, `app/frontend/src/components/review/ExportButtons.tsx` | Requirement 1–5, 10, 11 |
| Yaşam döngüsü | `app/backend/app/main.py` (saklama işi) | Requirement 6 |

## Uygulama kararları

- Görme: inceleyici yalnız kendi koşumlarını, kural yöneticisi kiracıdaki bütün koşumları görür;
  görme yetkisi olmayan veya başka kiracıdaki koşum `404 review_run_not_found` alır. `scope=all`
  isteyen inceleyici `403 review_scope_forbidden` alır. İşaret ve silme yalnız sahibindir; görebilen
  ama sahibi olmayan `403 review_run_not_owner` alır (Requirement 2, 4, 5, Decision 1).
- Liste en yeniden eskiye, aynı zamanda kimliğe göre sıralıdır; sayfa boyutu varsayılan 50, en çok
  200. Satır tür, durum, başlangıç ve bitiş zamanı, başlık, alt başlık, hata kodu ve iletisi, kural
  sürümü, nesne sayısı, bulgu sayısı, sahibin görünen adı ve `owned` taşır. Başlık kaynaktaki
  biçimdir: nesne koşumunda "<veritabanı> · N nesne" (çok veritabanında "N veritabanı (a, b)"),
  hatalı koşumda "<veritabanı> · hata"; alt başlık ilk 3 nesne ve "+N" (hatada ilk 4); metin
  koşumunda başlık etikettir. Süren koşum da listede görünür (Requirement 1, 2). Başlık için
  yalnız koşumların veritabanı adları ve ilk dört nesnenin adı okunur (`headings_of_runs`); nesne
  satırlarının tamamı ve SQL metni okunmaz (Requirement 12).
- Ayrıntı yalnız tamamlanan koşumun sonuçlarını, işaretleriyle ve `public_id` kimlikleriyle
  döndürür; SQL metni içermez. Durdurulan, hatalı veya yarıda kesilen koşumun sonucu boştur
  (Requirement 3, Decision 4). Ayrıntı nesne sayfalıdır: `page` ve `page_size` (varsayılan 50, en
  çok 200) nesne konumu aralığını seçer; yanıt `results_page` ve `results_page_size` taşır, toplam
  `object_count` alanıdır. Sonuçlar koşum ve konum aralığı üzerinden birleştirmeyle okunur, kimlik
  listesiyle değil; SQL metni sütunu ayrıntıda hiç yüklenmez (Requirement 3, 12).
- Ön yüz ayrıntıda 50'şer nesnelik sayfalar arasında gezinir; sonuç süzgeci yalnız açık sayfaya
  uygulanır. `/gecmis?run=<id>` adresi o koşumu seçili açar; canlı pencere büyük koşumun sonuçlarını
  bu adresle açar.
- Dışa aktarımlar koşumu 200'er nesnelik parçalarla okur (`EXPORT_CHUNK_OBJECTS`) ve her parçayı
  okuduktan sonra oturumdan çıkarır; CSV satırları parça parça üretilir, SQL dosyası için yalnız
  `FAIL` sonuçları ve metin tutulur. Dosya yine tek yanıt olarak döner (Requirement 12).
- İşaret: bulgu her zaman; kural sonucu yalnız `FAIL` ve bulgusuzsa işaretlenir, değilse `409
  false_positive_not_applicable`. Aynı değer değişiklik yapmaz (değiştiren ve zaman korunur).
  Bilinmeyen bulgu `404 review_finding_not_found`, kural sonucu `404 review_rule_result_not_found`
  (Requirement 4).
- Silme koşum satırını kilitler; süren koşum `409 review_run_in_progress`. `DELETE
  /review-runs?scope=mine` sahibin bitmiş koşumlarını siler, süren koşuma ve başkasına dokunmaz
  (Requirement 5).
- Saklama işi arka uç sürecinde başlangıçta ve 6 saatte bir çalışır; `finished_at` saklama
  süresinden eski koşumları `pg_try_advisory_xact_lock` ile tek kopyada kalıcı siler ve
  `review_history.retention_run` olayını yazar (Requirement 6).
- CSV kaynaktaki `buildReviewResultsCsv` ile aynı baytlardır (UTF-8 BOM, CRLF, sütunlar, tırnak ve
  satır düzleştirme kuralı; `generated_at` JavaScript `toISOString` biçimi). Yeni: `=`, `+`, `-`,
  `@`, sekme veya satır başıyla başlayan her hücrenin önüne `'` eklenir. Sonucu olmayan koşumda
  hata iletisi varsa tek hata satırı yazılır. Dosya adı `sql-review-<ms>.csv`, tür
  `text/csv; charset=utf-8` (Requirement 7, 9).
- SQL dosyası kaynaktaki yorum bloğunu (başlık, not satırı, nesne başlığı, `- <kural> — <Satir …> —
  <açıklama>`, `|` yerine `¦`, madde yoksa "Tespit edilen duzeltme maddesi yok.") ve altında
  saklanan metni yazar: nesne koşumunda `-- [veritabanı] şema.ad (tür)` başlıkları ve aralarında
  `GO`, metin koşumunda metin olduğu gibi. Yorumdaki her satır numarası (tek, aralık veya virgüllü
  liste) dosyanın kendisinden hesaplanır: modelin numaraladığı satırın dosyadaki gerçek satırıdır;
  metnin başındaki boş satırların kırpılması da hesaba katılır. Kaynaktaki "SSMS ile hizalama"
  kaydırması ve aralığın ilk sayısını iki kez kaydıran hata yoktur. Yanlış pozitif işaretli bulgu
  ve kural sonucu yoruma yazılmaz. Dosya adı `sql-review-source-<ms>.sql`, tür
  `application/sql; charset=utf-8` (Requirement 8, 9, Decision 6).
- Kural grupları (Decision 9): CSV'nin son sütunu `rule_group`, kural sonucunun koşum anındaki grup
  adlarını sürüm içi grup sırasıyla `; ` ile birleştirir; SQL yorumunda kural kimliğinin yanında grup
  adları virgülle yazılır. Grupsuz kuralda sütun boş, yorumda ek yoktur.
- Saklanmış metni olmayan koşum (tamamlanmamış veya bütün nesneleri hatalı) SQL dışa aktarımında
  `409 sql_text_unavailable` alır (Requirement 10).
- Günlük olayları: `review_history.deleted` (koşum, sayı, kullanıcı), `review_history.exported`
  (koşum, biçim, satır veya nesne sayısı), `review_history.retention_run`; metin, açıklama ve kod
  parçası yazılmaz.

## Dağıtım bağımlılığı

`DWHCODEREVIEW_REVIEW_HISTORY_RETENTION_DAYS` değerinin chart değer dosyasına eklenmesi ve 90 günlük
disk hacmi doğrulaması
[Kubernetes teslim PRD'sinindir](../../../application-foundation/PRDs/002-kubernetes-delivery/PRD.md);
bu teslimde `helm/` değişmedi.

## Doğrulama komutları

- `scripts/quality-gate.sh all`
- `scripts/export-openapi.sh --check`, `scripts/generate-types.sh --check`

## İzlenebilirlik

| Gereksinim | Kabul | Görev |
|---|---|---|
| Requirement 1–6, 10 | Acceptance 1 | Task 1, Task V1 |
| Requirement 3, 12 | Acceptance 1, Acceptance 3 | Task 7 |
| Requirement 7–9 | Acceptance 2 | Task 2 |
| Requirement 3, 4, 5, 10, 11 | Acceptance 3 | Task 3 |
| Gözlemlenebilirlik (ölçüm) | — | Task 4 |
| Acceptance 4, Acceptance 5 | Acceptance 4, Acceptance 5 | Task 5, Task 6 |
