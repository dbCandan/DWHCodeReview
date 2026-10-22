# PRD — llm-connection

Status: Accepted

Version: 1.1.2

Acceptance date: 2026-09-27

Domain: [sql-review](../../DOMAIN.md)

Kabul kaydı: Proje sahibi bu PRD'yi 2026-09-27'de, açık sorulardaki önerileri ve sahip kararlarını
benimseyerek kabul etti.

**1.x revizyon notu (2026-10-15):** [directory-login](../../../application-foundation/PRDs/001-directory-login/PRD.md) 1.3.0 Decision 14 ile `kural-yoneticisi` rolü kaldırıldı; kullanıcılar `inceleyici` (arayüzde "Kullanıcı") ve süper yöneticidir. Bu belgede kural yöneticisine verilen yetkiler (taslağı düzenleme ve yayımlama, bağlantı ayarları, LLM çağrı özetleri, tüm incelemeleri görme) süper yöneticidedir; "inceleyici" geçen yerler her kullanıcıyı anlatır.

## Amaç

İnceleme isteklerinin yalnız onaylı kurum içi LLM (büyük dil modeli) sunucusuna, kurum ağı politikası, kurum CA'sıyla doğrulanan TLS (şifreli bağlantı), süre sınırı, sınırlı yeniden deneme, **İnceleme koşumu** başına ve süreç geneli eşzamanlılık sınırıyla gitmesi. Her çağrı için yalnız **LLM çağrı özeti** PostgreSQL'de saklanır; ham SQL metni ve ham LLM yanıtı hiçbir loga ve kayda yazılmaz. LLM bağlantı ayarı **Ortam** `local` iken arayüzden düzenlenebilir, `nonprod` iken yalnız dağıtımdan gelir.

## Aktörler ve sonuçlar

- `inceleyici`: İnceleme sırasında her kural için LLM çağrısının canlı ilerlemesini (üretilen belirteç ve karakter sayısı) görür; çağrı başarısızsa kural sonucu "değerlendirilemedi" olur ve kısa, iç ayrıntı içermeyen bir neden görünür.
- `kural-yoneticisi`: LLM çağrı özetlerini listeler ve tek özeti açar; `local` Ortamda LLM bağlantısı sayfasında biçim, adres, model ve anahtarı düzenler.
- **İşletim ekibi** (uygulama rolü değildir): `nonprod` LLM ucunu, modeli, süre ve eşzamanlılık ayarlarını dağıtım girdisiyle verir; her denemenin sonucunu içerik görmeden logdan ve ölçümlerden izler.
- [Nesne incelemesi](../003-object-review/PRD.md) ve [metin incelemesi](../004-script-review/PRD.md) PRD'leri: istem metnini kurar ve yanıtı yorumlar; LLM'e yalnız bu PRD'nin tanımladığı port üzerinden ulaşır.

## Değişmezler ve sınırlar

- LLM isteği yalnız kurum içi (özel ağ) adrese gider; kurum ağı politikası kapatılamaz, ayarla veya API ile istisna tanınamaz.
- TLS sertifika doğrulaması hiçbir ortamda kapatılamaz; ortam vekil sunucusu (proxy) kullanılmaz; yönlendirme (redirect) izlenmez.
- Ham SQL metni, istem, Nesne meta verisi, ham LLM yanıtı ve LLM sunucusunun hata gövdesi loga, PostgreSQL'e ve diske yazılmaz.
- LLM anahtarı yalnız sunucu sınırındadır; yanıtta yalnız `api_key_set` bilgisi döner.
- `nonprod` Ortamda LLM ayarı çalışma sırasında değiştirilemez. Ortam `DWHCODEREVIEW_ENVIRONMENT` ayarından okunur (`development` → `local`, `staging` → `nonprod`); başka ya da okunamayan değer `nonprod` sayılır ([application-foundation alanı](../../../application-foundation/DOMAIN.md), [SQL Server bağlantısı PRD'si](../002-sql-server-connection/PRD.md) Decision 10).
- İstem içeriği, kural yorumlama ve iki parçalı analiz eşiği bu PRD'nin kapsamında değildir.

Decision 1: LLM erişimi bir uygulama portu (`LlmChatPort`; iş katmanının çağırdığı arayüz) ile altyapı uyarlayıcısı arasında ayrılır (`technology-profile.yml` `llm_orchestration.generation_boundary`). Port girdi olarak sistem istemi, kullanıcı içeriği, İnceleme koşumu, kural ve parça kimliğini; çıktı olarak yanıt metnini veya sabit hata sınıfını ve kullanım özetini verir.

Decision 2: İki istek biçimi korunur: `openai` (`…/chat/completions`, `messages[]`, akışlı yanıt) ve `api_v1_chat` (`…/api/v1/chat`, `system_prompt` + `input`, akışsız; yerel LM Studio için). Kaynaktaki eş adlar `gpt_oss` ve `v1_chat` kaldırılır.

Decision 3: `nonprod` LLM ucu, KT Verim'in kullandığı kurum içi RunAI ucudur: `openai` biçimi, `https://runai.gpudtx.kuveytturk.com.tr/inference/qwen36-35b-a3b-fp8/v1`, model `/data/models--Qwen--Qwen36-35B-A3B-FP8`, anahtar gerekmez (kaynak commit `bb8e65d`).

Decision 4: `local` Ortamda arayüzden yapılan değişiklik yalnız çalışan süreçte tutulur; `app/backend/.env` dahil hiçbir dosyaya ve süreç ortamına yazılmaz.

## Mevcut davranış

Kaynak uygulama `~/codes/dwhcodereview` bugün şöyle çalışır; hedefteki değişiklik her maddede belirtilmiştir.

- **Ayarlar** (`backend/config.py`): `LLM_CHAT_API` (varsayılan `api_v1_chat`), `LLM_BASE_URL`, `LLM_CHAT_URL`, `LLM_MODEL` ve ona üstün gelen `SQL_REVIEW_LLM_MODEL`, `LLM_API_KEY`, `LLM_HTTP_TRUST_ENV`, `LLM_HTTP_USER_AGENT`, `LLM_ENFORCE_PRIVATE_NETWORK`, `LLM_ALLOW_PUBLIC_HOSTS`, `LLM_LOG_FULL_PAYLOADS`, `SQL_REVIEW_MAX_CONCURRENT_RULES` (6, 1–512), `LLM_READ_TIMEOUT_SECONDS` (900, en az 60), `LLM_REQUEST_RETRIES` (2). **Hedefte:** `DWHCODEREVIEW_` önekiyle tek model ayarı; ağ politikası, vekil, tam gövde kaydı ve açık internet istisnası ayarları kaldırılır (Requirement 1).
- **Ayar yazma:** `PUT /api/llm-config` `services/llm_env.py` `merge_llm_into_dotenv` ile değerleri, LLM anahtarı dahil, çalışma sırasında `backend/.env` dosyasına ve süreç ortamına yazar. API, arayüzde olmayan `llm_enforce_private_network`, `llm_allow_public_hosts` ve `llm_log_full_payloads` alanlarını da kabul eder; yani yönetim anahtarına sahip biri ağ politikasını API'den kapatabilir. **Hedefte:** dosyaya yazma kalkar; `nonprod`'da uç yok; politika alanları yok (Decision 4, Requirement 13).
- **Adres çözümü** (`services/llm_review.py` `_llm_chat_url*`): `openai` biçiminde `LLM_CHAT_URL` doluysa o (`/v1` ile bitiyorsa `/chat/completions` eklenir), değilse `LLM_BASE_URL` + `/chat/completions`; `api_v1_chat` biçiminde `LLM_CHAT_URL` doluysa o, değilse `LLM_BASE_URL` sonundaki `/v1` atılıp `/api/v1/chat`. **Hedefte:** aynı kural, tek adres birleştirme yardımcısıyla (Requirement 2).
- **Gönderim:** `openai` biçimi her zaman `stream: true` ile gönderir ve SSE (sunucunun parça parça gönderdiği olay akışı) satırlarından `delta.content` veya `message.content` toplar; akış yoksa düz JSON gövdeyi okur. `api_v1_chat` akışsızdır. Kullanıcıya en sık 0,2 saniyede bir `llm_stream` ilerleme olayı gider. 200 kodlu ama `{"error": …}` taşıyan gövde hata sayılır. Yanıt boyutu sınırsızdır. **Hedefte:** aynı davranış; yanıt 4 MiB ile sınırlanır (Requirement 3, 5).
- **Ağ politikası** (`_enforce_llm_network_policy`): her çağrıdan önce ana makine adı çözülür; adreslerin hepsi özel ağ (RFC1918, loopback, link-local, IPv6 ULA) veya `100.64.0.0/10` aralığında değilse ya da ad izin listesinde değilse istek reddedilir. Denetim ile bağlantı ayrı DNS sorgularıdır; arada adres değişebilir. **Hedefte:** her zaman açık; bağlanılan adres de denetlenir (Requirement 4).
- **TLS:** `_llm_ssl_context` doğrulama için `SSL_CERT_FILE` ortam değişkenini doğrudan okur, yoksa `certifi` kullanır; imaja `backend/certs/corporate-inference-root.crt` kurum kök CA'sı eklenir. `LLM_HTTP_TRUST_ENV=true` ise ortam vekili kullanılır. **Hedefte:** tipli ayardan okunan güven deposu; vekil yok (Requirement 5).
- **Süre ve yeniden deneme** (`_llm_chat_completion`): okuma süresi 900 sn, bağlantı süresi `min(120, okuma)`; yalnız bağlantı veya okuma zaman aşımında en fazla 2 ek deneme, bekleme `1,5 × 2^n` sn (en çok 12 sn). Bağlantı reddi ve HTTP hataları yeniden denenmez. **Hedefte:** korunur (Requirement 6).
- **Eşzamanlılık:** `review_sql` her Nesne için ayrı `asyncio.Semaphore(6)` ve ayrı HTTP istemcisi (5.000 bağlantı sınırıyla) açar; `services/review_orchestrator.py` `run_reviews` bütün Nesneleri aynı anda başlatır. Böylece 10 Nesnelik koşum aynı uca 60 eşzamanlı çağrı gönderebilir. **Hedefte:** sınır bütün İnceleme koşumu içindir; ayrıca süreç geneli sınır vardır (Requirement 7).
- **Kimlik başlığı:** Her istek `User-Agent: DWHCodeReview-Backend/1.0 (internal SQL review; httpx)` taşır; anahtar varsa `Authorization: Bearer`. **Hedefte:** korunur (Requirement 8).
- **Hata iletisi:** `_llm_connect_error_hint` ve `_brief_llm_error_for_ui` kullanıcıya hedef adresi, `backend/.env` ve LM Studio ipuçlarını; HTTP hatalarında sunucunun hata gövdesinden 8.000 karaktere kadar metni gösterir. **Hedefte:** sabit hata sınıfı (Requirement 9).
- **Çağrı günlüğü** (`services/llm_log.py`): her çağrı `data/llm_logs/requests.jsonl` dosyasına (Kubernetes'te kalıcı diskte) yazılır. `LLM_LOG_FULL_PAYLOADS=false` iken yalnız `request`, `response_body`, `response_text` alanları atılır; **ham yanıt parçası (`response_text_fragment`) ve sunucu hata gövdesi (`error`) 8.000 karaktere kadar yine yazılır**. Kayıtta model, süre ve belirteç sayısı yoktur. `GET /api/llm-logs` son 100 (en çok 500) özeti, `GET /api/llm-logs/{id}` tam kaydı döndürür, `DELETE /api/llm-logs` dosyayı siler. Ayrıca `logger.warning` sunucunun hata metninin 500 karakterini, `logger.exception` istisna metnini uygulama loguna yazar. **Hedefte:** dosya ve tam kayıt kalkar; yalnız PostgreSQL'de 90 gün saklanan LLM çağrı özeti (Requirement 10–12, 14).
- **Arayüz** (`frontend/src/pages/LlmConfigPage.tsx`): biçim, temel adres, sohbet adresi, iki model alanı, anahtar ve vekil kutusu; metin değerlerin `backend/.env` dosyasına yazıldığını söyler. Kaynakta çağrı günlüğünü gösteren sayfa yoktur; yalnız `frontend/src/services/api.ts` istemci işlevleri vardır. **Hedefte:** Requirement 13.

## İşlevsel gereksinimler

Requirement 1: Tipli ayarlar: `DWHCODEREVIEW_LLM_CHAT_API` (`openai` veya `api_v1_chat`), `DWHCODEREVIEW_LLM_BASE_URL`, `DWHCODEREVIEW_LLM_CHAT_URL` (isteğe bağlı), `DWHCODEREVIEW_LLM_MODEL`, `DWHCODEREVIEW_LLM_API_KEY` (isteğe bağlı, sır), `DWHCODEREVIEW_LLM_CA_BUNDLE` (varsayılan imajın sistem güven deposu), `DWHCODEREVIEW_LLM_READ_TIMEOUT_SECONDS` (900; 60–3600), `DWHCODEREVIEW_LLM_REQUEST_RETRIES` (2; 0–5), `DWHCODEREVIEW_LLM_MAX_CONCURRENT_CALLS` (koşum başına; 6; 1–32), `DWHCODEREVIEW_LLM_PROCESS_MAX_CONCURRENT_CALLS` (süreç geneli; 12; 1–128) ve `DWHCODEREVIEW_LLM_USER_AGENT`. Yalnız ilk beşi `local`'de arayüzden değiştirilebilir; diğerleri yalnız dağıtım girdisidir. `nonprod`'da temel adres `https` değilse veya model boşsa süreç başlangıçta hata verip durur. Kaynaktaki `SQL_REVIEW_LLM_MODEL`, `LLM_HTTP_TRUST_ENV`, `LLM_ENFORCE_PRIVATE_NETWORK`, `LLM_ALLOW_PUBLIC_HOSTS` ve `LLM_LOG_FULL_PAYLOADS` karşılığı yoktur.

Requirement 2: Sohbet adresi Mevcut davranış bölümündeki kurala göre tek güvenli adres birleştirme yardımcısıyla üretilir. Kullanıcı adı/parola içeren (`kullanıcı:parola@`), parça (`#`) taşıyan veya `http`/`https` dışındaki adres 422 ile reddedilir; `http` yalnız `local` Ortamda kabul edilir.

Requirement 3: `openai` biçimi `model`, iki öğeli `messages` (sistem ve kullanıcı), `stream: true` ve `stream_options: {"include_usage": true}` gönderir; SSE parçalarından metni ve akışın son parçasındaki `usage.completion_tokens` ile `usage.prompt_tokens` değerlerini toplar, akış gelmezse düz JSON gövdeyi okur. `api_v1_chat` biçimi `model`, `system_prompt`, `input` gönderir. İki biçimde de ilerleme olayı `llm_stream` yalnız kural kimliği, belirteç ve karakter sayısını taşır, bir çağrı için saniyede en fazla 5 kez gönderilir. 200 kodlu `{"error": …}` gövdesi ve boş metin başarısız sayılır.

Requirement 4: Her çağrıdan önce adın çözüldüğü bütün adresler ve bağlantının gerçekten kurulduğu karşı adres özel ağ aralığında olmalıdır (RFC1918, loopback, link-local, IPv6 ULA, `100.64.0.0/10`). Aksi durumda istek gövdesi gönderilmeden çağrı `network_policy_denied` sonucuyla biter. `local`'de ayar kaydı da aynı denetimi yapar ve uymayan adresi 422 ile reddeder.

Requirement 5: TLS doğrulaması `DWHCODEREVIEW_LLM_CA_BUNDLE` güven deposuyla yapılır; imajın sistem deposuna kurum kök CA'sı `corporate-inference-root.crt` eklenir. Ortam vekili kullanılmaz, yönlendirme izlenmez, yanıt gövdesi (akışta biriken metin dahil) 4 MiB'ı aşarsa çağrı `response_too_large` ile kesilir.

Requirement 6: Okuma süresi ayardan, bağlantı süresi `min(120, okuma süresi)` saniyedir. Yalnız bağlantı veya okuma zaman aşımında `DWHCODEREVIEW_LLM_REQUEST_RETRIES` kadar ek deneme yapılır; bekleme `1,5 × 2^n` saniye, en çok 12 saniyedir. HTTP hata kodu, geçersiz yanıt, ağ politikası reddi ve iptal yeniden denenmez. İnceleme koşumu iptal edilir veya istemci bağlantıyı koparırsa süren çağrılar kapatılır ve `cancelled` olarak kaydedilir.

Requirement 7: Bir İnceleme koşumu içindeki eşzamanlı LLM çağrısı sayısı, koşumdaki Nesne sayısından ve iki parçalı analizden bağımsız olarak `DWHCODEREVIEW_LLM_MAX_CONCURRENT_CALLS` değerini aşmaz. Aynı süreçte aynı anda süren bütün koşumların toplam eşzamanlı LLM çağrısı `DWHCODEREVIEW_LLM_PROCESS_MAX_CONCURRENT_CALLS` değerini aşmaz; yer bekleyen çağrı sırayla bekler ve iptal edilen koşumun bekleyen çağrısı hiç başlamaz. `nonprod` süreç geneli değeri RunAI kapasite sahibiyle belirlenen dağıtım girdisidir; girdi verilmezse varsayılan geçerlidir (Decision 7). Bir koşum tek HTTP istemcisi kullanır.

Requirement 8: Her istek `DWHCODEREVIEW_LLM_USER_AGENT` değerini (varsayılan `DWHCodeReview-Backend/1.0 (internal SQL review; httpx)`) taşır; anahtar tanımlıysa `Authorization: Bearer` başlığı eklenir, değilse hiç eklenmez.

Requirement 9: Başarısız çağrı sabit bir sınıfa eşlenir: `timeout`, `connect_error`, `tls_error`, `network_policy_denied`, `upstream_status` (HTTP kodu ile), `invalid_response`, `response_too_large`, `cancelled`. İnceleyiciye yalnız sınıfın kısa Türkçe iletisi (örnek: "LLM sunucusu yanıt vermedi (zaman aşımı).") ve varsa HTTP kodu gösterilir; adres, sunucu hata gövdesi, `.env` veya LM Studio ipucu gösterilmez.

Requirement 10: Her deneme (yeniden denemeler ayrı ayrı) için PostgreSQL'e bir LLM çağrı özeti yazılır: `public_id`, başlama zamanı (UTC), İnceleme koşumu kimliği, Nesne etiketi veya metin incelemesi etiketi, kural kimliği, parça (tek/1/2), deneme sırası, istek biçimi, model, uç ana makine adı (yol ve sorgu olmadan), akışlı mı, sonuç (`ok` veya Requirement 9 sınıfı), varsa HTTP kodu, süre (ms), `completion_tokens`, varsa `prompt_tokens` ve yanıt karakter sayısı. İstem, SQL, Nesne meta verisi, yanıt metni, sunucu gövdesi, anahtar ve başlıklar saklanmaz. Özet yazılamazsa inceleme sürer, hata olayı ve ölçümü üretilir.

Requirement 11: `kural-yoneticisi` son özetleri en yeniden eskiye listeler (`limit` 1–500, varsayılan 100) ve tek özeti `public_id` ile açar; tek kayıt da yalnız Requirement 10 alanlarını döndürür. Kaynaktaki tam istek/yanıt gösterimi kaldırılır.

Requirement 12: Uygulama logunda LLM çağrısına ait tek olay `llm.call`'dur ve yalnız Requirement 10 alanlarıyla `request_id` taşır. İstisna kayıtları sunucu yanıtı veya istem içeren istisna metnini yazmaz. JSON Lines dosyası, `LLM_LOG_FULL_PAYLOADS` davranışı ve kalıcı diskteki `llm_logs` klasörü yoktur.

Requirement 13: `local`'de LLM bağlantısı sayfası biçim seçimi, temel adres, sohbet adresi, model, anahtar (maskeli; "kayıtlı" bilgisi ve kaldırma seçeneğiyle), "Kaydet" ve "Yenile" sunar; kayıt yeniden başlatmadan sonraki çağrılarda kullanılır ve sayfa metni değerlerin yalnız çalışan sürece uygulandığını söyler. Vekil kutusu ve ikinci model alanı kalkar. `nonprod`'da `PUT` ucu yönlendiriciye eklenmez (404), `GET` `editable: false` ile yalnız biçim ve modeli döndürür, arayüz sayfayı ve menü öğesini göstermez.

Requirement 14: LLM çağrı özetleri başlama zamanından 90 gün sonra, günde en az bir kez kendiliğinden silinir; birden çok kopya varsa PostgreSQL kilidiyle (advisory lock) yalnız biri siler. Toplu veya elle silme ucu yoktur (Decision 6).

## API sözleşmesi

Bütün uçlar `/api/dwhcodereview/v1` altındadır, geçerli oturum ister; OpenAPI dosyası `specs/openapi/dwhcodereview-api.yaml` ve üretilmiş ön yüz tipleri aynı değişiklikte güncellenir. Hata gövdesi tek hata zarfıdır: `{"detail":{"code":"...","message":"..."}}`; istek kimliği `x-request-id` başlığıyla döner.

| Yöntem ve yol | Rol | İstek özü | Yanıt özü | Hatalar |
|---|---|---|---|---|
| `GET /llm-connection` | `kural-yoneticisi` | — | `environment`, `editable`, `chat_api`, `model`; `local`'de ayrıca `base_url`, `chat_url`, `resolved_chat_url`, `api_key_set` | 401, 403 |
| `PUT /llm-connection` (yalnız `local`) | `kural-yoneticisi` | kısmi `chat_api`, `base_url`, `chat_url`, `model`, `api_key` (yok = koru, `""` = sil) | `GET` ile aynı | 404 (`nonprod`), 422 (Requirement 2 ve 4) |
| `GET /llm-calls?limit=` | `kural-yoneticisi` | `limit` 1–500 | `items[]`: Requirement 10 alanları | 401, 403, 422 |
| `GET /llm-calls/{public_id}` | `kural-yoneticisi` | — | Requirement 10 alanları | 404 `llm_call_not_found` |

Kaynaktaki `DELETE /api/llm-logs` karşılığı yoktur (Decision 6). İnceleme uçları ve SSE akışı Nesne ve metin incelemesi PRD'lerinindir; bu PRD yalnız `llm_stream` olayının içeriğini (Requirement 3) belirler.

## Güvenlik ve yetkilendirme

- Kimlik ve rol [dizin girişi PRD'si](../../../application-foundation/PRDs/001-directory-login/PRD.md) ile gelir; kaynaktaki `X-API-Key` / `X-Admin-Key` başlıkları kaldırılır.
- Ağ politikası (Requirement 4) uygulama içi savunmadır; asıl sınır Kubernetes ağ çıkış kuralıdır (Dağıtım etkisi). Politikayı kapatan veya istisna tanıyan hiçbir ayar, uç veya arayüz yoktur.
- LLM'e giden içerik (SQL metni, Nesne tanımı, katalog ve sütun meta verisi) yalnız kurum ağındaki LLM ve çıkarım uçlarına gider; bu gönderim sahip tarafından onaylıdır ve incelenebilecek veritabanlarını sınırlamaz (Decision 8).
- Özet listesi yalnız `kural-yoneticisi` içindir; Nesne etiketleri veritabanı ve Nesne adlarını gösterdiği için `inceleyici`'ye açılmaz.

## Veri ve geçiş

- Yeni tablo `llm_call_summary`, Alembic göçüyle eklenir; `41-sema-zorunlu-sutunlari` zorunlu bloğunu taşır, `public_id` tek dış kimliktir. İnceleme koşumuna boş olabilen yabancı anahtarla bağlanır (koşum tablosu Nesne incelemesi PRD'sinindir); koşum [geçmiş PRD'sinde](../005-review-history-export/PRD.md) silinince bağ veritabanınca boşaltılır (`ON DELETE SET NULL`) ve özet kendi saklama süresine kadar kalır. Kiracı kapsamı dizin girişi PRD'sinin modeline uyar. Uygulama satırları yalnız ekler ve Requirement 14 ile siler; güncellemez.
- Kaynağın `requests.jsonl` dosyası taşınmaz: ham yanıt parçaları içerebilir. Kaynaktaki kalıcı diskteki `llm_logs` klasörü hedefte oluşturulmaz.
- Saklama süresi 90 gündür (Requirement 14).

## Gözlemlenebilirlik

- Log: Requirement 12 `llm.call` olayı; özet yazma hatasında `llm_call_summary.write_failed` (yalnız `request_id` ve hata sınıfı); saklama işi için `llm_call_summary.retention_run` (silinen satır sayısı, süre, sonuç).
- Ölçümler: `dwhcodereview_llm_calls_total{outcome,chat_api}`, `dwhcodereview_llm_call_duration_seconds{outcome}`, `dwhcodereview_llm_inflight_calls`, `dwhcodereview_llm_completion_tokens_total`, `dwhcodereview_llm_retries_total` ve Requirement 10'daki özet yazma hatası için `dwhcodereview_llm_call_summary_write_failures_total`. `outcome` `ok` veya Requirement 9 sınıfı, `chat_api` iki istek biçiminden biridir; model, kural ve koşum ölçüme girmez.
- İz (trace): her çağrı için içerik taşımayan bir `llm chat` aralığı; öznitelikleri model, sonuç, HTTP kodu ve deneme sırasıdır. Uç adresi, istem ve yanıt aralığa girmez. Ortak kurallar ve saklama süresi [application-foundation alanında](../../../application-foundation/DOMAIN.md) tanımlıdır. Tüketen test: `app/backend/tests/unit/test_llm_adapter.py`.

## Dağıtım etkisi

- **Ayarlar:** Requirement 1 anahtarları `app/backend/.env.example` (yer tutucuyla), yerel Compose ortam bloğu ve dağıtıma eklenir (anahtar Runtime Secret'a, sır olmayan değerler `helm/dwhcodereview/values-project.yaml`'a); `python3 scripts/check-config-sync.py` geçer. `nonprod` değerleri Decision 3'tür; dağıtım yolu [Kubernetes teslim PRD'si](../../../application-foundation/PRDs/002-kubernetes-delivery/PRD.md) sahipliğindedir.
- **Secret:** `DWHCODEREVIEW_LLM_API_KEY` yalnız anahtar isteyen bir uç için Runtime Secret'a yazılır; RunAI ucu anahtar istemez, bu nedenle `nonprod`'da boştur.
- **İmaj:** `corporate-inference-root.crt` (kaynak `backend/certs/`) backend imajının sistem güven deposuna eklenir; aynı kök CA dizin girişinin LDAPS doğrulamasında da gerekiyorsa imaja bir kez eklenir.
- **Bağımlılık:** Uyarlayıcı HTTP istemcisi doğrudan `httpx` kullanır; `httpx` bugün yalnız geliştirme bağımlılığıdır (`app/backend/requirements-dev.in`) ve çalışma zamanı bağımlılığı olarak diğer bağımlılıklar gibi `dependency-admission.json` kabul kaydına alınır. `requirements-llm.in` (LangChain) etkinleştirilmez (Decision 5).
- **Ağ çıkışı:** Backend LLM için yalnız RunAI ucunun adresine TCP 443 üzerinden çıkabilir; kaynakta gözlenen adres `10.14.3.99` (kaynak `helm/dwhcodereview/values.yaml` açıklaması). Kaynaktaki özel ağ geneline açık 80 ve 443 kuralı daraltılır; adres dağıtım öncesi yeniden doğrulanır.

## Test stratejisi

- **Birim:** adres çözümü (iki biçim, `/v1` sonları), Requirement 2 red durumları, hata sınıfı eşleme, yeniden deneme kararları ve bekleme süreleri, Ortam değerine göre uç kaydı, başlangıç doğrulaması, anahtarın yanıtta bulunmaması.
- **Sahte sunucuyla gerçek TCP:** yerel sahte LLM sunucusu SSE akışı, düz JSON, 200 + `{"error"}`, 500, askıda kalma (zaman aşımı ve deneme sayısı), 4 MiB'ı aşan yanıt ve yönlendirme durumlarını üretir. Test CA'sıyla imzalanmamış sertifika `tls_error` verir. Genel IP'ye çözülen ad ve bağlantı anında adres değiştiren sahte çözücü `network_policy_denied` verir ve sahte sunucu gövde almaz.
- **Eşzamanlılık:** 3 Nesne × 10 kurallı koşumda sahte sunucunun gördüğü en yüksek eşzamanlı istek sayısı koşum sınırını aşmaz; aynı anda süren iki koşumda toplam, süreç geneli sınırı aşmaz; istemci kopuşunda süren istekler kapanır.
- **Veri sızıntısı:** SQL metnine ve sahte yanıta konan ayırt edici bir işaret dizesi log çıktısında, `llm_call_summary` satırlarında ve API yanıtlarında aranır; bulunmamalıdır. `User-Agent` başlığı sahte sunucuda doğrulanır.
- **Göç ve API:** `llm_call_summary` göçü, zorunlu sütun kapısı, koşum silinince bağın boşalması, 90 günü aşan satırın saklama işiyle silinmesi ve iki kopyada tek kez silme, liste sınırları ve rol denetimi.
- **Ön yüz:** Vitest ve tarayıcı testiyle `local` kaydetme akışı, `editable: false` iken sayfanın gizlenmesi, hata sınıfı iletisinin gösterimi.

## Vektör ve gömme sözleşmesi (uygulanabilirse)

- Sağlayıcı / dağıtım sınırı: Uygulanamaz
- Model kimliği ve değişmez sürüm: Uygulanamaz
- Boyut ve normalleştirme: Uygulanamaz
- Uzaklık metriği ve indeks stratejisi: Uygulanamaz
- Getirim kalitesi/duyarlılık ve gecikme eşikleri: Uygulanamaz
- Kaynak sınıflandırması, en aza indirme ve saklama: Uygulanamaz
- Yeniden gömme, geçiş ve geri alma: Uygulanamaz

## Kabul kriterleri

- [ ] Acceptance 1: L1 — Otomatik testlerden geçti: Requirement 1–6, 8 ve 9 birim ve sahte sunucu testleri geçer; ağ politikası ve TLS red durumlarında sahte sunucu istek gövdesi almaz.
- [ ] Acceptance 2: L1 — Otomatik testlerden geçti: Requirement 7 koşum ve süreç geneli eşzamanlılık ve iptal testleri ile Requirement 10–12 ve 14 göç, API, saklama ve veri sızıntısı testleri geçer; işaret dizesi log, veritabanı ve API yanıtında bulunmaz; `scripts/check-config-sync.py` ve tam kalite kapısı geçer.
- [ ] Acceptance 3: L1 — Otomatik testlerden geçti: Requirement 13 ön yüz testleri ile OpenAPI ve üretilmiş tiplerin güncelliği doğrulanır.
- [ ] Acceptance 4: L2 — Gerçek istemci/ortamda doğrulandı: `local` Ortamda yerel PostgreSQL ile, kurum ağından Decision 3 ucuna `openai` biçimiyle gerçek bir inceleme tarayıcıdan tamamlanır; canlı ilerleme görünür, özetler `kural-yoneticisi` listesinde model, süre ve belirteç sayısıyla yer alır, log ve özetlerde SQL ile yanıt metni bulunmaz; arayüzden model değiştirilince yeniden başlatmadan sonraki çağrı yeni modeli kullanır ve `app/backend/.env` değişmez (Requirement 3, 7, 10, 13).
- [ ] Acceptance 5: L2 — Gerçek istemci/ortamda doğrulandı: `nonprod` ayarlarıyla yerelde çalışan sürümde `PUT /llm-connection` 404 döner, LLM bağlantısı sayfası görünmez, `http` adresli veya modelsiz yapılandırmada süreç başlamaz (Requirement 1, 13). Küme dağıtımı bu kanıtın parçası değildir ve ayrı kullanıcı talimatı ister.

## Kararlar

Decision 5: Uyarlayıcı doğrudan `httpx` ile yazılır; LangChain (`requirements-llm.in`) etkinleştirilmez. Kaynak davranışı iki basit HTTP biçimi ve akıştan belirteç sayımıdır; `api_v1_chat` biçimi hazır entegrasyonla karşılanmaz. `httpx` çalışma zamanı bağımlılığı olarak kabul kaydına alınır.

Decision 6: LLM çağrı özetleri 90 gün saklanır ve süresi dolan satırlar kendiliğinden silinir (Requirement 14); toplu silme ucu yoktur, çünkü özetler hangi incelemenin hangi modelle yapıldığının kaydıdır.

Decision 7: Koşum başına sınıra ek olarak süreç geneli bir LLM çağrı sınırı vardır (Requirement 7); RunAI ucu başka ürünlerle paylaşılır. `nonprod` değeri RunAI kapasite sahibiyle belirlenen dağıtım girdisidir.

Decision 8: SQL kodu, Nesne tanımı ve katalog/sütun meta verisinin kurum ağındaki LLM ve çıkarım (model çalıştırma) servislerine, Decision 3'teki RunAI ucu dahil, gönderilmesine proje sahibi 2026-09-26'da izin verdi. LLM veri hassasiyeti nedeniyle incelenebilecek veritabanları sınırlanmaz; hangi veritabanlarının okunabileceğini bağlantı hesabının SQL Server yetkileri belirler ([SQL Server bağlantısı PRD'si](../002-sql-server-connection/PRD.md) Decision 5).

## Teslim akışı

Belirtim → Plan → Görevler → Uygulama

## Riskler

- **Paylaşılan kapasite:** RunAI ucu başka ürünlerle paylaşıldığından yoğunlukta zaman aşımı artar; 900 sn okuma süresi ve 2 ek deneme bir kuralın 45 dakikaya kadar sürmesine yol açabilir.
- **Model ve adres değişimi:** Uç yolu ve model kimliği (`/data/models--Qwen--…`) RunAI tarafında değişirse inceleme durur; değişiklik yalnız yeni dağıtımla yapılabilir.
- **Ağ adresi:** RunAI ucunun IP'si değişirse daraltılmış ağ çıkış kuralı çağrıları keser; adres her dağıtımda doğrulanmalıdır.
- **Sertifika:** Kurum kök CA'sının geçerliliği 2037'de biter; CA değişirse imaj yenilenmelidir.
- **Kayıt hacmi:** Her kural, parça ve deneme ayrı satırdır; büyük koşumlar binlerce satır üretir. 90 günlük saklama (Requirement 14) tabloyu sınırlar, ancak saklama işi durursa tablo büyür.
- **Davranış farkı:** Vekil ayarı ve açık internet istisnası kalktığı için vekil arkasındaki veya genel internetteki LLM'e yerelden bağlanan geliştirici kurulumları çalışmaz; bu bilinçli bir kısıttır.
