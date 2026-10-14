# Plan — scheduled-review-email

[PRD](PRD.md) belgesinden türetildi (`Status: Accepted`, Version 1.0.0). Proje kipi `separated-web`;
sabit yığın `python-fastapi` arka uç ve `sqlalchemy-alembic` kalıcılığıdır. Ön koşul:
[rule-group-selection](../007-rule-group-selection/PRD.md) (koşumun grup seçimi) uygulanmış olmalıdır.

## Veri modeli

Şema yetkisi yeni `app/backend/app/domain/models/scheduled_review.py` ve genişletilen
`app/backend/app/domain/models/review.py`; tek göç: `schema/alembic/versions/202610050002_scheduled_reviews.py`.

- `scheduled_review`: kiracı, sahip kullanıcı, `public_id`, `name` (sahip başına tekil), nesne seçimi
  (`selection_mode` `filter`/`list`; süzgeç alanları veya seçim listesi JSON'u), kural grubu kimlikleri,
  periyot (`daily`/`weekly`/`monthly`, gün, saat, zaman dilimi), alıcılar, `status`
  (`active`/`paused`), `next_run_at`, `last_run_at`.
- `scheduled_review_run`: tanım, `review_run_id` (koşum başlayınca dolar), `due_at`, `trigger`
  (`scheduled`/`manual`/`missed`), tetikleyen kullanıcı, `state` (`queued`/`running`/`completed`/
  `failed`/`interrupted`/`missed`/`skipped`), atlama nedeni, e-posta durumu (`pending`/`sent`/`failed`/
  `not_configured`), `email_attempts`, `next_email_at`.
- `review_run_recipient`: `review_run_id`, küçük harfe çevrilmiş alıcı adresi (Requirement 6;
  review-history-export Decision 8 bunu okur).
- `scheduled_review_setting`: kiracı başına `max_concurrent_runs` (1–10, satır yoksa 2).
- `review_run`: `kind` değerlerine `scheduled` eklenir; nullable `scheduled_review_id`.

## Katmanlar ve dosyalar

| Katman | Dosyalar | Gereksinim |
|---|---|---|
| Alan kuralları | `app/backend/app/domain/scheduled_review.py` (periyot doğrulama, bir sonraki çalışma zamanının hesabı `zoneinfo` ile, alıcı alan adı doğrulama, e-posta özet gövdesinin kurulması, yeniden deneme takvimi 1/5/15 dk) | Requirement 1, 2, 5, Decision 5, 7 |
| Depo | `app/backend/app/infrastructure/repositories/scheduled_review_repository.py` (vadesi gelen tanımları `FOR UPDATE SKIP LOCKED` ile alma, kuyruk, ayar) | Requirement 3, 7, 8 |
| E-posta uyarlayıcısı | `app/backend/app/infrastructure/mail/smtp_client.py` (standart kütüphane `smtplib` + `ssl`, kurum CA, `asyncio.to_thread`) | Requirement 5 |
| Hizmet | `app/backend/app/services/scheduled_review_service.py` (tanım CRUD ve yetki), `app/backend/app/services/scheduled_review_scheduler.py` (döngü: kaçırılanları işaretleme, kuyruğa alma, eşzamanlı sınırla başlatma, e-posta ve yeniden deneme), `app/backend/app/services/review_run_service.py` (akışsız, sunucu içi koşum yolu) | Requirement 3–8 |
| Başlatma | `app/backend/app/main.py` (mevcut saklama işleri gibi `asyncio.create_task`; yalnız `DWHCODEREVIEW_SCHEDULER_ENABLED` açıksa) | Decision 2 |
| Ayarlar | `app/backend/app/core/config.py`: `scheduler_enabled`, `scheduler_tick_seconds`, `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `smtp_sender`, `smtp_ca_bundle`, `mail_allowed_domains` | Dağıtım etkisi |
| API | `app/backend/app/api/scheduled_reviews/router.py`, `app/backend/app/schemas/scheduled_reviews/contracts.py` | API sözleşmesi |
| Erişim (005) | `app/backend/app/services/review_history_service.py`, `app/backend/app/infrastructure/repositories/review_repository.py` (alıcı denetimi) | review-history-export Decision 8 |
| Göç | `schema/alembic/versions/202610050002_scheduled_reviews.py` | Veri ve geçiş |
| Dağıtım | `helm/dwhcodereview/deploy-hooks.sh` (`SMTP_USER`, `SMTP_PASSWORD` isteğe bağlı eşleme), `helm/dwhcodereview/values-project.yaml` (SMTP çıkış eşi, gizli olmayan ayarlar), `app/infra/docker-compose.local.yml` (yerel sahte SMTP) | Dağıtım etkisi |
| Sözleşme | `specs/openapi/dwhcodereview-api.yaml`, üretilmiş `app/frontend/src/types/api.d.ts` | API sözleşmesi |
| Ön yüz | yeni `app/frontend/src/pages/ScheduledReviewsPage.tsx`, `app/frontend/src/services/scheduledReviews.ts`, ayar alanı için mevcut ayar sayfası, `app/frontend/src/generated/routes.tsx` ve menü, `app/frontend/src/pages/ReviewHistoryPage.tsx` (listede olmayan koşumu `?run=` ile açma) | Requirement 9 |
| Tarayıcı senaryosu | `e2e/sql-review/05-scheduled-review.mjs` | Acceptance 4 |

## Uygulama kararları

- **Yeni bağımlılık yok:** Zamanlama standart `asyncio` döngüsü ve `zoneinfo`, e-posta standart
  `smtplib`/`ssl` ile yapılır. Böylece `dependency-admission.json` kabul süreci gerekmez.
- **Döngü:** Her `scheduler_tick_seconds` (varsayılan 60) adımda zamanlayıcı sırayla: (1) `next_run_at`
  değeri iki adımdan daha eski olan etkin tanımları `missed` kaydıyla işaretler ve bir sonraki periyoda
  ilerletir (Decision 9; uygulama kapalıyken geçen zaman bu yolla "kaçırıldı" görünür); (2) vadesi gelen
  tanımlar için `queued` kayıt açar ve `next_run_at`'i ilerletir; önceki koşumu süren tanım `skipped`
  ("önceki koşum sürüyor") alır; (3) süren zamanlanmış koşum sayısı kiracı sınırının altındaysa en eski
  `queued` kaydı başlatır; (4) zamanı gelen e-posta denemelerini yapar. Her adım satır kilidiyle
  (`FOR UPDATE SKIP LOCKED`) çalışır; birden çok arka uç kopyası aynı işi iki kez yapmaz.
- **Koşum:** Zamanlanmış koşum, nesne/metin koşumunun yürütme kodunu kullanır; olaylar tarayıcıya akmak
  yerine sunucu içinde tüketilir. LLM sınırları (llm-connection Requirement 7) aynı süreçte paylaşılır.
  Koşum başında alıcı listesi `review_run_recipient`'a, grup seçimi 007'nin tablosuna yazılır.
- **Açılış:** Uygulama açılırken `running` kalmış zamanlanmış kayıtlar `interrupted` olur (object-review
  Requirement 16 ile aynı "yarıda kesildi"). Kendiliğinden yeniden başlatılmaz.
- **Şimdi çalıştır:** `manual` tetiklemeli `queued` kayıt açar; sırası gelince aynı yoldan başlar. Tanımın
  `queued` veya `running` kaydı varsa `409 scheduled_review_running`.
- **E-posta:** Gövde düz metin + basit HTML; içerik alan katmanında kurulur ve testle "SQL, kod parçası
  yok" doğrulanır. Bağlantı `{public_origin}/gecmis?run=<public_id>`'dir. SMTP ayarı yoksa durum
  `not_configured`. Başarısız gönderim `next_email_at` ile 1, 5, 15 dakika sonra yeniden denenir; kalıcı
  olduğu için uygulama yeniden başlasa da sürer.
- **Rapor erişimi:** `GET /review-runs/{id}` ve dışa aktarım uçları; sahip veya kural yöneticisi değilse
  `review_run_recipient` tablosunda kullanıcının e-postasını (küçük harf) arar. Geçmiş sayfası `?run=`
  ile istenen koşum listede yoksa ayrıntıyı doğrudan ister.
- Log olayları PRD'deki adlarla; adres, ad, SQL ve bulgu içeriği yazılmaz. Yeni ölçüm yoktur
  (Decision 10).

## Göç ve dağıtım bağımlılığı

- `202610050002` genişleticidir; `202610050001` (007) sonrasında gelir. Geri alma, zamanlanmış kayıt
  varken veri kaybını bildirip durur.
- Zamanlayıcı varsayılan kapalıdır; nonprod'da `values-project.yaml` içinde `backend.config` altında
  `DWHCODEREVIEW_SCHEDULER_ENABLED=true` ile açılır. SMTP sunucusu backend çıkış eşi olarak eklenir;
  SMTP kullanıcı/parolası `deploy-hooks.sh` ile runtime `Secret`'ına isteğe bağlı eşlenir. Chart'a iş
  yükü eklenmez (rules/45).

## Doğrulama komutları

- `scripts/db.sh apply`, `scripts/db.sh validate`, `scripts/db.sh status`
- `scripts/quality-gate.sh backend`, `scripts/quality-gate.sh frontend`, devir için
  `scripts/quality-gate.sh all`
- `scripts/export-openapi.sh --check`, `scripts/generate-types.sh --check`, `scripts/render-charts.sh`
- `scripts/e2e.sh` (Acceptance 4)

## İzlenebilirlik

| Gereksinim | Kabul | Görev |
|---|---|---|
| Requirement 1, 2 | Acceptance 1, Acceptance 3 | Task 1, Task 4 |
| Requirement 3, 7, 8 | Acceptance 2 | Task 2, Task 5 |
| Requirement 4 | Acceptance 2 | Task 5 |
| Requirement 5 | Acceptance 1, Acceptance 2 | Task 1, Task 3, Task 6 |
| Requirement 6, Decision 12 | Acceptance 4 | Task 5, Task 7 |
| Requirement 9 | Acceptance 3, Acceptance 4 | Task 8, Task 9 |
| Dağıtım etkisi | Acceptance 4 | Task 10 |
