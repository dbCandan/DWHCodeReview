# Yerel altyapı

Yerel yığın PostgreSQL, seçilen arka uç, ortak ön yüz ve aynı kaynaklı ters vekil sunucu içerir.
Redis yalnız önbellek yuvasıdır: `cache` Compose profiline bağlıdır, varsayılan yığında başlamaz ve
arka uç ona bağımlı değildir. Kabul edilmiş bir önbellek PRD'si onu `--profile cache` ile açar.
Uygulama/veri çalışma zamanı ağı kurum içi işaretlidir; bu servisler internete erişemez. Docker
Desktop, yalnız iç köprüden port yayımlayamadığı için yalnız nginx ve isteğe bağlı Grafana, ana
makineye dönük uç köprüye de katılır. Port yalnız geri döngü adresindedir, DNS kapalıdır ve
varsayılan yapılandırmada dışa giden üst akış yoktur; çevreleyen dış ağ trafiği kontrolü banka ana
makine güvenlik duvarıdır. Seçiliyse gözlemlenebilirlik de iç ağda kalır. nginx yalnız `localhost`
ve `127.0.0.1` adlarıyla gelen isteğe yanıt verir; başka bir adla gelen istek (örneğin kötü niyetli
bir sitenin adını bu bilgisayara yönlendirmesi) `421` ile reddedilir. Arka uca ve ön yüze tarayıcının
gönderdiği ad değil, sabit `localhost` adı iletilir. SQL Server ve LLM'e yerel erişim yalnız açıkça
seçilen `local-egress` profiliyle açılır (aşağıda).

Bütün üçüncü taraf imajları sürüm ve özetle (`@sha256:`) sabitlenmiştir. Makinede yoksa Docker
bu sabit özeti kayıt deposundan kendisi indirir; özet değişmediği için indirilen imaj incelenen
imajın aynısıdır. Çevrimdışı CI imajları paketten önceden yükler, bu durumda indirme yapılmaz.
Yayımlanan portlar yalnız geri döngü adresine bağlanır. İsteğe bağlı toplayıcı yalnız yerel Tempo,
Prometheus ve Loki servislerine aktarır; Grafana panosu yerel olarak hazırlanır. Bu katman açıkken
arka uç izlerini ve ölçümlerini OTLP/gRPC ile iç ağdaki toplayıcıya gönderir
(`DWHCODEREVIEW_OTEL_EXPORTER_OTLP_ENDPOINT`); katman yoksa arka uç hiçbir sinyal göndermez.
Bu Compose katmanını etkinleştirmeden önce Git tarafından yok sayılan `.env` içinde `GRAFANA_ADMIN_PASSWORD`
ayarlayın; anonim erişim, güncelleme denetimi, analiz, Gravatar ve eklenti indirme kapalıdır.

Her çalışma zamanı/temel imaj referansı, kaydedilmiş varsayılanı özetle sabitlenmiş kalan ortam
geçersiz kılmasıdır. Banka dağıtımı yalnız kayıt deposu ön ekini terfi ettirilmiş iç imaja çevirir;
özet incelenmiş kimlik olarak kalır. `DEPENDENCY_MODE=offline` ile mutlak
`PYTHON_WHEELHOUSE_CONTEXT` ve `NPM_CACHE_CONTEXT` yolları doğrulanmış paketi BuildKit'e
bağlar. Çevrimdışı Python ve ön yüz derlemeleri yalnız kabul edilmiş bağımlılıkları kullanır.
`connected` kipi de yalnız kontrollü ortam yapılandırmasıyla sağlanan banka yönetimli paket yansılarını
kullanır. Üretilen çevrimdışı CI, mutlak `KT_SCAFFOLD_OFFLINE_BUNDLE` ile ayrı dağıtılan
`KT_SCAFFOLD_OFFLINE_BUNDLE_SHA256` kabul özetini ister, imaj yüklemeden önce doğrular ve bütün
adlandırılmış bağlamları açıkça ayarlar; bağlı bağımlılık çözümlemesine geri dönmez.

Sabitlenmiş nginx tabanında henüz bulunmayan güvenlik düzeltmeleri
`locks/nginx-alpine-packages.lock` dosyasında durur: her satır bir Alpine paketinin tam sürümünü ve
SHA-256 özetini (içeriğin parmak izi) mimari başına verir. `Dockerfile.frontend.release` yalnız bu
paketleri kurar; özet tutmazsa derleme durur, paket yöneticisi imzayı doğrular ve hiçbir depoya
bakmaz. `connected` kipinde paket `ALPINE_PACKAGE_SOURCE` adresinden indirilir (banka yansısı bu
değişkenle verilir). `offline` kipinde indirme yapılmaz: paket, `alpine_packages` adlı derleme
bağlamında `<alpine-mimarisi>/<paket>-<sürüm>.apk` yolunda hazır bulunmalıdır, yoksa derleme durur.
Yerel Compose ters vekili ve isteğe bağlı `local-egress` geçidi aynı tabanı derlemeden çalıştırır;
ters vekil yalnız geri döngü adresinde dinler, geçit hiçbir port yayımlamaz.

Loki ve Tempo, yeniden başlatmalar arasında veriyi korurken kök olmayan kimlikte kalır. Adlandırılmış
birimleri `/loki` ve `/var/tempo` yollarına bağlanır; sabitlenmiş imajlar bu dizinlerin UID/GID 10001
sahibidir ve Docker'ın yeni birim kopyalaması, kök başlatıcı olmadan doğru sahibi korur. Her iki servis
kimliğini açıkça beyan eder, salt okunur kök dosya sistemi kullanır, bütün yetkinlikleri kaldırır,
`no-new-privileges` etkinleştirir; yalnız kabul edilmiş durum birimleri yazılabilirdir.

`scripts/stack.sh` kullanın; Compose proje adını ve dosya seçimini tutarlı tutar ve PostgreSQL, Redis
(yalnız `cache` profili açıkken kullanılır) ile arka uç imza anahtarının Git dışında üretilen yerel
sırlarını verir (`scripts/README.md`). Compose bu sırları `stack.sh` olmadan başlatıldığında açık
hatayla durur.

## SQL Server ve LLM'e yerel erişim (isteğe bağlı)

Arka uç varsayılan olarak hiçbir SQL Server'a ve LLM'e ulaşamaz
([Kubernetes teslim PRD'si](../../specs/application-foundation/PRDs/002-kubernetes-delivery/PRD.md)
Requirement 11, Decision 15). Git'in yok saydığı `app/infra/.env` dosyasına
`COMPOSE_PROFILES=local-egress` yazılınca `local-egress` geçidi başlar:

- Geçit, sabitlenmiş nginx imajıyla çalışan TCP aktarıcısıdır
  (`nginx/nginx.local-egress.conf`). Yalnız bu bilgisayarın 1433 (SQL Server), 11434 (Ollama) ve
  1234 (LM Studio) portlarına aktarır; başka port ve başka hedef yoktur.
- Arka uç yine yalnız iç ağlardadır. Geçit, yalnız arka uçla paylaştığı iç `host-gate` ağında
  `host.docker.internal` adıyla görünür; dışa çıkan `egress` köprüsüne yalnız geçit katılır. Ön yüz,
  veritabanı ve ters vekil geçide ulaşamaz.
- Geçit port yayımlamaz, salt okunur kök dosya sistemiyle, kök olmayan kullanıcıyla ve bütün Linux
  yetenekleri düşürülmüş çalışır; adı yalnız kendi `/etc/hosts` kaydından çözer.
- Profil kapalıyken `host.docker.internal` adı arka uçta çözülmez. Ayarı kapattıktan sonra
  **DWH: Uygulamayı başlat** görevi çalışan geçidi kaldırır; komut satırında aynı iş
  `scripts/stack.sh rm --stop --force local-egress` ile yapılır (Compose, profili kapatılan servisi
  `up` ile kendiliğinden durdurmaz).
- Uygulamanın LLM ağ politikası değişmez: geçidin adresi iç ağ adresi olduğu için kabul edilir.
- Yapısal denetim: `tests/infra/local-egress.test.sh`.

## Aynı projenin ikinci kopyası

Compose proje adı, yığının kapsayıcı, ağ, veri birimi ve derlenen imaj adlarının önüne gelir. Varsayılan
ad ürün kısa adıdır (`dwhcodereview`). Aynı bilgisayarda projenin ikinci bir kopyası (örneğin ikinci
bir Git çalışma ağacı) aynı adla çalışırsa, kendi yığınını kurmak yerine ilk kopyanın kapsayıcılarını
ve veritabanını kullanır. İkinci kopyaya ayrı bir yığın vermek için onun Git'in yok saydığı
`app/infra/.env` dosyasına farklı bir ad ve boş portlar yazın:

~~~sh
COMPOSE_PROJECT_NAME=dwhcodereview-2
APP_HTTP_PORT=8081
GRAFANA_PORT=3002
~~~

Kabuk ortamındaki `COMPOSE_PROJECT_NAME`, `app/infra/.env` içindekinin önüne geçer. Ad yalnız küçük
harf, rakam ve kısa çizgi içerebilir; kısa çizgiyle başlayamaz ve bitemez. Geçersiz bir ad verilirse
betik Docker'ı hiç çağırmadan açık bir iletiyle durur. `stack.sh` ve onu kullanan bütün betikler
(`db.sh`, `quality-gate.sh`, `export-openapi.sh`, `generate-types.sh`, `create-super-admin.sh`) ile
`compile-dependency-locks.sh` adı aynı yoldan, `scripts/compose-project.sh` ile çözer; bu yüzden hepsi
aynı yığında çalışır. Tarayıcı testleri ikinci kopyada `APP_E2E_BASE=http://localhost:8081` ile o
kopyanın portuna yönlendirilir. Yerel sırlar her kopyanın kendi `app/infra/.data/` dizininde durur.
