# DWH Code Review — API Sözleşmesi (v1)

Yerel, tek kullanıcılı uygulama. Kimlik doğrulama YOK. Backend: FastAPI, `http://127.0.0.1:8000`.
Tüm uç noktalar `/api` önekiyle. JSON alan adları `snake_case`. Tarihler ISO-8601 (UTC, `Z`).
Hata gövdesi her zaman: `{"detail": "<Türkçe mesaj>"}` (HTTP 400/404/409/422/502).

## Ortak tipler

```ts
type Severity = "critical" | "high" | "medium" | "low" | "info";
type RuleKind = "regex" | "llm";
// regex kuralı için: "match" = desen bulunursa bulgu (her eşleşme ayrı bulgu),
//                    "absent" = desen HİÇ bulunmazsa nesne başına tek bulgu
type MatchMode = "match" | "absent";
// regex desen hedefi: nesnenin SQL tanımı veya nesne adı
type RuleTarget = "definition" | "name";
type ObjectType = "PROCEDURE" | "VIEW" | "FUNCTION_SCALAR" | "FUNCTION_INLINE" | "FUNCTION_TABLE";

interface Rule {
  id: number;
  code: string;            // benzersiz, örn. "DWH001" (^[A-Z][A-Z0-9_-]{1,31}$)
  name: string;            // kısa başlık
  description: string;     // açıklama / neden önemli
  recommendation: string;  // nasıl düzeltilir
  severity: Severity;
  kind: RuleKind;
  // regex alanları (kind="regex" iken zorunlu: pattern)
  pattern: string | null;
  match_mode: MatchMode;           // default "match"
  target: RuleTarget;              // default "definition"
  ignore_case: boolean;            // default true
  ignore_comments: boolean;        // default true: -- ve /* */ yorumları + string literal'leri eşleşmeden hariç tut (satır numaraları korunur)
  // llm alanı (kind="llm" iken zorunlu)
  llm_prompt: string | null;       // LLM'e verilecek kural tanımı
  object_types: ObjectType[];      // boş = tüm tipler için geçerli
  enabled: boolean;
  group_ids: number[];
  created_at: string;
  updated_at: string;
}
type RuleInput = Omit<Rule, "id" | "created_at" | "updated_at">;

interface RuleGroup {
  id: number;
  name: string;            // benzersiz
  description: string;
  color: string;           // "#RRGGBB"
  rule_ids: number[];
  created_at: string;
  updated_at: string;
}
type RuleGroupInput = { name: string; description: string; color: string; rule_ids: number[] };

interface Connection {
  id: number;
  name: string;
  server: string;          // host veya host\instance
  port: number;            // default 1433
  username: string;
  has_password: boolean;   // parola asla geri dönmez
  encrypt: boolean;        // default true
  trust_server_certificate: boolean; // default true (yerel kullanım)
  created_at: string;
  updated_at: string;
}
// password: oluşturmada zorunlu; güncellemede boş/null => mevcut parola korunur
type ConnectionInput = { name; server; port; username; password?: string | null; encrypt; trust_server_certificate };

interface DbObject {
  database: string;
  schema: string;
  name: string;
  type: ObjectType;
  create_date: string;
  modify_date: string;
}

interface LlmSettings {
  enabled: boolean;
  base_url: string;        // OpenAI uyumlu, örn. "https://api.openai.com/v1" veya "http://localhost:11434/v1"
  model: string;
  has_api_key: boolean;
  temperature: number;     // default 0
  timeout_seconds: number; // default 120
}
type LlmSettingsInput = { enabled; base_url; model; api_key?: string | null /* boş => korunur */; temperature; timeout_seconds };

type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

interface AnalysisSummary {
  id: number;
  name: string;
  connection_id: number | null;
  connection_name: string;
  status: RunStatus;
  object_count: number;
  rule_count: number;
  total_checks: number;       // object_count * uygulanabilir kural sayısı
  completed_checks: number;
  finding_count: number;
  severity_counts: Record<Severity, number>;  // 5 anahtar da her zaman mevcut
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

interface AnalysisObject {
  id: number;
  database: string; schema: string; name: string; type: ObjectType;
  create_date: string | null; modify_date: string | null;
  status: "pending" | "running" | "done" | "error";
  error: string | null;
  finding_count: number;
  line_count: number;
}

interface AnalysisRuleRef { id: number | null; code: string; name: string; severity: Severity; kind: RuleKind }

interface Finding {
  id: number;
  object_id: number;           // AnalysisObject.id
  object_label: string;        // "db.schema.name"
  rule_code: string;
  rule_name: string;
  severity: Severity;
  kind: RuleKind;
  line: number | null;         // 1 tabanlı
  snippet: string;             // eşleşen satır / parça (<= 500 karakter)
  message: string;             // açıklama (regex: kural açıklaması; llm: modelin nedeni)
  recommendation: string;
}

interface AnalysisDetail extends AnalysisSummary {
  filters: Record<string, unknown>;   // oluştururken gönderilen filtre bilgisi (sadece gösterim)
  rules: AnalysisRuleRef[];
  objects: AnalysisObject[];
}
```

## v1.1 eklemeleri (kural motoru)

```ts
type RuleKind = "regex" | "llm" | "builtin";
// Yerleşik (kod içinde yazılmış, katalog metadatası kullanan) deterministik kontroller
type BuiltinCheck = "nolock_physical_tables" | "derived_view_consistency";
// Katalog tabanlı ön koşul: sağlanmazsa kural o nesne için çalıştırılmaz (LLM çağrısı yapılmaz)
type MetadataPrecondition = "references_scd_table" | "references_partitioned_table";

interface Rule {               // mevcut alanlara ek olarak:
  builtin_check: BuiltinCheck | null;   // kind="builtin" iken zorunlu
  precondition: string | null;          // regex; nesne tanımında (ignore_comments/ignore_case kuralına göre) eşleşmezse
                                        // kontrol "uygulandı, bulgu yok" sayılır, LLM çağrılmaz
  metadata_precondition: MetadataPrecondition | null;
  requires_metadata: boolean;           // LLM istemine KATALOG METADATASI bloğu eklenir
  databases: string[];                  // boş = tüm veritabanları; aksi halde yalnız bu DB'lerdeki nesnelere uygulanır (büyük/küçük harf duyarsız)
  name_pattern: string | null;          // regex, "schema.name" üzerinde (IGNORECASE, search); eşleşmeyen nesneye kural uygulanmaz
}
```

Uygulanabilirlik (total_checks'e sayılır mı): `object_types` VE `databases` VE `name_pattern` sağlanmalı.
Ön koşullar (`precondition`, `metadata_precondition`) uygulanabilirliği değiştirmez; sağlanmazsa kontrol bulgu üretmeden tamamlanır.
`POST /api/rules/test` gövdesine opsiyonel `database?: string` eklenir; builtin/metadata gerektiren kurallar test SQL'i üzerinde
katalog olmadan çalışır (metadata boş kabul edilir) ve yanıttaki `error` alanında "Bu kural katalog metadatası gerektirir; tam sonuç için analiz çalıştırın." notu döner.

## v1.4 eklemeleri (bulgu istisnaları, yeni yerleşik kontroller)

```ts
// Tam liste (v1.3 + v1.4). v1.4 ile eklenenler: "id_literal_filter", "calendar_date_predicate".
type BuiltinCheck =
  | "nolock_physical_tables" | "derived_view_consistency"
  | "left_then_inner_join" | "select_list_subquery" | "tablock_physical_insert"
  | "join_column_type_mismatch" | "non_sargable_predicates" | "or_in_predicates"
  | "scalar_udf_in_query" | "window_order_by_type" | "date_variable_type_mismatch"
  | "personnel_flag_view_source"
  | "id_literal_filter"          // DWH-ID-01: sabit değer filtresi vekil anahtar (Id) üzerinden (katalogdan tespit)
  | "calendar_date_predicate";   // DWH-CAL-01: WHERE/ON'da dönüştürülmüş tarih kolonu → Calendar aralık join'i önerisi

interface Rule {                 // mevcut alanlara ek olarak:
  exception_count: number;       // bu kurala tanımlı istisna sayısı (salt okunur; RuleInput'ta YOK)
}

// Bulgu istisnası: eşleşen bulgular analizde kaydedilmez, yalnızca sayılır.
interface RuleException {
  id: number;
  rule_id: number;
  rule_code: string;
  database: string | null;       // null/boş = her veritabanı
  schema: string | null;         // null/boş = her şema
  object_name: string | null;    // null/boş = her nesne (yalnız nesne adı, şemasız)
  snippet_pattern: string | null;// regex; bulgunun snippet + "\n" + message metninde IGNORECASE search
  reason: string;                // zorunlu, en fazla 500 karakter
  created_at: string;
}
type RuleExceptionInput = {
  database?: string | null; schema?: string | null; object_name?: string | null;
  snippet_pattern?: string | null; reason: string;
};

interface AnalysisSummary {      // (AnalysisDetail ve dashboard.recent_analyses dahil) mevcut alanlara ek olarak:
  suppressed_count: number;      // istisna nedeniyle kaydedilmeyen bulgu sayısı (finding_count'a dahil DEĞİL)
}
interface AnalysisObject {       // mevcut alanlara ek olarak:
  suppressed_count: number;      // bu nesnede istisnayla gizlenen bulgu sayısı (finding_count'a dahil DEĞİL)
}
```

Eşleşme kuralları: istisnada DOLU olan tüm alanlar eşleşmeli; database/schema/object_name büyük/küçük harf duyarsız tam eşitlik,
snippet_pattern regex araması. Boş string null kabul edilir. İstisnalar analiz başlarken bir kez okunur (sonradan eklenen istisna
çalışan analizi etkilemez). `POST /api/rules/test` istisnaları UYGULAMAZ. Kural silinince istisnaları da silinir; kural kopyalanınca
(`duplicate`) istisnalar kopyalanmaz. Eski analizlerde `suppressed_count` = 0.

Uç noktalar:
- `GET /api/rule-exceptions?rule_id=` → `RuleException[]` (rule_code, sonra id sırasıyla; rule_id verilmezse tümü)
- `POST /api/rules/{id}/exceptions` body `RuleExceptionInput` → `RuleException` (201)
  - kural yoksa 404 "Kural bulunamadı."
  - database/schema/object_name/snippet_pattern hepsi boşsa 422
    "İstisna en az bir nesne alanı veya ifade deseni içermeli; kuralı tamamen kapatmak için kuralı pasifleştirin."
  - reason boşsa 422 "İstisna nedeni zorunludur."; 500 karakterden uzunsa 422 "İstisna nedeni en fazla 500 karakter olabilir."
  - snippet_pattern derlenemezse 422 "Geçersiz düzenli ifade (snippet_pattern): <hata>"
- `DELETE /api/rule-exceptions/{id}` → 204 (yoksa 404 "İstisna bulunamadı.")

Rapor: HTML raporun başlık/kapsam bölümünde "İstisna nedeniyle gizlenen bulgu: N" satırı bulunur.

## v1.5 eklemeleri (büyük nesnelerde LLM parçalama)

```ts
interface LlmSettings {          // mevcut alanlara ek olarak:
  chunk_lines: number;           // tam sayı, 50–2000, default 250
}
type LlmSettingsInput = { /* mevcut alanlar */ chunk_lines?: number };   // verilmezse 250
```

- `GET /api/settings/llm` yanıtında, `PUT /api/settings/llm` ve `POST /api/settings/llm/test` / `.../models` gövdelerinde
  `chunk_lines` bulunur. Aralık dışı değer → 422 "Parça satır sayısı 50 ile 2000 arasında olmalıdır."
- Davranış: LLM kuralı incelenen nesne `chunk_lines` satırdan (veya ~20 000 karakterden) uzunsa SQL, ifade sınırlarında
  (`GO`, `;` ile biten satır veya boş satır) ~15 satır örtüşmeli parçalara bölünür; her parça ayrı LLM çağrısıdır,
  satır numaraları nesnenin orijinal numaralarıdır. Parçaların bulguları birleştirilir (aynı satır + aynı kod parçası tek bulgu).
  Geçici bağlantı hatalarında parça başına 2 kez yeniden denenir; yine başarısız olan parçanın hatası nesnenin `error`
  alanına yazılır, diğer parçaların bulguları korunur. Küçük nesnelerde davranış değişmez (tek çağrı).

### Kural örnekleri (canlı test paneli)

```ts
interface Rule {                       // mevcut alanlara ek olarak (RuleInput'ta da var, hepsi opsiyonel):
  sample_sql: string | null;           // canlı test panelinde varsayılan SQL ("-- HATA" / "-- DOĞRU" satırlı örnek)
  sample_object_name: string | null;   // "schema.name"
  sample_object_type: ObjectType | null;
  sample_database: string | null;
}
```

- Hazır 32 kuralın örneği seed/migration ile doldurulur (migration yalnız örneği boş kurallara yazar; kullanıcı örneği korunur).
- `PUT /api/rules/{id}` gövdesinde `sample_*` alanları HİÇ gönderilmezse kayıtlı değer korunur; `null`/boş string gönderilirse silinir.
  Geçersiz `sample_object_type` → 422.
- `POST /api/rules/{id}/duplicate` örneği de kopyalar.
- Örnek, analizlere/snapshot'lara girmez; yalnızca kural editöründe `POST /api/rules/test` için kullanılır.

## v1.6 eklemeleri (LLM kural asistanı, konu grupları)

Tipler ve uç noktalar RULE_ASSISTANT_SPEC.md'deki gibidir (`AssistantRequest`, `AssistantSession`, `AssistantCaseResult`,
`AssistantNoise`; `POST/GET /api/rule-assistant/sessions`, `GET .../{id}`, `POST .../{id}/revalidate|save|cancel`). Uygulama notları:
- `preferred_kind`: yalnız `"regex" | "llm" | null` anlamlıdır; `"builtin"` gönderilirse sessizce `null` sayılır.
- Doğrulama hataları (422): açıklama 10–4000 karakter; 1–10 pozitif, ≤10 negatif örnek; boş örnek SQL; gürültü testinde
  `sample_size` 10–200, en az bir veritabanı, var olan bağlantı. LLM kapalıysa 400 "Kural asistanı için LLM ayarlarının etkin olması gerekir."
- Doğrulama en fazla 3 tur (`validation.iterations` ≤ 3); katalog gerektiren yerleşik kontroller örneklerde katalogsuz çalışır
  (case `error` alanında not).
- `revalidate`: yalnız `ready`/`failed` oturumda (aksi 409); `save`: yalnız `ready` oturumda (aksi 409); kod çakışması 409.
  Kaydedilen kuralın örneği yoksa `sample_*` alanları ilk pozitif örnekten doldurulur.
- `cancel`: çalışan oturum → `cancelled`; zaten iptal edilmişse aynı yanıt; diğer durumlarda 409.
- `GET /api/rule-assistant/sessions` listesinde `log` son 5 satırla kısaltılır.
- Konu grupları: yeni kurulum/migration "Hızlı Tarama (LLM'siz)", "LLM Kuralları" ve 7 konu grubunu (yoksa) oluşturur.
  Asistan önerisinde ve kaydında regex/builtin kurallar otomatik "Hızlı Tarama (LLM'siz)", llm kuralları "LLM Kuralları" grubuna girer;
  `PUT /api/rules/{id}` ile tür llm ↔ regex/builtin değişirse bu iki grubun üyeliği backend'de düzeltilir.

## v1.7 eklemeleri (zamanlanmış analizler)

Tipler ve uç noktalar SCHEDULED_SPEC.md ile birebir aynıdır (`ScheduledAnalysis`, `ScheduledAnalysisInput`, `ScheduledRun`,
`RunDiffFinding`; `/api/scheduled-analyses` CRUD, `/preview`, `/{id}/run` (202), `/{id}/runs?limit=`, `/api/scheduled-runs/{run_id}/diff`).
`AnalysisSummary` (+ AnalysisDetail, dashboard.recent_analyses): `schedule_id`, `schedule_name`, `schedule_run_id` (zamanlanmış değilse null;
tanım silinince `schedule_id` null olur, `schedule_name` korunur). Dashboard: `upcoming_schedules` (etkin, en yakın 5).
Uygulama notları:
- Doğrulama: ad zorunlu/≤200/benzersiz (409); var olan bağlantı; ≥1 veritabanı; saat `HH:MM`; weekly ≥1 gün (1–7);
  monthly 1–31; interval 1–168; groups/rules modunda ≥1 seçim → 422 (Türkçe `detail`).
- `next_run_at` oluştururken ve zamanlama/etkinlik değişince yeniden hesaplanır; saatler sunucu bilgisayarının yerel saatidir.
- `POST /{id}/run` her zaman 202 ve `ScheduledRun` döner; `status` "running" (analiz başladı, `analysis_id` dolu), "skipped" veya "failed" olabilir.
- `preview`: `?schedule_id=` verilirse o tanımın watermark'ı ile `changed_count` hesaplanır (aksi halde null); katalog hatası → 502.
- `DELETE /api/connections/{id}`: bağlantı bir zamanlanmış analizde kullanılıyorsa 409.
- `diff.compared_objects`: önceki bir çalıştırmada karşılaştırma tabanı bulunan nesne sayısı.
- Analiz `filters`'ına `schedule`, `incremental`, `changed_since`, `databases`, `queries` yazılır (HTML raporun Filtreler bölümünde görünür).

## Uç noktalar

### Sağlık
- `GET /api/health` → `{"status":"ok","version":"1.0.0"}`

### Dashboard
- `GET /api/dashboard` →
  `{ rule_count, enabled_rule_count, group_count, connection_count, analysis_count,
     total_findings, severity_counts: Record<Severity,number>  // son 10 tamamlanmış analizin toplamı
     recent_analyses: AnalysisSummary[] /* son 6 */,
     top_rules: {code,name,severity,count}[] /* tüm analizlerde en çok bulgu üreten 5 */ }`

### Kurallar
- `GET /api/rules?q=&severity=&kind=&group_id=` → `Rule[]` (code'a göre sıralı)
- `POST /api/rules` body `RuleInput` → `Rule` (201). `group_ids` ile grup üyeliği atanır.
- `GET /api/rules/{id}` → `Rule`
- `PUT /api/rules/{id}` body `RuleInput` → `Rule`
- `DELETE /api/rules/{id}` → 204
- `POST /api/rules/{id}/duplicate` → `Rule` (code sonuna `_COPY` vb. eklenir)
- `POST /api/rules/test` body `{ rule: RuleInput, sql: string, object_name?: string, object_type?: ObjectType }`
  → `{ findings: {line, snippet, message}[], error: string | null }`  (regex ve llm için çalışır; geçersiz regex => error)

### Kural grupları
- `GET /api/rule-groups` → `RuleGroup[]`
- `POST /api/rule-groups` body `RuleGroupInput` → `RuleGroup` (201)
- `PUT /api/rule-groups/{id}` body `RuleGroupInput` → `RuleGroup`
- `DELETE /api/rule-groups/{id}` → 204 (kurallar silinmez)

### Bağlantılar (SQL Server)
- `GET /api/connections` → `Connection[]`
- `POST /api/connections` body `ConnectionInput` → `Connection` (201)
- `PUT /api/connections/{id}` → `Connection`
- `DELETE /api/connections/{id}` → 204
- `POST /api/connections/test` body `ConnectionInput & { id?: number }` (id verilip parola boşsa kayıtlı parola kullanılır)
  → `{ ok: boolean, message: string, server_version: string | null, database_count: number | null }` (her zaman 200)
- `GET /api/connections/{id}/databases` → `string[]` (sistem DB'leri hariç: master, tempdb, model, msdb)
- `GET /api/connections/{id}/schemas?databases=db1,db2` → `{database: string, schema: string, object_count: number}[]`
- `POST /api/connections/{id}/objects` body:
  ```ts
  { databases: string[];               // en az 1
    schemas?: string[];                // boş = tümü; "db.schema" veya "schema" biçimi (sadece "schema" => her DB'de o şema)
    types?: ObjectType[];              // boş = tümü
    created_from?: string | null; created_to?: string | null;    // "YYYY-MM-DD", dahil
    modified_from?: string | null; modified_to?: string | null;  // "YYYY-MM-DD", dahil
    search?: string | null }           // ad içinde (case-insensitive)
  ```
  → `{ items: DbObject[], total: number }`. TÜM filtreler AND ile birleşir. Sıralama: database, schema, name.

### LLM ayarları
- `GET /api/settings/llm` → `LlmSettings`
- `PUT /api/settings/llm` body `LlmSettingsInput` → `LlmSettings`
- `POST /api/settings/llm/test` body `LlmSettingsInput` (api_key boş => kayıtlı anahtar) → `{ ok: boolean, message: string, latency_ms: number | null }`

### Analizler
- `POST /api/analyses` body:
  ```ts
  { name?: string;                     // boşsa "Analiz #<id>"
    connection_id: number;
    objects: {database, schema, name, type}[];   // havuz, en az 1
    rule_ids?: number[]; group_ids?: number[];   // birleşimi (union) alınır, en az 1 kural; sadece enabled kurallar
    filters?: Record<string, unknown> }          // gösterim için saklanır
  ```
  → `AnalysisSummary` (201). Analiz arka planda çalışır: her nesnenin tanımı bir kez çekilir, ardından
  her kural sırayla işletilir (kuralın `object_types` filtresine uymayan nesne atlanır ve total_checks'e sayılmaz).
  Seçili kurallar arasında LLM kuralı varken LLM ayarları etkin/eksiksiz değilse analiz başlatılmaz, 400 döner:
  "Seçili kurallar arasında LLM kuralı var ancak LLM ayarları etkin değil."
  Tek bir kontrolün (nesne×kural) hatası analizi durdurmaz: nesneye `error` yazılır, diğer kontroller sürer.
  Nesne tanımı okunamazsa (şifreli vb.) nesne `error` olur, kuralları atlanır.
- `GET /api/analyses?status=` → `AnalysisSummary[]` (yeniden eskiye)
- `GET /api/analyses/{id}` → `AnalysisDetail` (çalışırken ilerleme için 1 sn'de bir poll edilir)
- `GET /api/analyses/{id}/findings?severity=&rule_code=&object_id=&q=` → `Finding[]` (severity önceliği, sonra nesne, satır)
- `GET /api/analyses/{id}/objects/{object_id}/source` → `{ definition: string | null, findings: Finding[] }` (analiz anında çekilen tanım saklanır)
- `POST /api/analyses/{id}/cancel` → `AnalysisSummary`
- `DELETE /api/analyses/{id}` → 204
- `GET /api/analyses/{id}/report.html` → kendi içinde bağımsız (inline CSS), yazdırılabilir HTML çalışma raporu
  (indirme: `Content-Disposition: attachment; filename="analiz-<id>.html"`). İçerik: başlık, tarih/süre, bağlantı,
  filtreler, kapsam (nesne/kural sayıları), önem dağılımı, kural bazlı özet tablo, nesne bazlı özet tablo, tüm bulgular.
- `GET /api/analyses/{id}/report.csv` → bulgular CSV (UTF-8 BOM, `;` ayraçlı)
