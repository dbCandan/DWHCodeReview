# application-foundation alanı

## Amaç ve sonuçlar

DWH Code Review'un kimlik, yetki, çalışma ortamı ve dağıtım temeli. Kullanıcılar kurum Active
Directory hesabıyla girer, rolüne göre yetkilendirilir; uygulama yerelde Compose ile, nonprod'da KT
Rancher kümesinde tek chart ile çalışır.

## Aktörler

- **Kullanıcı:** Active Directory hesabıyla giriş yapan, `inceleyici` rolündeki kişi.
- **Uygulama yöneticisi:** Rol atamalarını yapan süper yönetici.
- **İşletim ekibi:** Azure dağıtım işini, gizli değişkenleri ve küme kaynaklarını yönetir.

## Ortak dil

- **Dizin girişi:** Kullanıcı adı ve parolanın LDAPS üzerinden Active Directory'de doğrulanması.
  Kullanıcı eşitleme ve dizinde arama yoktur.
- **Rol:** `inceleyici` (arayüzde "Kullanıcı"); diğer yetkiler süper yöneticidedir (directory-login Decision 14).
- **Runtime Secret:** Nonprod'da uygulama sırlarını taşıyan Kubernetes Secret'ı
  (`dwhcodereview-runtime`); `helm/dwhcodereview/deploy-hooks.sh` hazırlar: oturum imza anahtarını
  ve ayar şifreleme anahtarını bir kez üretir, verilmişse isteğe bağlı Azure gizli değişkenlerini
  yazar.
- **Ortam:** `local` (geliştirici makinesi, `DWHCODEREVIEW_ENVIRONMENT=development`) veya `nonprod`
  (KT Rancher kümesi, `DWHCODEREVIEW_ENVIRONMENT=staging`). Başka ya da okunamayan değer `nonprod`
  gibi davranır.

## Değişmezler

- Her API isteği, sağlık uçları dışında, geçerli oturum ve uygun rol ister; SSE akışları dahil.
- Parola uygulamada saklanmaz; yalnız dizine doğrulama için iletilir.
- Sırlar Git'e, Helm değer dosyasına, komut argümanına ve loga girmez.
- Dağıtım, yayımlanmamış imajla kümeye dokunmaz ve hizmet vermiş release'i silmez.
- Ölçümler ve izler (OpenTelemetry) yalnız PRD'lerin Gözlemlenebilirlik bölümünde adı geçen
  sinyallerdir. Etiket değerleri sabit kümelerdir; kümede olmayan değer `other` olarak yazılır. SQL
  metni, kod parçası, etiket, model yanıtı, adres, parola, belirteç, kullanıcı adı, nesne ve
  veritabanı adı hiçbir iz aralığına, özniteliğe veya ölçüme girmez; hata metni ize yazılmaz.

## Sahip olunan veri

PostgreSQL'de kullanıcı kaydı (dizin kimliği, görünen ad, rol, son giriş) ve oturum yenileme durumu.

## Harici sınırlar

- **Active Directory:** LDAPS, kurum CA bundle'ı ve onaylı çıkış hedefleri.
- **KT Rancher nonprod kümesi ve Azure dağıtım işi:** `helm/dwhcodereview/deploy.sh` ile.
- **Kurum imaj deposu:** `cr-test.kuveytturk.com.tr/ghcr.io.vc/kt-vibecoding/`.
- **OpenTelemetry toplayıcısı:** Ölçüm ve izler OTLP/gRPC ile yalnız
  `DWHCODEREVIEW_OTEL_EXPORTER_OTLP_ENDPOINT` adresine gider; ayar boşsa hiçbir sinyal dışarı
  çıkmaz ve `OTEL_` ile başlayan süreç değişkeni başlangıcı durdurur. Yerelde gözlemlenebilirlik
  Compose katmanı adresi kendi toplayıcısına yöneltir; orada Prometheus ölçümleri 15 gün, Tempo
  izleri 14 gün saklar. `nonprod`'da adres yalnız `https` olabilir; kümede toplayıcı yoktur ve
  kurulması ayrı PRD ister (`rules/25`).

## İş yetkinliği yol haritası

[Yol haritası](roadmap.md).
