# Tarayıcı kanıtı

Kalıcı tarayıcı paketi varsayılan `http://localhost:8080` olmak üzere `APP_E2E_BASE` üzerinde çalışır.
Süreç kaynaklı `super-admin` kimlik bilgilerini kullanır ve depoya işlemez. Temel senaryo; korumalı
yönlendirme, oturum açma, belirtecin yalnız bellekte tutulması, kiracı uygulaması, veritabanı destekli
`/auth/me`, yeniden yüklemede yenileme çereziyle kurtarma ve oturum kapatma temizliği davranışını kanıtlar.

`sql-review` paketi ayrıca `scripts/create-local-user.sh --role ...` ile açılmış yerel hesapları
ortam değişkenlerinden alır: `APP_E2E_REVIEWER_USER`/`_PASS`, `APP_E2E_SECOND_REVIEWER_USER`/`_PASS`
(ikisi `inceleyici`); kural ve bağlantı yönetimi süper yönetici hesabıyla yapılır (directory-login Decision 14). Arka ucun ulaşabildiği
OpenAI uyumlu bir LLM adresi `APP_E2E_LLM_BASE_URL` (isteğe bağlı `APP_E2E_LLM_MODEL`) ile verilirse
tam SQL betiği incelemesi çalışır; verilmezse yalnız "LLM bağlantısı yapılandırılmamış" reddi doğrulanır. İstemciden bağımsız
Node.js/Playwright kodudur; eklenti kurmaz veya ikinci MCP sunucusu açmaz. Tarayıcı çalıştırılabilir
dosyaları kontrollü çevrimdışı paketten gelmeli ve
`PLAYWRIGHT_BROWSERS_PATH` ile seçilmelidir.

Paketi depo kökünden çalıştırın:

~~~sh
export KT_SCAFFOLD_OFFLINE_BUNDLE=/approved/bundles/<platform-matrix>
export KT_SCAFFOLD_OFFLINE_BUNDLE_SHA256=<bank-admission-sha256-of-SHA256SUMS>
scripts/e2e.sh auth
~~~

Varsayılan kip çevrimdışıdır. Yardımcı önce `SHA256SUMS` dosyasını bankanın bant dışı yapıt kabul
kaydındaki özete bağlar; listedeki her dosyayı doğrular, paketin platform uyumluluğunu denetler, npm
çevrimdışı kipiyle paket önbelleğinden kurar, Playwright'ın kabul edilmiş ağaç içindeki
çalıştırılabilir Chromium dosyasını çözümlediğini doğrular ve ancak sonra paketi başlatır. Kayıt deposuna
veya tarayıcı indirmesine geri dönüş yoktur. Yük ile paket içi bildirimi birlikte yeniden yazmak
güven oluşturmaz. Bankaya bağlı geliştirme ortamı açıkça `KT_SCAFFOLD_E2E_MODE=private-index`
seçebilir; bu kip ayrıca `KT_SCAFFOLD_NPM_REGISTRY` ve önceden hazırlanmış
`PLAYWRIGHT_BROWSERS_PATH` ister, genel npm kayıt depolarını reddeder.

Hata durumunda her paket kısa ad içeren `test-results/*-failure.png` yazar; bu yok sayılan yerel
kanıttır. Kök kalite kapısı bütün `e2e/*/run-all.mjs` çalıştırıcılarını keşfeder; üretilen alan paketleri
tarayıcı kanıt seviyesinin sessizce dışında kalamaz.
