# Plan — rule-proposals

[PRD](PRD.md) belgesinden türetildi (`Status: Accepted`, Version 1.0.0). Proje kipi `separated-web`;
sabit yığın `python-fastapi` arka uç ve `sqlalchemy-alembic` kalıcılığıdır.

## Veri modeli

Şema yetkisi `app/backend/app/domain/models/rule_proposal.py` (yeni) ve
`app/backend/app/domain/models/rule_set.py`; değişiklik tek göçle gelir:
`schema/alembic/versions/202610140001_rule_proposals.py`. Her tablo zorunlu denetim ve yazılımsal silme
iskeletini ve etkin satır kısmi indeksini taşır (rules/41).

- `rule_proposal`: kiracı, `public_id`, `kind` (`rule`/`group`), `status`
  (`bekliyor`/`onaylandi`/`reddedildi`/`geri_cekildi`), öneren kullanıcı, `rationale` (en çok 500).
  Kural türünde `summary` (1–200), `text` (1–8.000), `priority` (`critical`/`normal`), `requires_metadata`,
  `rule_group_ids` (JSONB dizi); grup türünde `group_name` (1–80), `group_description` (en çok 500),
  `rule_codes` (JSONB dizi). Karar: `decided_by_user_id`, `decided_at`, `rejection_reason` (1–500),
  `published_version_number`, `new_rule_code`, `new_rule_group_id`. Türe göre zorunlu alanlar ve durum ile
  karar alanlarının tutarlılığı CHECK kısıtıdır.
- `rule_publish_request`: kiracı, `public_id`, isteyen kullanıcı, `draft_revision`, `status`
  (`bekliyor`/`onaylandi`/`reddedildi`/`gecersiz`), karar veren, karar zamanı, ret gerekçesi, yayımlanan
  sürüm numarası. Kiracı başına en çok bir `bekliyor` satırı kısmi tekil indeksle sağlanır.
- `rule_proposer`: kiracı ve kullanıcı doğal anahtarı, yetkiyi veren kullanıcı; geri alma yazılımsal
  silmedir (rules/41 bağ tablosu kuralı).
- `rule_set_draft_rule.summary`, `rule_set_version_rule.summary` (en çok 200, boş olabilir):
  [rule-management](../001-rule-management/plan.md) 1.1.0 sütunları.

## Katmanlar ve dosyalar

| Katman | Dosyalar | Gereksinim |
|---|---|---|
| Alan kuralları | `app/backend/app/domain/rule_proposal.py` (öneri doğrulaması, öneriyi yayımlanmış içeriğe ekleme: yeni `KuralNN`, grup üyeliği, 200 kural ve ad çakışması; yayın isteği farkı) | Requirement 2, 3, 5, 6 |
| Modeller | `app/backend/app/domain/models/rule_proposal.py`, `app/backend/app/domain/models/rule_set.py` | Veri modeli |
| Depo | `app/backend/app/infrastructure/repositories/rule_proposal_repository.py`, `app/backend/app/infrastructure/repositories/rule_set_repository.py` (kilitli taslak ve en son sürüm okuma, içerikten sürüm yazma) | Requirement 1–6 |
| Hizmet | `app/backend/app/services/rule_proposal_service.py`, `app/backend/app/services/rule_set_service.py` (ortak yayın yolu, `publish_requires_approval`) | Requirement 1–6 |
| API | `app/backend/app/api/rule_proposals/router.py`, `app/backend/app/api/rule_set/router.py` (yayın istekleri), `app/backend/app/schemas/rule_proposals/contracts.py`, `app/backend/app/api/router.py` | API sözleşmesi |
| Göç | `schema/alembic/versions/202610140001_rule_proposals.py` | Veri ve geçiş |
| Sözleşme | `specs/openapi/dwhcodereview-api.yaml`, üretilmiş `app/frontend/src/types/api.d.ts` | API sözleşmesi |
| Ön yüz | `app/frontend/src/services/ruleProposals.ts`, `app/frontend/src/pages/RuleProposalsPage.tsx` ("Kural önerilerim"), `app/frontend/src/pages/RuleApprovalsPage.tsx` ("Kural onayları"), `app/frontend/src/components/rules/RuleSetDiff.tsx`, `app/frontend/src/pages/RulesPage.tsx` ("Onaya gönder"), `app/frontend/src/components/layout/AppShell.tsx` (menü ve bekleyen sayı), `app/frontend/src/App.tsx` (rotalar) | Requirement 6, 7 |
| Tarayıcı senaryosu | (2.0.0 Decision 8 ile kaldırıldı) `e2e/sql-review/06-rule-proposals.mjs` | Acceptance 4 |

## Uygulama kararları

- **Ortak yayın yolu:** `RuleSetService` içinde tek bir "içerikten sürüm yayımla" işlevi vardır; süper
  yöneticinin doğrudan yayını, onaylanan yayın isteği ve onaylanan öneri bu işlevi kullanır. Parmak izi,
  sürüm numarası ve olay yazımı tek yerdedir.
- **Onay işlemi (Decision 2):** Tek işlemde kiracının taslak satırı `FOR UPDATE` ile kilitlenir (yayınların
  ortak kilidi), öneri satırı `FOR UPDATE` ile okunur ve `bekliyor` değilse `409 proposal_not_pending`
  döner. En son yayımlanmış sürüm okunur; öneri bu içeriğe eklenir; aynı değişiklik taslağa da yazılır.
  - Kural önerisi: yeni kimlik taslağın `next_rule_number` değeridir; kural, önceliğinin grubunun sonuna
    eklenir ve seçilen gruplara üye olur. Taslağa da aynı kimlikle aynı yere eklenir; `next_rule_number`
    ilerler ve taslak `revision` bir artar.
  - Grup önerisi: yeni grup taslakta yeni `public_id` ile oluşur, sürüme aynı kimlikle kopyalanır; seçilen
    kurallar sürümde ve taslakta (taslakta hâlâ varsa) gruba üye olur.
  - Çakışmalar `409 proposal_conflict` ile durur ve hiçbir şey yazılmaz: sürüm 200 kurala ulaşmış, grup
    adı (Türkçe katlanmış) artık var, 50 grup sınırı dolu, önerinin grubu veya kural kodu en son sürümde
    yok. Öneri `bekliyor` kalır.
  - Taslak `revision` arttığı için bekleyen yayın isteği bayatlar (PRD Riskler); onayında
    `publish_request_stale` alır.
- **Yayın isteği:** Oluştururken `base_revision` taslağın revizyonuyla aynı olmalıdır
  (`409 rule_set_draft_conflict`); boş taslak `422 rule_set_empty`. Önceki `bekliyor` istek aynı işlemde
  `gecersiz` olur. Onay kilit altında taslak revizyonunu karşılaştırır; farklıysa istek `gecersiz` olur
  ve `409 publish_request_stale` döner. Fark (eklenen, değişen, silinen kurallar ve gruplar) her okumada
  taslak ile en son sürümden hesaplanır; saklanmaz.
- **Doğrudan yayın:** `POST /rule-set/versions` süper yönetici dışındaki çağırana
  `403 publish_requires_approval` döner. Süper yöneticinin doğrudan yayını bekleyen yayın isteğini
  değiştirmez; istek taslak değişmediyse onaylanabilir ve aynı içerikli sürüme 200 döner.
- **Yetki:** Öneri uçları `rule_proposer` satırı (etkin) veya süper yönetici ister; aksi `403
  proposal_forbidden`. Süper yönetici de öneri oluşturabilir, ama karar aynı uçlardan verilir. Sahibi
  olmayan kullanıcının öneriye erişimi `404`. Karar uçları `require_super_admin`. Yetki yalnız etkin
  kullanıcıya verilir (`404 user_not_found`).
- **Sayfalama:** Öneri ve istek listeleri `page` (≥1), `page_size` (1–100, varsayılan 20); yeniden eskiye.
- **Yetenekler:** `GET /rule-proposals/capabilities` yalnız `{can_propose, can_decide}` döner ve menüyü
  belirler. Menüdeki bekleyen sayı, süper yöneticide `scope=pending` öneri listesinin ve
  `status=bekliyor` yayın isteği listesinin `total` alanlarının toplamıdır (Requirement 7).
- **Girdi sınırları (rules/57):** Bütün metin alanları Pydantic'te üst sınırla; `rule_group_ids` en çok 50,
  `rule_codes` en çok 200 öğe.
- Log olayları PRD Gözlemlenebilirlik'teki adlarla; yalnız `public_id`, tür, sayılar ve sürüm numarası
  yazılır.

## Göç ve dağıtım bağımlılığı

- `202610140001` genişleticidir: üç yeni tablo ve iki `summary` sütunu. Geri alma, öneri veya yayın isteği
  satırı ya da dolu özet varken açıklayıcı hatayla durur.
- Dağıtım sonrası kural yöneticileri doğrudan yayımlayamaz; süper yönetici yetki listesini doldurur. Yeni
  sır, ağ çıkışı veya chart değişikliği yoktur.

## Doğrulama komutları

- `scripts/db.sh apply`, `scripts/db.sh validate`, `scripts/db.sh status`
- `scripts/quality-gate.sh backend`, `scripts/quality-gate.sh frontend`, devir için `scripts/quality-gate.sh all`
- `scripts/export-openapi.sh --check`, `scripts/generate-types.sh --check`
- `scripts/e2e.sh` (Acceptance 4)

## İzlenebilirlik

| Gereksinim | Kabul | Görev |
|---|---|---|
| Requirement 1 | Acceptance 3, Acceptance 4 | Task 3, Task 4, Task 7, Task 8 |
| Requirement 2, 3 | Acceptance 1, Acceptance 3 | Task 1, Task 3, Task 6 |
| Requirement 4 | Acceptance 2 | Task 3, Task 6 |
| Requirement 5 | Acceptance 1, Acceptance 2 | Task 1, Task 4 |
| Requirement 6 | Acceptance 1, Acceptance 2, Acceptance 3 | Task 1, Task 5, Task 7 |
| Requirement 7 | Acceptance 4 | Task 6, Task 7, Task 8 |
| Veri ve geçiş | Acceptance 2 | Task 2 |
