# sql-review alanı

## Amaç ve sonuçlar

Veri ambarı geliştiricileri, SQL Server'daki nesnelerini (saklı yordam, görünüm, fonksiyon) ve
yapıştırdıkları SQL metnini kurumun yayımlanmış inceleme kurallarına göre kurum içi LLM ile inceler.
Sonuç, her kural için satır referanslı bulgular ve düzeltme notlarıdır; CSV ve düzeltme yorumlu SQL
olarak dışa aktarılır. Bu alan, `~/codes/dwhcodereview` uygulamasının davranışını fabrika yapısına
taşır; mevcut davranış kaynak kabul edilir, farklılıklar PRD'lerde açıkça yazılır.

## Aktörler

- **İnceleyici:** Veri ambarı geliştiricisi. Nesne veya metin inceletir, sonuçları görür, dışa aktarır.
- **Kural yöneticisi:** 1.x ile kaldırıldı (directory-login Decision 14); kuralları süper yönetici
  düzenler ve yayımlar.
- **Uygulama yöneticisi (süper yönetici):** Kuralları, grupları ve taslağı düzenler ve doğrudan yayımlar;
  nonprod'da, dağıtım SQL Server bağlantısını vermiyorsa bağlantıyı arayüzden girer. Kimliği ve yetkisi
  `application-foundation` alanındadır.
- **İşletim ekibi:** Ortam ayarlarını, sırları ve dağıtımı yönetir; uygulama içinde bir rol değildir.

## Ortak dil

- **Kural:** Kimliği (`Kural01` biçiminde), ayrıntılı metni, tek cümlelik özeti ve "nesne meta verisi
  gerekir" işaretini taşıyan tek inceleme ölçütü. LLM'e ayrıntılı metin gider; süper yönetici dışındaki
  kullanıcılar kuralı özetiyle görür. Kurallar **kritik** ve **normal** olmak üzere iki öncelik grubundadır.
- **Kural grubu:** Süper yöneticinin tanımladığı adlandırılmış kural
  kümesi (örneğin Performans, Güvenlik). Öncelik grubundan (kritik/normal) ayrı bir boyuttur; bir kural
  sıfır, bir veya daha çok gruba üye olabilir, hiçbir gruba üye olmayan kural "grupsuz"dur. Gruplar kural kümesi sürümüyle birlikte yayımlanır ve donar.
- **Kural önerisi ve yayın isteği:** (2026-10-19'da [rule-proposals](PRDs/009-rule-proposals/PRD.md) 2.0.0
  Decision 8 ile kaldırıldı.) Eski kayıtların tabloları geçmiş olarak yerinde kalır.
- **Kural kümesi:** Kuralların tamamı. Bir **taslak** ve yayımlanmış **sürümler** vardır; inceleme
  yalnız en son yayımlanmış sürümü kullanır.
- **Nesne:** SQL Server'daki kullanıcı nesnesi: saklı yordam, görünüm, skaler/satır içi/tablo
  fonksiyonu. Veritabanı, şema, ad ve türle tanımlanır.
- **Nesne meta verisi:** Nesnenin bağımlı olduğu nesneler ve sütun özetleri; yalnız işaretli
  kurallarda LLM isteğine eklenir.
- **İnceleme koşumu:** Bir veya daha çok nesnenin ya da bir SQL metninin, belirli bir kural sürümüyle
  ve isteğe bağlı kural grubu seçimiyle (seçilmezse tüm kurallar) incelenmesi. Canlı ilerleme olayları
  üretir.
- **Kural sonucu:** Bir nesne ve bir kural için LLM değerlendirmesi: uyumlu, ihlal var veya
  değerlendirilemedi.
- **Bulgu (ihlal):** Kural sonucundaki tek ihlal; satır referansı, kod parçası ve açıklama taşır.
  Açıklama düzeltme notu olarak kullanılır; ayrı bir düzeltme önerisi alanı yoktur.
- **Zamanlanmış inceleme:** Nesne seçimi, kural grubu seçimi, periyot ve alıcılardan oluşan kayıtlı
  tanım. Arka uç içindeki zamanlayıcı onu periyodunda tarayıcıdan bağımsız çalıştırır ve alıcılara
  yalnız özet ile rapor bağlantısı içeren e-posta gönderir.
- **İki parçalı analiz:** Eşik uzunluğu aşan SQL'in iki parçada incelenip sonuçların birleştirilmesi.
- **LLM çağrı özeti:** Bir LLM çağrısının zaman, model, süre, durum ve belirteç sayısı gibi meta
  verisi. Ham SQL veya ham yanıt değildir.

## Değişmezler

- İnceleme yalnız yayımlanmış kural sürümünü kullanır; her koşum hangi sürümle yapıldığını saklar.
- SQL Server'a yalnız salt okunur katalog ve tanım sorguları gider; uygulama SQL Server'da yazma
  yapmaz ve incelenen kodu çalıştırmaz.
- Ham SQL metni ve ham LLM yanıtı günlüklere yazılmaz; yalnız LLM çağrı özeti saklanır.
- LLM isteği yalnız onaylı kurum içi LLM ucuna gider; ağ politikası dışındaki hedef reddedilir.
- Sırlar (SQL Server parolası, LLM anahtarı, LDAP ve oturum anahtarları) yalnız sunucu sınırındadır;
  arayüze, Git'e ve loga girmez. Veritabanına yalnız nonprod'un SQL Server parolası, şifrelenmiş
  olarak yazılır.
- Nonprod'da LLM bağlantı ayarı arayüzden değiştirilemez. SQL Server bağlantısı dağıtımdan
  geliyorsa o da değiştirilemez; gelmiyorsa yalnız süper yönetici girer ve değiştirir.

## Sahip olunan veri

PostgreSQL'de: kural kümesi taslağı ve yayımlanmış sürümleri, inceleme koşumları, kural sonuçları ve
bulgular, LLM çağrı özetleri, nonprod'da süper yöneticinin kaydettiği SQL Server bağlantısı (parolası
şifreli). İncelenen SQL metni (nesne tanımı veya yapıştırılan metin) koşumla
birlikte saklama süresi boyunca (varsayılan 90 gün) tutulur; yalnız koşumu başlatan kullanıcı,
süper yönetici ve zamanlanmış koşumda o koşumun e-posta alıcısı olan kullanıcı görür. Günlüklere
yazılmaz. Ayrıca zamanlanmış inceleme tanımları, çalışma kayıtları, koşumla saklanan alıcı listeleri ve
kiracı başına zamanlanmış inceleme ayarı; kaldırılmış kural önerisi, yayın isteği ve öneri yetkisi
tabloları geçmiş olarak yerinde kalır.

## Harici sınırlar

- **SQL Server veri ambarı:** ODBC ile, ortama göre yapılandırılan salt okunur hesapla.
- **Kurum içi LLM sunucusu:** OpenAI uyumlu veya LM Studio tarzı sohbet ucu, kurum CA'sıyla TLS.
- **Kurumsal e-posta sunucusu (SMTP):** Zamanlanmış inceleme bildirimleri için; kurum CA'sıyla TLS,
  yalnız izinli kurum alan adlarına gönderim. Kod ve SQL metni e-postaya girmez.
- Kimlik ve dağıtım `application-foundation` alanındadır.

## İş yetkinliği yol haritası

[Yol haritası](roadmap.md).
