# DWH Code Review

Veri ambarı geliştiricilerinin SQL Server nesnelerini ve yapıştırılan SQL kodunu yayımlanmış inceleme kurallarına göre kurum içi LLM ile incelemesi, bulguları satır referanslarıyla görmesi ve CSV/SQL olarak dışa aktarması; Active Directory girişiyle ve kurumsal Kubernetes ortamında güvenli çalışma.

Bu depo çalışan platform temel çizgisiyle başlar: PostgreSQL, JWT kimlik doğrulama, RBAC, uygulama
`super-admin` kullanıcısı, sağlık/hazır olma uç noktaları, yerelleştirilmiş ön yüz ve gerçek tarayıcı
kanıtı. Bilinçli olarak örnek iş varlığı içermez.

Birincil alan bağlamı: `specs/sql-review/`. Arka uç profili: `python-fastapi`.
Kalıcılık otoritesi: `sqlalchemy-alembic`.

## Kılavuzlar

- [Kullanım kılavuzu](docs/tr/kullanim-kilavuzu.md): giriş, roller, nesne ve SQL betiği incelemesi,
  geçmiş, CSV ve SQL dışa aktarma, yanlış pozitif ve 90 günlük saklama.
- [Yönetici kılavuzu](docs/tr/yonetici-kilavuzu.md): süper yönetici, rol ve hesap yönetimi, kuralları
  yayımlama, SQL Server ve LLM ayarları, isteğe bağlı Azure gizli değişkenleri, günlükler.
- [Yerel kurulum](docs/tr/yerel-kurulum.md): uygulamayı macOS'ta VS Code görevleriyle başlatma ve
  durdurma, yerel hesap açma.

## Üretilen sınırlar

İlk oluşturma işlemi tam proje ağacını kurar. Bundan sonra `app/**` uygulama ekibine aittir; merkezi
iskelet güncellemesi bu kapsamın üzerine yazmaz veya bu kapsamı silmez. `helm/**` ise temel iskelet
ve DevOps tarafından yönetilen kapsamdır; aşağıda anlatılan, projeye ait iki dağıtım dosyası bunun
dışındadır. DevOps standardı gereği uygulama chart'ı (Kubernetes'e kurulum paketi)
`helm/dwhcodereview/` dizinindedir: kendi `Chart.yaml`, `templates/**`, `deploy.sh` ve tam olarak
bir `values.yaml` dosyasından oluşan tek Helm paketi içinde arka uç ve ön yüz iş yüklerini taşır.
Aynı pakette PostgreSQL 17 veritabanı ve Alembic şema geçişi (veritabanı tablolarını güncelleyen tek
seferlik iş) de vardır, ama `values.yaml` içindeki `postgres` ve `migration` bölümlerinde varsayılan
olarak kapalıdır; yalnız projenin kabul edilmiş PRD'si isterse açılır. Kuralları
`rules/45-dagitim-hedefi.md` dosyasındadır. Redis, işleyici ve gözlemlenebilirlik iş yükleri ihtiyaç
doğduğunda kabul edilmiş proje çalışmasıyla eklenir.

## İmaj yayını ve Helm dağıtımı

`.github/workflows/image-build.yml`, `main` dalına gelen her committe backend ve frontend release
imajlarını `ghcr.io` üzerinde `latest`, UTC tarih, kısa SHA ve tam SHA etiketleriyle yayımlar. Helm
değerlerindeki kanonik repository yolu kurum içi GHCR proxy-cache adresidir.

Azure işi `IMAGE_TAG=latest` ile çağırdığında `helm/dwhcodereview/deploy.sh`,
`BUILD_SOURCEVERSION` değerini tam 40 karakter SHA olarak doğrular ve iki workload için aynı etiketi
seçer. Mevcut Azure Secure File adımının sağladığı `KUBECONFIG` kullanılır; ayrı yayın makbuzu veya
ikinci audit akışı yoktur.

Apply yolu kümeye dokunmadan önce iki imajın registry'de yayımlandığını `curl` ile sorar. Yayın
gecikmişse `IMAGE_WAIT_SECONDS` (varsayılan 1200) boyunca bekler; imaj yine yoksa küme değişmeden
durur. Registry yanıt vermezse `[IMAGE] UNKNOWN` yazıp devam eder. Beklemedeki release için önce
çalışan dağıtım `PENDING_WAIT_SECONDS` (varsayılan 1800) kadar beklenir; yarım kalmış upgrade geri
alınır, hizmet vermiş release kaldırılmaz. Aynı işin eşzamanlı koşmaması Azure tarafında ayrıca
ayarlanmalıdır.

~~~sh
TF_BUILD=true BUILD_SOURCEVERSION=<40-character-lowercase-sha> helm/dwhcodereview/deploy.sh

IMAGE_TAG=<explicit-tag> helm/dwhcodereview/deploy.sh --render
~~~

Kanonik giriş NetworkPolicy'si yönetilen test RKE2 kümesindeki controller'ın gerçek namespace'i olan
`kube-system` değerini taşır. `nginx` IngressClass adıdır; `ingress-nginx` namespace varsayımı değildir.

Apply sırasında script, Azure runner'da hedef namespace'te bulunmayan `ailab-tls` Secret'ını
varsayılan olarak `kt-verim/ailab-tls` kaynağından kopyalar. `TLS_COPY_ENABLED=false` bu davranışı
kapatır; `TLS_SOURCE_NAMESPACE`, `TLS_SOURCE_SECRET` ve `TLS_TARGET_SECRET` adları değiştirebilir.
Sertifika ve anahtar yalnız owner-only geçici dizinden geçirilir, Git'e veya Helm argümanına yazılmaz.
Script önce `helm lint` çalıştırır; varsa proje kancasını çalıştırır, veritabanı `Secret`'larını
hazırlar, beklemedeki release'i kurtarır ve ardından
`helm upgrade --install --reset-values --atomic --wait --wait-for-jobs` çalıştırır; şema geçişi
başarısız olursa önceki sürüm korunur. Render kipi cluster'a erişmez, kancayı çalıştırmaz ve Secret
yazmaz.

Güvenilen yerel MCP kurulu üreteçle sabit çalışma alanına doğrudan yazabilir. Uzak HTTP MCP ise aynı
kanonik dosya baytlarını, modları ve SHA-256 özetlerini sayfalar halinde teslim eder; Claude, Codex
veya seçilen VS Code istemcisi bunları kendi yerel dosya araçlarıyla uygular ve gözlediği envanteri
geri bildirir. Uzak sunucu yerel dosya sistemini okuduğunu, yazdığını veya atomik yayın yaptığını
iddia etmez; canlı HTTP güveni TLS/mTLS/OAuth sınırından gelir.

## Projenin dağıtım dosyaları

Test kümesine dağıtmak için fabrikanın dosyalarını düzenlemeyin; `kt-iskelet guncelle` onları
yeniden yazar. Bunun yerine chart'ın yanına projenin kendi iki dosyasını ekleyin. İskelet bu
dosyaları hiç oluşturmaz, değiştirmez veya silmez; ikisi de isteğe bağlıdır.

`helm/dwhcodereview/values-project.yaml` (değer katmanı): `deploy.sh` bu dosyayı `values.yaml`
dosyasının üstüne ekler. Yalnız adresleri ve gizli olmayan ayarları taşır; parola, anahtar veya
belirteç yazılırsa `scripts/render-charts.sh` denetimi reddeder. Örnek:

~~~yaml
backend:
  existingSecret: dwhcodereview-runtime   # deploy-hooks.sh'in hazırladığı Secret'ın adı
  config:
    DWHCODEREVIEW_ENVIRONMENT: staging       # gizli olmayan ayarlar
  networkPolicy:
    egress:                                  # arka ucun ulaşabileceği adresler
      - to:
          - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}
            podSelector: {matchLabels: {k8s-app: kube-dns}}
        ports: [{protocol: UDP, port: 53}, {protocol: TCP, port: 53}]
      - to:
          - podSelector:
              matchLabels:
                app.kubernetes.io/part-of: dwhcodereview
                app.kubernetes.io/component: database
        ports: [{protocol: TCP, port: 5432}]
frontend:
  ingress:
    className: nginx
    host: dwhcodereview.ailab-test.kuveytturk.com.tr
    tlsSecretName: ailab-tls
postgres:
  enabled: true                              # yalnız kabul edilmiş PRD isterse
  persistence: {storageClassName: <kümenin-depolama-sınıfı>}
migration:
  enabled: true
~~~

`helm/dwhcodereview/deploy-hooks.sh` (dağıtım kancası): `deploy.sh` bunu yalnız gerçek dağıtımda,
imajlar yayımlandıktan ve namespace hazırlandıktan sonra, Helm hiçbir şeyi değiştirmeden önce `bash`
ile çalıştırır. Görevi projeye özgü sırları kümede hazırlamaktır: örneğin imza anahtarını ilk
dağıtımda üretip sonrakilerde kümedekini kullanmak veya isteğe bağlı dış hizmet bilgilerini çalışma
zamanı `Secret`'ına koymak. Kanca `KT_DEPLOY_RELEASE`, `KT_DEPLOY_NAMESPACE`, `KT_DEPLOY_CHART_DIR`,
`KT_DEPLOY_IMAGE_TAG` ve `KT_DEPLOY_DATABASE_ENABLED` değişkenlerini alır. Gizli değeri ekrana
yazdırmamalı, değerleri `kubectl`'e komut argümanıyla değil dosyayla vermelidir. Kanca hata verirse
dağıtım Helm değişikliği yapmadan durur. Arka ucun imza anahtarını bir kez üreten örnek:

~~~bash
#!/usr/bin/env bash
set -euo pipefail
secret="$KT_DEPLOY_RELEASE-runtime"
key_file=DWHCODEREVIEW_JWT_PRIVATE_KEY
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
umask 077
current="$(kubectl --namespace "$KT_DEPLOY_NAMESPACE" get secret "$secret" --ignore-not-found \
  --output "jsonpath={.data.$key_file}")"
if [[ -n "$current" ]]; then
  base64 --decode <<< "$current" > "$work/$key_file"
else
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$work/$key_file"
fi
kubectl --namespace "$KT_DEPLOY_NAMESPACE" create secret generic "$secret" \
  --from-file="$work/$key_file" --dry-run=client --output yaml | kubectl apply --filename - >/dev/null
~~~

Veritabanı açıksa `deploy.sh` kancadan sonra üç `Secret` hazırlar ve parolaları ilk dağıtımda üretir,
sonrakilerde kümedekini yeniden kullanır: `<release>-postgres` (veritabanı sahibi),
`<release>-migration` (şema geçişi) ve `<release>-database` (arka ucun `DWHCODEREVIEW_DATABASE_URL`
bağlantısı). Arka uç yalnız veri okuyup yazabilen bir veritabanı rolüyle bağlanır; tabloları yalnız
şema geçişi değiştirir. Kanca bu `Secret`'lardan birini önceden oluşturursa içindeki değer korunur.

## İlk çalıştırma

~~~sh
scripts/bootstrap.sh
scripts/stack.sh up -d --build --wait
scripts/db.sh apply
scripts/create-super-admin.sh
scripts/create-local-user.sh --role inceleyici        # dizin kapalıyken yerel test hesabı
scripts/create-local-user.sh --role inceleyici
scripts/quality-gate.sh all
export KT_SCAFFOLD_OFFLINE_BUNDLE=/approved/bundles/<platform-matrix>
export KT_SCAFFOLD_OFFLINE_BUNDLE_SHA256=<bank-admission-sha256-of-SHA256SUMS>
scripts/e2e.sh auth
~~~

`scripts/quality-gate.sh all`, ağ gerektirmeyen bağımlılık kabul kontrolünü içerir. Kod barındırma
platformundaki güvenlik işini yerelde yeniden üretmek için `INTERNAL_SCANNER_MATERIAL_DIR`,
`INTERNAL_SCANNER_SHA256SUMS`, bant dışı `INTERNAL_SCANNER_SHA256SUMS_SHA256`,
`INTERNAL_SCANNER_ADMITTED_ON`, `INTERNAL_SEMGREP_RULESET` ve `TRIVY_CACHE_DIR` değerlerini banka
tarafından kabul edilmiş, en çok yedi günlük tek tarayıcı anlık görüntüsüne yöneltip
`scripts/security-gate.sh` çalıştır. Dependabot yalnız banka yönetimli GitHub Enterprise servisi
onaylı iç yansılara erişebildiğinde etkindir; her öneri kabul defterinden geçmelidir.

Tam yerel kapı ayrıca üretilen projenin sabitlenmiş `kt-iskelet` sürümünü ve `PATH` üzerinde Helm'i
gerektirir. Helm paket politikası bu CLI'ın kabul edilmiş Python yorumlayıcısını kullanır ve çalışma
zamanı ayrıştırıcısı indirmez.

Bütün çalışma zamanı servisleri yerel ağda veya küme ağında kalır. Bağlantıyı kesmeden önce
çevrimdışı paketi bankanın kontrollü yansısından doldur; uygulama çalışma zamanında kod, yazı tipi,
betik, model veya telemetri hedefi indirmez. E2E yardımcısı çevrimdışı başlar, paket
bildirimini bant dışı banka kabul özeti ve platform matrisiyle doğrular, yalnız npm önbelleğinden
kurar ve eşleşen Chromium derlemesini çalıştırır. Paket, güven kökü veya uyumlu tarayıcı yoksa
güvenli biçimde başarısız olur.

## Ortak yönetişim kayıtları

Prompt makbuzu, LLM çağrı olayları, review koşumu ve commit kayıtları repo ve kullanıcı dizini
dışında, işletim sisteminin bütün kullanıcılarına açık tek bir kökte `project_id` ile ayrılır:
macOS'ta `/Users/Shared/kt-scaffold/governance/`, Windows'ta `%ProgramData%\kt-scaffold\governance\`,
Linux'ta yöneticinin bir kez oluşturduğu `/var/lib/kt-scaffold/governance/`. Desen
`<kök>/<project_id>/<tür>/...` biçimindedir; her kayıt bir kez yazılır, cihaz adını ve işletim
sistemi kullanıcı adını taşır ve değiştirilmez. Kayıt yazılamazsa prompt kararı ve ajan akışı
değişmez, sabit bir uyarı verilir; repo'ya, kullanıcı dizinine veya geçici dizine yazılmaz. Hassas
içerikli prompt her durumda gönderilmez.

Kayıtların saklandığı yer koruma iddiası taşımaz; aynı cihazdaki kullanıcılar kayıtları okuyabilir.
Güven, on iki uzman ajanın bağımsız değerlendirmesinden ve bu kanıtı ajan yolunda uygulayan prompt ve
commit kancalarından gelir. Ajanın dosya araçları ortak köke yalnız inceleme koşumu girdilerini
yazabilir; son deterministik denetim CI'dadır. Tek uzman Agent çağrısı
`governance_client.py consultation` komutuyla karar ve commit yetkisi taşımayan danışma kaydı
üretir. Mevcut native session/turn hash'leri korunur; istemci vermediyse kimlik uydurulmaz. Ham
LLM/Agent çıktısı toplanmaz.

İlk kullanımdan ve yönetilen incelemeden önce proje kökünde çalıştır:

```bash
python3 .kt-scaffold/hooks/governance_client.py preflight
```

Bu komut kayıt okumaz ve hiçbir şeyi değiştirmez; ortak kökü, yazılabilirliğini, `.venv`
yorumlayıcısının teknoloji profiliyle eşleşmesini ve projenin commit'i olan bir git deposunda
(projenin değişiklik geçmişini tutan kayıt) bulunduğunu gösterir. `repository_status`
`not-a-repository` veya `no-commit` ise proje oluşturmanın son adımı olan ilk commit (projenin ilk
kaydedilmiş hâli) yapılmamıştır. `ok: true` kayıt yazma yetkisi veya native kanca başarısı değildir.
Prompt kaydı yoksa kaydı elle üretme; seçili istemcinin kanca keşfi/güven onayı/etkinliğini doğrula.
Codex'te proje güveni kanca güveninden ayrıdır; CLI `/hooks` ekranında güncel tanımı incele. Sorun
çözüldükten sonra yeni gerçek prompt gönder. Başka oturumun makbuzunu kullanma. Sonuç bu bağlar
tamamlanana kadar `BLOCKED_INCOMPLETE` olarak bildirilir; teslim kapısı geçilmiş sayılmaz.
[Codex kanca güveni](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks), 2026-09-16.

## Yönetişim yüzeyi ve oturum kökü

Kodlama istemcisini daima proje kökünde başlat. Prompt, commit ve yönetişim yüzeyi kancaları yalnız o
kökte başlatılan oturumda yüklenir; üst dizinden, başka depodan veya projeyi başka kökten oluşturan
oturumdan yapılan değişiklik kancasız kalır. Oturum kökünden bağımsız kalan tek yerel kapı `scripts/git-gate.sh`
ile etkinleşen Git `pre-commit` tutarlılık denetimidir. Kabuk komutundan sonra sapma olursa ajan
`GOVERNANCE_DRIFT_DETECTED` geri bildirimi alır. Sapan yönetilen dosya
`python3 .kt-scaffold/hooks/governance_client.py restore <yol>` ile kaydedilmiş doğru hâline
döner; adımın sahibi `rules/04-politika-catismasi.md` kuralıdır.

`agent-platform/`, `rules/`, `.kt-scaffold/` altındaki kanca, manifest ve projeksiyonlar, üretilmiş
talimat ve istemci yüzeyleri, teknoloji profili, bağımlılık kabul kaydı ve yönetişim CI kapıları
yönetişim yüzeyidir; tam liste `rules/04-politika-catismasi.md` içindedir. Bu yüzey yalnız
kullanıcının başlattığı `/kt-guncelle`, `/kt-yansit`, MCP iskele eşitlemesi veya yönetişim
uzlaştırmasıyla değişir. Bulgu; kontrol, detector veya eşik silinerek çözülmez. Uzman Agent ve
`agent:otomatik-duzeltme` önerileri değişiklik yetkisi değildir; AutoFix kapalıdır.

Claude Code'da bu yüzeye yerel dosya aracıyla yapılan her yazım `.claude/settings.json` izin
kuralıyla insan onayı ister; kural hiçbir izin kipinde atlanmaz. `governance_surface_guard.py`
kancası özete bağlı yetki varlıklarında kısmi düzenlemeyi ve bağlantı, harf varyantı veya üst dizin
geçişiyle yapılan yazımı reddeder. Ortak yönetişim kökündeki kayıtlar, `.claude/settings.local.json`
ve kullanıcının `~/.claude/settings.json` dosyası yerel dosya aracına kapalıdır. Aynı kanca Codex
`apply_patch`, Cursor `Write`/`Delete` ve VS Code/Copilot dosya araçlarında da çalışır; bu
istemcilerde yol kapsamlı onay olmadığından mevcut yetki varlığı yerel dosya aracıyla değiştirilemez
ve kanonik güncellemesini kullanıcı `kt-iskelet guncelle` ile yapar. Codex kancaları proje güvenilir
ve `/hooks` ile onaylı, Cursor kancaları çalışma alanı güvenilir olduğunda çalışır. Codex'te kabuk
yazımını da kapatan salt okunur profil yalnız yönetici tarafından makine düzeyinde kurulur.
Kabuk/yorumlayıcı yazımı, harici düzenleyici ve insan düzenlemesi kanca dışında kalır;
`scripts/render-clients.sh --check`, commit kapısı ve CI sapmayı saptar. Bu
`conditional-native-guard` iddiasıdır; değişmezlik veya üretim uygulatımı değildir.

## Governed review ve commit

Seçilen kodlama istemcisi, kendi native skill yolundaki `governed-review` becerisini açık inceleme,
PR/teslim, birden çok risk alanı, otorite/politika/manifest sapması veya
`GOVERNED_REVIEW_REQUIRED` işareti için kullanır. Her istem turunda ve her küçük TDD adımında tam
inceleme çalıştırılmaz. Becerinin çekirdeği bir `supervisor` ajanı değil,
`agent-platform/orchestrations/governed-review.yml` içindeki on iki zorunlu Agent'ın ayrı çağrıları ve
`policy:governed-review-aggregation` değerlerini kullanan Agentic karardır; MCP zorunlu değildir.

Faz 1 becerisi exact adayı Git index tree, `HEAD` ve bütün merge parent kimlikleriyle bağlar. Project,
authority, orkestrasyon, policy, evaluator/harness/rule/skill, on iki Agent paket/projection,
istemci, prompt-template/envelope ve context/retrieval/tool-result manifestleri reuse kimliğine
dahildir. On iki ayrı non-authoritative Agentic observation, policy
version/digest/instruction-digest/değerleri,
strict karar digest'i ortak kökte `<project_id>/governed-review/<run_id>/` altında tutulur.
Run/trace/span korelasyonlu review audit'i ve yayın işaretini `finalize-review` komutu aynı yere bir
kez yazar; repo içinde audit veya makbuz kopyası oluşturulmaz. Ham prompt, secret, PII veya exact kaynak içeriği
review makbuzuna yazılmaz. Yalnız exact aynı staged adayın retry'si
`PASS` makbuzunu yeniden kullanabilir; index, `HEAD`, merge parent, policy veya rapor digest'i
değişirse tam inceleme yenilenir.

Receipt içindeki tek versioned `decision_evidence`, zorunlu ve doğrulanabilir `audit_replay` ile
best-effort `model_rerun` capability'lerini ayırır. İkinci geçiş validator ayrı invocation/span,
identity/version/digest, checked digest seti ve yeniden hesaplanan verdict/reason/skorları taşır;
yalnız `verified` self-claim yeterli değildir ve harici bağımsızlık kanıtı sayılmaz. Bilinmeyen
provider/deployment/model/inference metadata uydurulmaz; explicit `unavailable` + reason yalnız model
rerun'ı unavailable yapar. Exact model output garantisi yoktur. Tam içerik gelecekte gerekirse genel
audit'e gömülmez; yalnız erişim kontrollü ve süreli `evidence-vault:` referansı tutulabilir.

On iki observation JSON, decision ve run receipt çalışma artifact'ları yalnız istemcinin native
`Write`/`Edit` dosya araçlarıyla yazılır; Python/interpreter/heredoc/compound Bash artifact generator
değildir. Audit'i `finalize-review` doğrulayıp yazar; audit yazılmadan koşum yayımlanmaz. Ayrı sürümlü Faz 1 Agentic evaluator policy'si ana LLM'in kanonik aggregation alanlarını
uygulamasını ve aynı evaluator digest'ini observation/decision/receipt/audit zincirine bağlamasını
zorunlu kılar. Deterministik `semantic_evaluators: []` Faz 2 sözleşmesidir. Eksik veya belirsiz
binding `BLOCKED_INCOMPLETE` kalır. Artifact'lardaki ham prompt/kaynak dışlama alanları istemci-owned
transcript/tool-result non-retention kanıtı değildir. Proje MCP/Web aracı çağrılmaması da
Claude/model control-plane ağ izolasyonunu kanıtlamaz.

Dört native projeksiyon repo-local, Python standard-library-only
`agentic_review_receipt_guard.py` command harness'ını kullanır; hostta `python3` gerekir. Harness
yalnız görünür doğrudan `git`/`/usr/bin/git ... commit` için aynı snapshot `PASS`
makbuzunun tam v3 reuse, on iki report, decision, second-pass ve audit zincirini doğrular; eksik,
bayat, tahrif edilmiş veya tool/plumbing hatasında exit 2 deny üretir. Kanca Agent çağırmaz,
bulguları puanlamaz veya semantic karar üretmez. Normal ana Agent turu beceriyi çalıştırıp artifact
zincirini ürettikten sonra aynı commit yeniden denenir.
Agentic `PASS` ve aynı-snapshot reuse için istemci kimliği/sürümü/digest'i ve mandatory audit
binding'leri receipt'te bulunmalıdır. Claude/Codex event'leri sürüm taşımaz, VS Code session ve
sürümü zorunlu taşımaz; yalnız Cursor `conversation_id` ve `cursor_version` alanlarını native
eventten `native-event-observed` olarak bağlar. Diğer sürümler yalnız `agent-self-observed`
metadata'dır ve native pin eşleşmesi değildir. Raw session yerine prompt-ingress ile aynı privacy-safe
`session:client.<sha256(raw-session-utf8)>` bağı kullanılır. Optional model-rerun metadata eksikliği
verified audit replay'i tek başına `BLOCKED_INCOMPLETE` yapmaz.

Cursor command hook `failClosed: true` kullanır; Claude/Codex/VS Code error, timeout, trust, disable
ve bypass sınırları aynı değildir. Bu projeksiyon yalnız `conditional-native-guard` L1 iddiasıdır;
yeni pinned L2, istemciler arası parity veya production enforcement değildir. Çözülebilen
`command`/`env`/`sudo`/`sh -c` commit sarmalayıcıları ve gerçek commit segmenti içeren dynamic
şekiller artifact okumadan deny edilir; opaque wrapper ve alias kapsam dışıdır. Opaque wrapper,
harici terminal ve Git GUI repo-local native
kancayla evrensel olarak önlenemez. Görünür `git commit --no-verify` native kapıda kalır; yalnız Git
hooklarını atlar. `-a/--all`, include/only/interactive/patch ve pathspec direct commit şekilleri
staged snapshot'tan farklı tree seçebildiği için deny edilir. CI/kabul ise teslim iddiasının otoriter
yeniden doğrulamasıdır.
Verifier yalnız pre-execution snapshot'ını denetler; eşzamanlı index/pre-commit TOCTOU'yu mutlak
önlediği iddia edilmez ve native L2 allow kanıtı oluşan commit tree'sini ayrıca karşılaştırmalıdır.

`scripts/bootstrap.sh` veya `scripts/git-gate.sh`, Git deposunda `core.hooksPath` değerini
`.kt-scaffold/hooks/git` yapar; oradaki `pre-commit` kancası oturum kökünden ve istemciden bağımsız
olarak her commit'ten önce governance-drift denetimini çalıştırır. `core.hooksPath` ayarlıyken
`pre-commit install` kurulum yapmaz; daha önce kurulmuş `.git/hooks/pre-commit` kancası kapıdan sonra
çalıştırılır. `pre-commit install` yalnız bağımsız Gitleaks ve governance-drift kontrollerini kurar. Yönetilen
mekanik governed-review Git/CI/MDM kapısı ve mevcut launcher kodu Faz 2'ye ertelenmiştir; Faz 1 etkin
hook/skill yolu kurulu bir `kt_scaffold` paketi gerektirmez.

Faz 1 Agentic makbuzları yerel ve mutable'dır. Şemaları strict olsa da LLM üretimi kendi kendine
belirlenimci kanıt, canonical conformance, runtime admission, immutable audit, Collector/OTLP export
veya production decision authority oluşturmaz. Tam 14 audit satırı yalnız review yaşam döngüsünü
(başlangıç + 12 Agent + karar) kaydeder; native hook allow/deny, retry veya hook-error sonucunu
kanıtlamaz.

## İlk iş yetkinliği

Yalnız yeni bağımsız yetenek için yerel ajan araçları veya isteğe bağlı `kt-iskelet spesifikasyon` CLI
ile PRD oluştur, incele, `Status` değerini `Accepted` yap; ardından şema, arka uç, ön yüz ve tarayıcı
kanıtını bu belirtim yolundan uygula. Mevcut kabul edilmiş PRD kapsamındaki küçük uygulama,
davranışsız yeniden düzenleme veya onarıcı hata düzeltmesinde yeni PRD üretme; exact
`Requirement <n>`/`Acceptance <n>` ve mevcut görev/koşum izini yeniden kullan. Çalışma alanına bağlı
yerel MCP, doğrulanmış ilk yazım için önceden kurulu üreteci çağırabilir;
uzak yönetişim MCP bu depoyu incelemez veya doğrudan düzenlemez. Sonraki her değişikliğin sahibi yerel
kodlama ajanıdır. `specs/README.md` dosyasına bakın.

Ürüne dönük dokümantasyon `docs/tr/` altındadır. Kabul edilmiş PRD'leri; mühendislik kurallarını veya
uygulama planlarını ikinci gereksinim kaynağına kopyalamadan güncelleyin.
