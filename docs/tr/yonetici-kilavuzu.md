# Yönetici kılavuzu

Bu kılavuz iki kişi içindir:

- **Süper yönetici (uygulama yöneticisi):** İnceleme kurallarını ve gruplarını düzenler ve yayımlar,
  yapay zekâ çağrılarını izler, hesapları kapatır; test ortamında SQL Server
  bağlantısını girer. Uygulamada başka yetkili rol yoktur; diğer herkes **Kullanıcı**dır.
- **Dağıtımı yöneten ekip:** Test ortamına (nonprod: ekibin ortak kullandığı, kurum sunucularında
  çalışan sürüm) kurulumu yapan Azure DevOps işini (kodu sunucuya kuran kurum aracı) ve gizli
  değerleri yönetir. Bu ekip uygulama içinde bir rol değildir.

Günlük kullanım [kullanım kılavuzunda](kullanim-kilavuzu.md), kendi bilgisayarında çalıştırma
[yerel kurulum kılavuzunda](yerel-kurulum.md) anlatılır.

## Süper yönetici hesabı

Süper yönetici kurum hesabı değil, uygulamanın kendi (yerel) hesabıdır. Kurum dizini (kurumun
kullanıcı hesaplarını tutan sistem, Active Directory) çalışmasa da bu hesapla girilebilir.

### Test ortamında: `admin`

- Test ortamında `admin` adlı süper yönetici hesabını, kurulumdan sonra uygulamanın kendisi **bir kez**
  açar. İlk parolasını proje sahibi seçer ve yalnız Azure DevOps'taki gizli değişken
  `DWHCODEREVIEW_ADMIN_PASSWORD` ile verir (nasıl ekleneceği aşağıda
  [Azure'a gizli değişken eklemek](#azurea-gizli-değişken-eklemek) bölümündedir).
- Parola kuralı: en az 15 karakter; yaygın bir parola olamaz; hesap adını (`admin`) içeremez. Kurala
  uymayan parolayla hesap açılmaz, uygulama yine çalışır.
- Hesap bir kez açıldıktan sonra sonraki kurulumlar ona dokunmaz: gizli değişkeni değiştirmek var olan
  hesabın parolasını değiştirmez.
- Uygulamada parola değiştirme ekranı yoktur. Parolayı sıfırlamak için dağıtımı yöneten ekip, çalışan
  arka uçta (uygulamanın sunucu tarafı) `python -m app.scripts.create_super_admin --password-stdin`
  komutunu çalıştırır.
- Parola kaybolursa rol yönetimi durur. Parolayı güvenli bir parola kasasında saklayın.
- Test ortamında yerel parolayla yalnız süper yönetici girebilir; diğer herkes kurum hesabıyla girer.

Hesabın açıldığını günlükten doğrulayabilirsiniz (günlükler aşağıda anlatılır):
`auth.super_admin.bootstrap` olayı ilk kurulumda `created`, sonrakilerde `exists` yazar. `rejected`
parolanın kurala uymadığını, `not_configured` gizli değişkenin arka uca ulaşmadığını gösterir.

### Yerelde

Yerelde süper yöneticiyi siz açarsınız: VS Code'da **DWH: Yerel süper yönetici aç** görevini
çalıştırın ([yerel kurulum](yerel-kurulum.md#hesap-açmak)). Görev önce kullanıcı adını, sonra parolayı
sorar. Aynı adla yeniden çalıştırmak parolayı sıfırlar.

Kaynak: [dizin girişi PRD'si](../../specs/application-foundation/PRDs/001-directory-login/PRD.md),
Requirement 14 ve Decision 13 (PRD: bir özelliğin ne yapacağını ve nasıl kabul edileceğini yazan
belge).

## Kullanıcıları yönetmek

Süper yönetici menüde **Yönetim → Kullanıcılar** sayfasını görür.

- Kurum hesabıyla ilk kez giren herkes kendiliğinden **Kullanıcı** olur; kaydı ilk girişten sonra
  listede görünür. Seçilecek başka rol yoktur.
- **Kullanıcı ara** alanına `ad.soyad` yazıp arayın. Tabloda kullanıcı adı, görünen ad, hesap türü
  (**Kurum dizini** ya da **Yerel**), rol, durum ve son giriş zamanı vardır.
- **Pasifleştir** hesabı kapatır; kişi doğru parolayla da giremez. **Etkinleştir** yeniden açar.
- Durumu değişen kişinin açık oturumları kapatılır; en geç 15 dakika içinde yeniden giriş
  ister.
- Her rol ve durum değişikliği (kim, kimi, eski ve yeni değer, zaman) veritabanındaki kalıcı bir
  değişiklik kaydına yazılır.
- Süper yönetici hesabının rolü ve durumu bu sayfadan değiştirilemez; kendi hesabınızı da
  pasifleştiremezsiniz.
- Kurumda kapatılan bir hesabın açık oturumu en geç 8 saatte kendiliğinden biter. Daha erken kapatmak
  için hesabı burada pasifleştirin.
- "Bu hesap başka bir kullanıcı kaydıyla çakışıyor" iletisi, aynı e-postayla yerel bir hesap
  bulunduğunu gösterir. Bu çakışmayı dağıtımı yöneten ekip veritabanında elle çözer.

Bugün kurum dizininde hesabı olan herkes girebilir ve Kullanıcı olur. Girişi belirli bir kurum
grubuyla sınırlamak açık bir iştir (dizin girişi PRD'sindeki Task 14).

## Kuralları düzenlemek ve yayımlamak

Süper yönetici menüde **Yönetim → Kurallar** sekmesini görür. Kural ve grup değişikliklerini yalnız
süper yönetici yapar; kullanıcıların öneri gönderdiği bir onay akışı yoktur. **Yönetim → Genel durum**
kuralların son sürümünü, SQL Server, LLM ve e-posta durumunu tek bakışta gösterir.

- Kuralların bir **taslağı** ve numaralı **yayımlanmış sürümleri** vardır. İncelemeler yalnız en son
  yayımlanmış sürümü kullanır; taslaktaki değişiklik **Yayınla**'ya basılana kadar hiçbir incelemeyi
  etkilemez.
- Sayfa başlığında "Son yayın: sürüm N · tarih · yayımlayan" yazar. Taslak son sürümden farklıysa
  "Taslakta yayımlanmamış değişiklik var" rozeti görünür. İlk sürüm eski uygulamadan içe aktarılmıştır;
  yayımlayan olarak "içe aktarım" yazar.
- Kurallar iki sütundadır: **Kritik (HIGH)** ve **Normal (LOW / MEDIUM)**. Kural bir gruptan ötekine
  taşınamaz; gerekirse silip öteki grupta yeniden ekleyin.
- **+ Kural** yeni kural ekler. Kimlik kendiliğinden verilir (`Kural12` gibi); bir kez kullanılmış
  kimlik silinse de başka kurala verilmez.
- Kural satırına tıklayınca metin kutusu açılır. Bir kural metni en çok 8.000 karakter, taslak en çok
  200 kural olabilir. Boş bırakılan kural kaydederken atılır.
- **Nesne meta verisi gerekir** kutusu işaretliyse, veritabanından okunan nesnelerin incelemesinde o
  kurala nesnenin kullandığı diğer nesnelerin ve sütunların özeti de gönderilir.
- ↑ ve ↓ düğmeleri kuralı grup içinde taşır; sıra modele giden sıradır. **Sil** kuralı taslaktan
  çıkarır, **Daralt** satırı kapatır. **Kural ara** kimlik ya da metinle arar.
- **Taslağı kaydet** taslağı saklar; kaydedilmemiş değişiklik varsa **Kaydedilmedi** rozeti görünür.
- **Yayınla**, kaydedilmemiş değişikliği önce kaydeder, sonra taslağı yeni ve değiştirilemez bir sürüm
  olarak yayımlar: "Sürüm N yayımlandı. Bundan sonra başlayan incelemeler bu sürümü kullanır." Taslak
  son sürümle aynıysa yeni sürüm oluşmaz. Hiç kural içermeyen taslak yayımlanamaz.
- Sürmekte olan inceleme, başladığı andaki sürümle biter; sırada yayımlanan sürüm onu etkilemez.
- Aynı anda iki kişi düzenlerse ikinci kaydeden "Kurallar başka biri tarafından değiştirildi; sayfayı
  yenileyin." iletisini alır. **Sayfayı yenile** ile güncel taslağı açıp değişikliğinizi yeniden yapın.
- Eski bir sürümü taslağa geri yükleme özelliği yoktur. Eski sürümleri **Yayımlanmış kurallar**
  sayfasında okuyabilirsiniz.

Kural metni modele olduğu gibi gider. Metne modeli yönlendiren ifadeler yazmak süper yöneticinin
sorumluluğundadır.

Kaynak: [kural yönetimi PRD'si](../../specs/sql-review/PRDs/001-rule-management/PRD.md).

## Yapay zekâ çağrılarını izlemek

**Yönetim → LLM çağrıları** sayfası, yapay zekâ modeline (LLM) yapılan her çağrının özetini listeler:
başlangıç zamanı, nesne veya etiket, kural, model, sonuç, süre ve üretilen metin miktarı. **Son 100**,
**Son 250** veya **Son 500** kaydı seçebilirsiniz; satırdaki düğme ayrıntıyı açar.

- Sonuçlar: Başarılı, Zaman aşımı, Bağlanamadı, Güvenli bağlantı hatası, Ağ politikası reddetti, Sunucu
  hata kodu, Geçersiz yanıt, Yanıt çok büyük, İptal edildi.
- Özetler 90 gün saklanır, sonra kendiliğinden silinir; elle silme yoktur.
- Özetlerde modele giden metin, SQL ve model yanıtı yoktur.
- Nesne adlarını gösterdiği için bu sayfa inceleyicilere kapalıdır.

Kaynak: [LLM bağlantısı PRD'si](../../specs/sql-review/PRDs/006-llm-connection/PRD.md).

## SQL Server ve LLM ayarları

### Yerelde: ekrandan

Yerelde süper yönetici menüde **SQL bağlantısı** ve **LLM bağlantısı** sayfalarını görür.

- **SQL bağlantısı:** Sunucu adı, port (bağlantı kapı numarası), kullanıcı adı, parola, **Şifreli bağlantı (Encrypt)** ve
  **Sunucu sertifikasına doğrulamadan güven (TrustServerCertificate)** alanları vardır. **Bağlantıyı
  test et** kaydetmeden dener ve bulunan veritabanlarından ilk 8'ini gösterir. **Kaydet** ve **Yenile**
  düğmeleri de vardır. Parola kutusu boş bırakılırsa kayıtlı parola korunur; sunucu, port veya kullanıcı
  değiştiyse kayıtlı parola yeni sunucuya gönderilmez, parolayı yeniden yazmanız gerekir.
- **LLM bağlantısı:** İstek biçimi (**OpenAI uyumlu** ya da LM Studio tarzı **POST /api/v1/chat**),
  temel adres, isteğe bağlı sohbet adresi, model ve isteğe bağlı API anahtarı (modelin istediği erişim anahtarı) alanları vardır. Adres
  kurum içi (özel) ağda değilse kayıt reddedilir.
- Ekrandan girilen değerler yalnız çalışan uygulamaya uygulanır ve hiçbir dosyaya yazılmaz. Uygulama
  yeniden başlayınca `app/infra/.env` dosyasındaki değerlere dönülür. Kalıcı ayar için
  [yerel kurulum kılavuzuna](yerel-kurulum.md#sql-server-ve-yapay-zekâ-modeline-bağlanmak) bakın.
- Yerel uygulama bilgisayarınızdaki SQL Server'a ve modele yalnız bu erişimi açtıysanız ulaşır;
  açılışı [yerel kurulum kılavuzunda](yerel-kurulum.md#erişimi-açmak) anlatılır. Erişim kapalıyken
  bağlantı testi "SQL Server'a ulaşılamadı." der ve LLM sayfası `host.docker.internal` adresini
  kaydetmez.

### Test ortamında

**LLM bağlantısı** sayfası test ortamında menüde görünmez; adresle açılırsa "Bu ortamda bağlantı
ayarları dağıtımla yönetilir." yazar. Yapay zekâ modelinin adresi ve model adı depodaki
`helm/dwhcodereview/values-project.yaml` dosyasında hazırdır ve yalnız kurulumla değişir. Bugünkü uç
anahtar istemez.

**SQL bağlantısı** sayfasını test ortamında yalnız süper yönetici görür ve kullanır:

1. `admin` hesabıyla girin ve menüden **Yönetim → SQL bağlantısı** sayfasını açın.
2. Sunucu adını, portu (bağlantı kapı numarası), okuma hesabının kullanıcı adını ve parolasını yazın.
3. **Bağlantıyı test et** düğmesine basın. Test hiçbir şeyi kaydetmez; bağlantı kurulursa hesabın
   erişebildiği veritabanlarının sayısını ve ilk 8 adını gösterir.
4. **Kaydet** düğmesine basın. Bağlantı hemen kullanılır; uygulamayı yeniden başlatmak gerekmez.

Bilmeniz gerekenler:

- Değerler uygulamanın kendi veritabanına kaydedilir. Parola şifrelenerek saklanır ve ekranda bir
  daha gösterilmez; sayfada yalnız "Kayıtlı parola var." yazar.
- Parola kutusunu boş bırakırsanız kayıtlı parola korunur. Sunucu, port veya kullanıcı değiştiyse
  test için parolayı yeniden yazmanız gerekir; kayıtlı parola başka bir sunucuya gönderilmez.
- **Kayıtlı parolayı kaldır** seçilip kaydedilirse bağlantı kapanır ve kullanıcılar "SQL Server
  bağlantısı yapılandırılmamış." iletisini görür.
- İncelemeye açılacak veritabanları ayrıca seçilmez. **Nesne incelemesi** ekranında okuma hesabının
  erişebildiği bütün veritabanları listelenir; yalnız SQL Server'ın kendi sistem veritabanları
  (`master`, `tempdb`, `model`, `msdb`) listelenmez. Kullanıcıların neyi okuyup yapay zekâ modeline
  gönderebileceğini yalnız bu hesabın SQL Server'daki yetkileri belirler; bir veritabanının
  incelenmesini istemiyorsanız hesabın o veritabanındaki yetkisini SQL Server'da kaldırtın.
- Test ortamında bağlantı her zaman şifrelidir; bu ayar ekranda yoktur ve değiştirilemez.
- Uygulama olağan durumda sunucunun sertifikasını (sunucunun kimliğini kanıtlayan belge) doğrular.
  Sertifika kurumun sertifika otoritesiyle imzalı değilse test "SQL Server ile güvenli bağlantı
  kurulamadı." der. Bu durumda **Sunucu sertifikasına doğrulamadan güven (TrustServerCertificate)**
  kutusunu işaretleyip yeniden test edin ve kaydedin. Kutu işaretliyken bağlantı yine şifrelidir,
  ancak sunucunun kimliği doğrulanmaz; ağdaki biri kendini bu sunucu gibi gösterebilir. Bu seçenek
  geçicidir: veri ambarı sunucusunun (PASIFIK) sertifikası kendinden imzalı olduğu için proje sahibi
  2026-12-31'e kadar izin vermiştir. Veritabanı ekibi sunucuya kurum imzalı sertifika kurunca kutuyu
  kaldırıp yeniden kaydedin.
- Uygulama SQL Server'a yalnız kurulumun izin verdiği adres aralığından ve 1433 numaralı porttan
  ulaşabilir. Aralık `helm/dwhcodereview/values-project.yaml` dosyasındadır; sunucu bu aralığın
  dışındaysa ya da başka bir port kullanıyorsa test "SQL Server'a ulaşılamadı." der ve aralığın
  kurulumla değiştirilmesi gerekir.
- Kullanıcılar bu sayfayı görmez; adresle açan kullanıcı erişim yetkisi olmadığını görür.
- Kimin ne zaman kaydettiği veritabanında tutulur; günlüğe (log: uygulamanın yaptığı işleri satır
  satır yazdığı kayıt) yalnız hangi alanların değiştiği yazılır, değerler yazılmaz.

Kurulumu yöneten ekip isterse bağlantıyı kurulumla da verebilir: okuma hesabı Azure'a `MSSQL_USER` ve
`MSSQL_PASSWORD` gizli değişkenleri olarak, sunucu adı ve port
`helm/dwhcodereview/values-project.yaml` dosyasına eklenir. Sunucu, kullanıcı ve parolanın üçü de
kurulumla verildiğinde kurulumdaki değerler geçerli olur, **SQL bağlantısı** sayfası süper yönetici
için de kapanır ve "Bu ortamda bağlantı ayarları dağıtımla yönetilir." yazar. Bu durumda da
bağlantı şifreli olmalıdır; şifreleme kapatılırsa uygulama açılmaz ve kurulum kendiliğinden önceki
sürüme döner. Sertifika doğrulaması aynı geçici izinle
`DWHCODEREVIEW_MSSQL_TRUST_SERVER_CERTIFICATE: true` satırıyla kapatılabilir.

Kaynak: [SQL Server bağlantısı PRD'si](../../specs/sql-review/PRDs/002-sql-server-connection/PRD.md),
[LLM bağlantısı PRD'si](../../specs/sql-review/PRDs/006-llm-connection/PRD.md).

## İsteğe bağlı Azure gizli değişkenleri

Test ortamı kurulumu hiçbir ayar veya gizli değer verilmeden çalışır. Aşağıdaki değişkenler yalnız
gerektiğinde eklenir. Kurulum sırasında `helm/dwhcodereview/deploy-hooks.sh` bunları kümedeki
(test ortamını çalıştıran kurum sunucu grubu) `dwhcodereview-runtime` gizli kaydına (Kubernetes
Secret) yazar.

| Azure değişkeni | Ne işe yarar | Verilmezse |
|---|---|---|
| `DWHCODEREVIEW_ADMIN_PASSWORD` | `admin` süper yöneticisinin ilk parolası | Süper yönetici açılmaz |
| `MSSQL_USER` | SQL Server okuma hesabının kullanıcı adı | Bağlantıyı süper yönetici uygulamadan girer |
| `MSSQL_PASSWORD` | SQL Server okuma hesabının parolası | Bağlantıyı süper yönetici uygulamadan girer |
| `SETTINGS_ENCRYPTION_KEY` | Uygulamaya kaydedilen SQL Server parolasını şifreleyen anahtar (rastgele 32 baytın base64 yazımı) | İlk kurulumda bir kez üretilir ve korunur |
| `LLM_API_KEY` | Anahtar isteyen bir model ucu için anahtar | Yazılmaz; bugünkü uç anahtar istemez |
| `JWT_PRIVATE_KEY` | Oturumları imzalayan anahtar (P-256 biçiminde) | İlk kurulumda bir kez üretilir ve korunur |

Kurallar:

- Değişken boşsa, hiç tanımlanmamışsa ya da Azure onu çözemeyip `$(DEĞİŞKEN)` metni olarak
  gönderirse "verilmedi" sayılır; kümedeki eski değer korunur.
- Bir değer değişince uygulamanın sunucu tarafı (arka uç) kendiliğinden yeniden başlatılır.
- `JWT_PRIVATE_KEY` değiştirmek herkesin oturumunu kapatır.
- `SETTINGS_ENCRYPTION_KEY` değişirse ya da kümedeki gizli kayıt silinirse uygulamaya kaydedilmiş SQL
  Server parolası açılamaz. Bağlantı "yapılandırılmamış" olur; süper yönetici **SQL bağlantısı**
  sayfasında parolayı yeniden yazıp kaydeder. Bu değişkeni vermeniz gerekmez.
- Değerler hiçbir zaman depoya, değer dosyalarına, komut satırına veya günlüğe yazılmaz. Günlükte
  yalnız anahtarın adı görünür.
- Eski uygulamadan kalan `API_ACCESS_TOKEN`, `API_ADMIN_TOKEN` ve `MSSQL_CONNECTION_STRING`
  değişkenleri artık okunmaz; Azure'dan elle silinebilir.

Kaynak: [Kubernetes dağıtımı PRD'si](../../specs/application-foundation/PRDs/002-kubernetes-delivery/PRD.md),
Requirement 5.

## Azure'a gizli değişken eklemek

Gizli değeri **yalnız Azure DevOps ekranına** yazın. Depoya, bir dosyaya, sohbete, iş kaydına veya
e-postaya yazmayın; kodlama asistanına da vermeyin.

**1. Değişkeni ekleyin.**

1. Azure DevOps'ta projeyi açın, **Pipelines** bölümünde DWH Code Review'u kuran işi bulun ve
   **Edit** deyin.
2. **Variables** düğmesine (ya da sekmesine) basın, **New variable** (ya da **+ Add**) seçin.
3. **Name** alanına değişken adını birebir yazın, örneğin `DWHCODEREVIEW_ADMIN_PASSWORD`.
4. **Value** alanına değeri yazın.
5. **Keep this value secret** kutusunu işaretleyin (eski görünümde değerin yanındaki kilit simgesi).
   Gizli işaretli değer bir daha ekranda gösterilmez ve iş günlüğünde `***` olarak görünür.
6. **Save** ile kaydedin.

**2. Değişkeni kurulum adımına bağlayın.** Azure, gizli değişkenleri kurulum betiğine kendiliğinden
geçirmez. Her gizli değişken, `helm/dwhcodereview/deploy.sh` komutunu çalıştıran adıma aynı adla
bağlanmalıdır:

- İş ekranda düzenleniyorsa: bu adımı (komut çalıştıran Bash görevi) açın, **Environment Variables** bölümünde **+**
  ile yeni satır ekleyin. Ad: `DWHCODEREVIEW_ADMIN_PASSWORD`, değer:
  `$(DWHCODEREVIEW_ADMIN_PASSWORD)`.
- İş bir YAML dosyasıyla (işin adımlarını yazan ayar dosyası) tanımlıysa: aynı adımın `env:` bölümüne şu satır eklenir. Satırda değer
  değil, yalnız değişkenin adı durur:

  ```yaml
  env:
    DWHCODEREVIEW_ADMIN_PASSWORD: $(DWHCODEREVIEW_ADMIN_PASSWORD)
  ```

**3. Kurulumu çalıştırın ve denetleyin.** Ana koda (`main` dalı) her birleştirme kurulumu kendiliğinden başlatır;
beklemek istemezseniz işi **Run pipeline** ile elle başlatın. İş günlüğünde şunlara bakın:

- `[RUNTIME] DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_PASSWORD set from DWHCODEREVIEW_ADMIN_PASSWORD`:
  değer ulaştı.
- `[RUNTIME] DWHCODEREVIEW_BOOTSTRAP_SUPER_ADMIN_PASSWORD not provided`: değişken tanımlı değil ya da
  adıma bağlanmamış. 2. adımı denetleyin.

Aynı adımlar `MSSQL_USER`, `MSSQL_PASSWORD`, `LLM_API_KEY`, `JWT_PRIVATE_KEY` ve
`SETTINGS_ENCRYPTION_KEY` için de geçerlidir.

## Günlükler ve izleme verileri

Günlük (log), uygulamanın yaptığı işleri satır satır yazdığı kayıttır.

### Test ortamında

- **Kurulum günlüğü:** Azure DevOps'taki iş koşumunun günlüğüdür. Satırlar yaptıkları işe göre
  `[IMAGE]`, `[HOOK]`, `[RUNTIME]`, `[DATABASE]` ve `[RELEASE]` ile başlar.
- **Uygulama günlüğü:** Sunucu tarafının (arka uç) ve veritabanının günlükleri, kümede
  `dwhcodereview` adlı alanda (namespace) çalışan kapsayıcıların (uygulamanın çalıştığı ayrı kutular)
  günlüğündedir; kümeye erişimi olan ekip okur. Günlüklerin kümede ne kadar kaldığı güvence altında
  değildir; bu yüzden rol değişiklikleri ayrıca veritabanında kalıcı saklanır.
- **İzleme verileri (ölçüm ve iz):** Test ortamında hiçbir yere gönderilmez; kümede bunları toplayan bir
  sistem yoktur.

### Yerelde

- Uygulamanın sunucu tarafının (arka uç) günlüğünü VS Code'daki **DWH: Arka uç günlüğünü izle**
  göreviyle görürsünüz.
- Ölçümler ve izler bilgisayarınızdaki izleme panosuna (Grafana) gider: `http://localhost:3001`.
  Kullanıcı adı `admin`, parola `app/infra/.env` dosyasındaki `GRAFANA_ADMIN_PASSWORD` değeridir.
  Ölçümler 15 gün, izler 14 gün saklanır.

### Günlüğe hiç yazılmayanlar

İncelenen SQL metni, kod parçaları, kural metni, model yanıtı, parolalar ve oturum anahtarları hiçbir
günlüğe, ölçüme veya ize yazılmaz. Başarısız girişte kullanıcı adı yerine onun tek yönlü özeti yazılır.

### İşe yarayan günlük olayları

| Olay | Ne zaman |
|---|---|
| `auth.login.succeeded` / `auth.login.failed` | Başarılı ya da başarısız giriş |
| `auth.directory.unavailable` | Kurum dizinine ulaşılamadı |
| `admin.user.role_changed` / `admin.user.active_changed` | Rol ya da hesap durumu değişti |
| `auth.super_admin.bootstrap` | Süper yönetici açılışının sonucu |
| `rule_set.version_published` | Yeni kural sürümü yayımlandı |
| `sql_server.call` | SQL Server çağrısı ve sonucu |
| `sql_connection.updated` | SQL Server bağlantısı kaydedildi (değişen alanların adı, sertifika doğrulamasının kapalı olup olmadığı ve kaydeden kullanıcı) |
| `sql_connection.stored_unusable` | Kaydedilmiş SQL Server bağlantısı kullanılamıyor (parola açılamadı) |
| `llm.call` | Yapay zekâ modeli çağrısı ve sonucu |
| `review_history.retention_run` | 90 günlük saklama süresi dolan incelemeler silindi |

## Saklama süreleri

| Veri | Süre |
|---|---|
| İncelemeler, sonuçlar, işaretler ve incelenen SQL metni | Bitişten 90 gün sonra silinir. Süre `DWHCODEREVIEW_REVIEW_HISTORY_RETENTION_DAYS` ayarıyla 1–365 gün arasında değiştirilebilir. |
| Yapay zekâ çağrı özetleri | 90 gün |
| Rol ve hesap durumu değişiklik kayıtları | Kalıcı |

Uygulamanın veritabanının yedeği alınmaz; proje sahibi bu riski kabul etmiştir. Veritabanı diski
bozulursa kurallar, geçmiş ve kaydedilmiş SQL Server bağlantısı kaybolur.
