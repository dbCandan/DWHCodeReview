---
id: "45-dagitim-hedefi"
title: "Her değişikliği sıkılaştırılmış Kubernetes hedefine dağıtılabilir tut"
scope: deployment
authority: mandatory
priority: 45
trigger: path-match
applies_to:
  - "helm/**"
  - "app/infra/**"
  - ".github/workflows/**"
gate: "charts-render.yml"
application_modes:
  - separated-web
---

# Dağıtım hedefi

Her proje iskeleti, internet çıkışı olmayan yönetilen, üretim dışı `Kubernetes` kümesini hedefler.
DevOps standardı gereği tek uygulama `chart`'ı `helm/<ürün-kısa-adı>/` dizinindedir ve dağıtım giriş
noktası aynı dizindeki `deploy.sh` dosyasıdır. `chart` kendi kendine yeterlidir; arka uç ve ön yüz iş
yüklerini, projenin kabul edilmiş `PRD`'si bildirdiğinde ise bir PostgreSQL 17 `StatefulSet`'ini ve bir
Alembic şema geçişi `Job`'unu içerir. Önbellek, işleyici veya gözlemlenebilirlik iş yükü, alt `chart`,
bağımlılık arşivi veya çalışma zamanı indirmesi içermez. Ortama özgü bilgi yalnız aşağıdaki projeye ait
değer katmanıyla gelir. Proje, fabrikanın yönettiği dosyaları elle düzenlemeden ve dışarıdan ayar
veya `Secret` beklemeden üretim dışı hedefe dağıtılabilir.
Bu hedefi karşılayamayan değişiklik tamamlanmış değildir.

Oluşturulan her iş yükü şu kontrollerin tamamını karşılamalıdır:

- arka uç ve ön yüz imajı kanonik iç `GHCR` proxy-cache yolundan gelir; GitHub `main` yapısı tam 40
  karakter kaynak commit etiketini yayımlar ve Azure dağıtımı `latest` isteğini aynı
  `BUILD_SOURCEVERSION` etiketine çözer;
- `chart`, `Secret` yazmaz; değer dosyası ve proje katmanı gizli malzeme içermez; iş yükü `Secret`'a
  adıyla bağlanır;
- kapsayıcı açıkça kök olmayan kullanıcı/grupla çalışır, ayrıcalık yükseltmeyi kapatır, tüm
  `Linux` yeteneklerini düşürür, `RuntimeDefault` `seccomp` kullanır ve salt okunur kök dosya sistemine
  sahiptir;
- her yazılabilir yol, açıkça boyutu sınırlı bir birimdir;
- kabul edilmiş yetenek `Kubernetes` API erişimi gerektirmedikçe hizmet hesabı belirteci bağlama kapalıdır;
- tüm kapsayıcılar kaynak istek/sınırı bildirir; `HTTP` iş yükü başlatma/hazırlık/canlılık
  yoklaması içerir;
- her iş yükü giriş/çıkış `NetworkPolicy` kuralı içerir; boş eş kümesi izin vermez, reddeder;
- yönetilen test RKE2 hedefinde Ingress controller `kube-system` namespace'indedir; `nginx`
  IngressClass adı namespace adı değildir ve ağ politikası `ingress-nginx` varsayamaz;
- `Service`, `ClusterIP` tipindedir; iş yükü düğüm kapısı, yük dengeleyici veya küme kapsamlı nesne
  oluşturmaz;
- kalıcı birim istemi boyut bildirir; `Job`, `Always` dışı yeniden başlatma politikası kullanır.

Fabrikanın yönettiği kanonik `values.yaml` `backend` ve `frontend` bölümlerini, ayrıca varsayılanı
kapalı `postgres` ve `migration` bölümlerini taşır. `backend` ve `frontend` bölümleri
`cr-test.kuveytturk.com.tr/ghcr.io.vc/kt-vibecoding/<proje>-<bileşen>` yolunu ve `latest` varsayılanını
taşır; Azure çağrısında `deploy.sh` bu varsayılanı tam kaynak commit etiketiyle ezer. İstenirse açık
bir imaj özeti etikete üstün gelir. Backend ve frontend giriş politikaları kanonik RKE2 controller
namespace'i `kube-system` için doğru portu önceden taşır. Ortam bilgileri bu dosyada boş kalır ve
projeye ait iki dosyayla gelir. İskelet (`baslat`, `guncelle`) bu dosyaları oluşturmaz, güncellemez,
silmez ve yönetilen dosya listesine yazmaz:

- `helm/<ürün-kısa-adı>/values-project.yaml`: `deploy.sh` bu dosyayı render ve apply kiplerinde temel
  değer dosyasının üstüne katmanlar. Projenin ortam bilgisini taşır: ingress sınıfı, host ve TLS
  `Secret` adı; `backend.existingSecret` adı; backend çıkış eşleri; depolama sınıfı; `postgres` ve
  `migration` açma anahtarları; `backend.config` altında `<ENV_PREFIX>` önekli, gizli olmayan ayarlar.
  İki ayar isteğe bağlıdır; yazılmazsa render çıktısı değişmez. `backend.strategy` arka uç
  `Deployment`'ının güncelleme yöntemidir: yalnız `{type: RollingUpdate}` (isteğe bağlı `maxSurge` ve
  `maxUnavailable` tam sayı ya da yüzde olarak) veya `{type: Recreate}` kabul edilir; `Recreate`
  ile `rollingUpdate` birlikte reddedilir. Süren işin durumunu bellekte tutan arka uç `Recreate`
  seçer; güncellemede iki arka uç podu aynı anda çalışmaz. `frontend.ingress.annotations`, `chart`'ın
  ürettiği kimlik ek açıklamalarının (`annotation`) yanına giriş kapısı için gizli olmayan ayarlar
  ekler; örneğin `nginx.ingress.kubernetes.io/proxy-body-size: "20m"`. `scaffold.kt.internal/`,
  `helm.sh/` ve `meta.helm.sh/` önekli anahtarlar ile paylaşılan giriş kapısında yapılandırma
  çalıştıran `...snippet` anahtarları işlenmeden reddedilir.
  Çıkış eşi bir seçici ya da adıyla sınırlı `ipBlock` adres bloğudur; IPv4'te `/8`, IPv6'da `/32`
  değerinden geniş blok reddedilir. Gizli görünen anahtar (parola, belirteç, özel anahtar, bağlantı
  adresi gibi), PEM özel anahtarı veya kullanıcı adı ve parola içeren adres taşıyamaz.
  Kurum mail relay'i, Exchange ve LDAP adresleri bu dosyada da tutulmaz: proje yalnız
  `backend.corporateEnvironment.sections` listesine `mail`, `exchange` veya `ldap` yazar.
  `chart` istenen bir bölüm çözülmeden render etmez; `deploy.sh` render ve apply kiplerinde bölümleri
  dağıtım anında `KT_CORPORATE_ENVIRONMENT_URL` (`https://`) adresinden, fabrikanın MCP sunucusunun
  barındırdığı kurum ortamından geçici bir değer katmanı olarak alır: önekli `backend.config`
  anahtarları ve `backend.networkPolicy.corporateEgress` çıkış eşleri. Katman diskte kalmaz; adres
  yoksa veya alınamazsa dağıtım değişiklik yapmadan durur. Proje katmanı `resolved` ve
  `corporateEgress` değerlerini yazamaz.
- `helm/<ürün-kısa-adı>/deploy-hooks.sh`: yalnız apply kipinde, imaj yayın denetimi, namespace
  oluşturma ve `ailab-tls` kopyasından sonra; veritabanı `Secret`'larından, beklemedeki release
  işleminden ve her Helm değişikliğinden önce `bash` ile çalışır. `KT_DEPLOY_RELEASE`,
  `KT_DEPLOY_NAMESPACE`, `KT_DEPLOY_CHART_DIR`, `KT_DEPLOY_IMAGE_TAG` ve `KT_DEPLOY_DATABASE_ENABLED`
  değişkenlerini alır. İşi projeye özgü `Secret` hazırlığıdır: örneğin imza anahtarını bir kez üretip
  sonraki koşularda kümedekini yeniden kullanmak veya isteğe bağlı dış kimlik bilgilerini çalışma
  zamanı `Secret`'ına eşlemek. Gizli değeri yazdırmaz. Sıfır dışı çıkış, dağıtımı Helm değişikliği
  yapmadan durdurur.

`scripts/render-charts.sh`, sentetik değerlerle yapısal sözleşmeyi hem veritabanı ve geçiş kapalıyken
hem açıkken kanıtlar. Proje katmanı varsa temel değerleri ve katmanı `deploy.sh`'in varsayılan release
ve namespace adıyla aynı yapısal denetimlerden geçirir; gizli malzemeyi ve geçersiz yapıyı reddeder.
Kanca varsa sözdizimini `bash -n` ile denetler. `chart` da `backend.config` içinde öneksiz veya gizli
görünen anahtarı, geçersiz `backend.strategy` değerini ve izin verilmeyen ingress ek açıklamasını
işlemeden reddeder.

`postgres.enabled` açıldığında veritabanı iş yükü yukarıdaki kontrollere ek olarak şunları karşılar:

- tek kopya `StatefulSet`'tir ve bileşen etiketi `database`'dir; imaj, yerel Compose'daki PostgreSQL 17
  imajıyla aynı `sha256` özetiyle sabitlenir, özet boşsa işleme durur; ortam depo yolunu özet
  değişmeden kurum içi aynaya çevirebilir;
- `postgres.enabled` yalnız `migration.enabled` ile birlikte açılır; çalışma zamanı rolünü geçiş
  oluşturur;
- veri, boyutu ve depolama sınıfı adı açıkça yazılmış `ReadWriteOnce` kalıcı birim istemindedir;
  depolama sınıfı proje katmanından gelir ve boşsa işleme durur;
- kapsayıcı `999` kullanıcı/grubuyla kök olmadan çalışır; `/var/run/postgresql` ve `/tmp` boyutu
  sınırlı birimlerdir; veri sağlama toplamı (`--data-checksums`) açıktır; kapanışa 60 saniye tanınır;
- kimlik bilgileri yalnız `<release>-postgres` `Secret`'ından `envFrom` ile gelir;
  başlatma/hazırlık/canlılık yoklamaları yapılandırılmış kullanıcıyla gerçek `SELECT 1` sorgusu
  çalıştırır;
- `NetworkPolicy` girişi yalnız aynı sürümün backend ve geçiş podlarından veritabanı portuna açar;
  çıkış listesi boştur, yani her çıkış reddedilir.

`migration.enabled` yalnız `postgres.enabled` ile birlikte açılır; aksi hâlde işleme durur. Geçiş
`Job`'u şu sözleşmeyi karşılar:

- backend imaj kimliğiyle `alembic upgrade head` çalıştırır; ayrı geçiş imajı yoktur;
- yeniden başlatma politikası `Never`, `backoffLimit` değeri `0`'dır ve `activeDeadlineSeconds` süre
  sınırı vardır; başarısız geçiş yeniden denenmez, incelenir;
- bağlantısını yalnız `<release>-migration` `Secret`'ından `envFrom` ile alır; backend bu `Secret`'ı
  görmez;
- Alembic'ten önce veritabanı imajıyla çalışan ikinci hazırlık kapsayıcısı, şema sahibi olarak
  çalışma zamanı rolünü oluşturur veya günceller. Rol süper kullanıcı değildir; veritabanı veya rol
  oluşturamaz; `public` şemasında yalnız `SELECT`, `INSERT`, `UPDATE`, `DELETE` ve dizi kullanımı
  yetkisi alır. Varsayılan yetkiler Alembic'in sonradan oluşturduğu tablolara da uzanır. Oturum,
  ifadelerini sunucu günlüğüne yazdırmaz;
- `NetworkPolicy` girişi kapatır; çıkışı yalnız küme DNS'ine ve veritabanı portuna açar;
- kimlik bilgisi taşımayan bekleme kapsayıcısı, veritabanı `Service`'i bağlantı kabul edene kadar
  bekler; `Service` bağlantıyı yalnız `SELECT 1` hazırlık yoklaması geçtikten sonra kabul eder;
- çalışma sırası geçişin daha önce çalışıp çalışmadığına göre seçilir: önceki bir sürümün oluşturduğu
  geçiş `NetworkPolicy`'si yoksa (ilk kurulum ya da veritabanını ilk kez ekleyen güncelleme) `Job`
  veritabanıyla aynı anda oluşturulan sıradan sürüm kaynağıdır; varsa `Job` yeni backend
  podlarından önce çalışan `pre-upgrade` Helm kancasıdır (`hook`). Geçiş hiçbir durumda backend'in
  hazır olmasını beklemez; dağıtım bu yüzden kilitlenmez;
- backend hazır olma yoklaması, çalışma zamanı rolü veritabanına bağlanana ve veritabanındaki
  Alembic sürümü imajın taşıdığı son geçişe (`head`) ulaşana kadar hata metni içermeyen sabit
  gövdeli `503` döner. İlk kurulumda rol ve şema oluşurken pod trafik almaz; reddedilen giriş
  süreci durdurmaz ve günlüğe hata izi yerine sıklığı sınırlı, gizli değer taşımayan bir olay
  düşer. Şemanın güncel olduğu bir kez doğrulanınca sonraki yoklamalar yalnız bağlantıyı dener.
  İmajın tanımadığı daha yeni bir sürüm hazır sayılır; böylece geri alınan önceki sürüm yeni
  şemada çalışır;
- `deploy.sh` Helm'i `--atomic --wait --wait-for-jobs` ile çalıştırır; başarısız geçiş sürümü
  başarısız kılar ve önceki sürüm korunur. Geri almada şema geri indirilmez; geçişler eski sürümün
  çalışabileceği biçimde genişletici yazılır.

Oluşturulan `.github/workflows/image-build.yml`, backend ve frontend imajlarını `main` üzerinde
`latest`, UTC tarih, kısa SHA ve tam SHA etiketleriyle `ghcr.io`'ya yayımlar.
`helm/<ürün-kısa-adı>/deploy.sh`, mevcut Azure `KUBECONFIG` bağını kullanarak Helm'i doğrudan
çalıştırır. Bu teslim hattı ikinci bir yayın
makbuzu, yeniden inceleme veya ayrı audit hunisi gerektirmez. Apply yolu kümede değişiklik yapmadan önce
render edilen her imajın registry'de yayımlandığını sorar ve geç yayını bekler; imaj yayımlanmamışsa
namespace, `Secret` veya Helm değişikliği yapmadan durur. Registry yanıt vermezse bunu belirtir ve
Helm'in hazır podu koruyan rollout güvencesiyle devam eder.
Apply yolu yeni namespace'te eksik olan paylaşılan `ailab-tls` Secret'ını mevcut `kt-verim`
namespace'inden runner kimliğiyle kopyalar; değerleri Git'e, Helm argümanına veya loga yazmaz.
Render edilen `chart` veritabanını içeriyorsa apply yolu kancadan sonra ve Helm'den önce üç `Secret`
hazırlar:

- `<release>-postgres`: şema sahibinin `POSTGRES_USER` ve `POSTGRES_PASSWORD` değerleri;
- `<release>-migration`: şema sahibinin `<ENV_PREFIX>DATABASE_URL`, `PGHOST`, `PGPORT`,
  `PGDATABASE`, `PGUSER` ve `PGPASSWORD` değerleri ile çalışma zamanı rolünün
  `RUNTIME_DATABASE_USER` ve `RUNTIME_DATABASE_PASSWORD` değerleri;
- `<release>-database`: çalışma zamanı rolünün `<ENV_PREFIX>DATABASE_URL` değeri. Backend bu
  `Secret`'ı, proje `Secret`'ından sonra `envFrom` ile okur.

Parolalar ilk koşuda rastgele üretilir; sonraki koşularda kümedeki değer okunup yeniden kullanılır.
Kancanın önceden hazırladığı değer de korunur; yalnız adres, render edilen `chart`'tan yeniden
türetilir. Mevcut `Secret` okunamazsa hiçbir şeyi değiştirmeden durur. Değerler `kubectl`'e yalnız
sahibine özel geçici dosyalardan geçer; Git'e, değer dosyasına, komut argümanına veya loga yazılmaz.
Beklemedeki (`pending-*`) Helm release için önce çalışan işlemin bitmesi beklenir. Yarım kalmış
`pending-upgrade` veya `pending-rollback` son release'e geri alınır; geri alma başarısızsa upgrade
yapılmaz. Hizmet vermiş release kaldırılmaz; yalnız hiç kurulmamış `pending-install` kaldırılır.

Çalışma zamanı veritabanı rolü yalnız `DML` yetkilidir; şemayı yalnız geçiş `Job`'unun `Secret`'ındaki
bağlantı değiştirir. Yayımlanmış `chart` sürümleri değişmezdir. Oluşturma ve hazırlık denetimi
doğrulamadır; dağıtım yetkisi değildir.
