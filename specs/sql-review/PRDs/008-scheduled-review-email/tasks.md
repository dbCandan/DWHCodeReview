# Görevler — scheduled-review-email

[Plan](plan.md) belgesinden türetildi. Ön koşul: 007 (kural grubu seçimi) görevleri. Her görev önce
başarısız olan testle başlar; kanıt satırları görev bitince doldurulur.

## Kanıt (L1, kurumsal olmayan yerel ortam)

Docker'sız yerel ortamda (Python 3.14, PostgreSQL 17, `RUN_POSTGRES_INTEGRATION=1`) koşulanlar:

- Arka uç: `pytest -q` 790 geçti, 1 kaldı. Kalan `test_config.py::test_otel_process_variables_stop_start_up[otel_sdk_disabled]`
  bu değişiklikten bağımsızdır ve değişiklik öncesi tabanda da kalıyordu. `test_llm_adapter.py` Windows'ta TLS
  vakalarında takıldığı için bu ortamda dışarıda bırakıldı.
- Yeni testler: `test_scheduled_review_rules.py` 38, `test_smtp_client.py` 6, `test_scheduled_review_api.py` 16,
  `test_scheduled_review_scheduler.py` 12, `test_scheduled_reviews_migration.py` ve `test_data_model.py` ek vakaları.
- `ruff check app tests`, `black --check app tests`, `isort --check-only app tests`, `mypy app` temiz.
- Göç: yerel PostgreSQL'de `alembic upgrade head`, `downgrade 202610050001`, yeniden `upgrade` ve `alembic check`
  geçti.
- API sözleşmesi: `python -m app.scripts.export_openapi` çıktısı kayıtlı yapıtla aynı; `openapi-typescript`
  çıktısı `app/frontend/src/types/api.d.ts` ile aynı.
- Ön yüz: `npm run typecheck`, `npm run lint`, `npm run build` temiz; `vitest` 169/169 geçti.
- `e2e/sql-review/05-scheduled-review.mjs` yazıldı ve `node --check` geçti; çalıştırılmadı (L2 kanıtı değildir).
- Saat dilimi hesabı standart `zoneinfo` ile yapılır. Bu Windows ortamında sistem saat dilimi verisi
  olmadığından `tzdata` yalnız depo dışındaki yerel test ortamına kuruldu; proje bağımlılığı eklenmedi.

Kurumsal ortamda kalanlar: arka uç imajında `python -c "import zoneinfo; zoneinfo.ZoneInfo('Europe/Istanbul')"`
denetimi; `scripts/db.sh validate`, `scripts/export-openapi.sh --check`, `scripts/generate-types.sh --check`
ve `scripts/render-charts.sh` betiklerinin kendisi; `test_llm_adapter.py`; Task 11 senaryosunun koşulması;
Task 12 kalite kapısı. Task 10'daki yerel Compose sahte SMTP'si yeni bir konteyner imajı gerektirdiği için
eklenmedi; imaj kabulü kurum sürecine bağlıdır. `values-project.yaml` içindeki izinli alan adı
(`kuveytturk.com.tr`) ile SMTP sunucusu adresi, portu, göndereni ve çıkış eşi işletim ekibince doğrulanmalı
ve doldurulmalıdır.

- [x] Task 1 — Requirement 1, 2, 5, Decision 5, 7 / Acceptance 1: alan kuralları. Periyot doğrulama
  (serbest cron yok), zaman dilimiyle bir sonraki çalışma zamanı (yaz saati geçişi dahil), alıcı alan adı
  ve biçim doğrulama, e-posta özet gövdesinde SQL/kod parçası bulunmaması, 1/5/15 dk yeniden deneme
  takvimi. Kanıt: `app/backend/tests/unit/test_scheduled_review_rules.py`.
- [ ] Task 2 — Veri modeli / Acceptance 2: modeller ve göç `202610050002_scheduled_reviews.py`; geri
  alma ve yeniden uygulama; dolu kayıtta geri almanın durması. Kanıt:
  `app/backend/tests/integration/test_data_model.py` ek vakaları, `scripts/db.sh validate`.
- [x] Task 3 — Requirement 5 / Acceptance 1: SMTP uyarlayıcısı (TLS ve kurum CA, zaman aşımı, hata
  sınıfları), sahte SMTP sunucusuna gerçek gönderim testi. Kanıt:
  `app/backend/tests/integration/test_smtp_client.py`.
- [x] Task 4 — Requirement 1, 2, Decision 3, 6, 8 / Acceptance 3: tanım ve ayar uçları; sahip/süper
  yönetici yetkisi (`404`), `schedule_invalid`, `recipient_domain_not_allowed`,
  `schedule_name_duplicate`, duraklat/etkinleştir, ayar ucunun yalnız süper yöneticiye açık olması ve
  `setting_out_of_range`. Kanıt: `app/backend/tests/integration/test_scheduled_review_api.py`.
- [x] Task 5 — Requirement 3, 4, 6, 7, 8, Decision 2, 9 / Acceptance 2: zamanlayıcı döngüsü. Vadesi gelen
  tanımın kuyruğa alınıp başlatılması; üst üste binmenin `skipped`; yayımlanmış kural yokken atlama;
  eski vadenin `missed`; eşzamanlı sınırın aşılmaması ve ayar değişince uygulanması; iki eşzamanlı
  zamanlayıcı örneğinde tek yürütme; açılışta `interrupted`; "Şimdi çalıştır" ve koşum sürerken `409`;
  koşuma grup seçimi ve alıcı listesinin yazılması. LLM test ikamesi ve gerçek PostgreSQL. Kanıt:
  `app/backend/tests/integration/test_scheduled_review_scheduler.py`.
- [x] Task 6 — Requirement 5, Decision 1, 7 / Acceptance 2: bitişte e-posta; sahte SMTP'de içerik
  denetimi, gönderim hatasında 3 yeniden deneme ve `failed`, SMTP yokken `not_configured`, yeniden
  başlatmadan sonra bekleyen denemenin sürmesi. Kanıt: aynı test dosyası ek vakaları.
- [x] Task 7 — Decision 12 / review-history-export Acceptance 6: alıcının rapor ve dışa aktarım erişimi,
  işaretleme/silmede `404`. Bu görev [005 Task 8](../005-review-history-export/tasks.md) ile birlikte
  yapılır. Kanıt: alıcılık zamanlayıcının ürettiği gerçek koşum üzerinde sınandığı için
  `app/backend/tests/integration/test_scheduled_review_scheduler.py::test_a_recipient_reads_the_report_but_cannot_change_it`.
- [ ] Task 8 — API sözleşmesi / Acceptance 3: OpenAPI ve üretilmiş tipler. Kanıt:
  `scripts/export-openapi.sh --check`, `scripts/generate-types.sh --check`.
- [x] Task 9 — Requirement 9 / Acceptance 3: "Zamanlanmış incelemeler" sayfası (form, süzgeç/liste
  seçimi, grup seçimi, periyot, alıcılar, liste, geçmiş, "kaçırıldı" ve "e-posta gönderilemedi"
  uyarıları), süper yöneticiye "Şimdi çalıştır" ve ayar alanı, geçmiş sayfasının listede olmayan koşumu
  `?run=` ile açması. Kanıt: `app/frontend/src/pages/ScheduledReviewsPage.test.tsx`,
  `ReviewHistoryPage.test.tsx` ek vakaları.
- [ ] Task 10 — Dağıtım etkisi / Acceptance 4: `deploy-hooks.sh` SMTP eşlemesi, yerel Compose'a sahte
  SMTP, `values-project.yaml` örnek çıkış eşi; `scripts/render-charts.sh` geçer, chart'a iş yükü
  eklenmez. Kanıt: `scripts/render-charts.sh` çıktısı.
- [ ] Task 11 — Requirement 1–6, 9 / Acceptance 4: L2. `e2e/sql-review/05-scheduled-review.mjs`: kısa
  periyotlu tanım arka planda çalışır, rapor saklanır, sahte SMTP'ye kod parçası içermeyen özet ulaşır,
  alıcı kullanıcı bağlantıyla raporu açar, alıcı olmayan açamaz. Yerel PostgreSQL, test SQL Server ve
  onaylı LLM ucu gerekir.
- [ ] Task 12 — Kalite kapısı: `scripts/quality-gate.sh all` geçer; sonuç bu dosyanın başına kanıt
  olarak yazılır.

## Ortam notu

Kalite kapıları, yönetilen inceleme ve proje kancaları yalnız kurumsal ortamda, proje kökünde açılan
oturumda çalışır. Bu görevlerin L1/L2 kanıtı oradan alınmalıdır.
