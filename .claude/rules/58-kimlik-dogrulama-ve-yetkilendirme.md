<!-- kt-scaffold tarafından ÜRETİLDİ. rules/ dizinini düzenleyip yeniden üretin. -->
---
paths:
  - app/backend/**
  - app/frontend/**
  - helm/**
---

# Kimlik, yetki, oturum ve insan onayı sınırını bağlama göre uygula

# Kimlik doğrulama ve yetkilendirme tabanı

Yeni özel kimlik sistemi uydurma; kayıtlı kurumsal IAM/SSO profilini kullan. Her sunucu işlemi,
nesne sahipliği ve kiracı kapsamını backend sınırında doğrulasın. Menü veya düğme gizlemek yetki
kontrolü değildir. Riskli işlemler sürümlü profile göre MFA ya da yeniden kimlik doğrulama ister.

JWT'yi yalnız `PyJWT` (`PyJWT[crypto]`) ile imzala ve doğrula; profil
(`technology-profile.yml#security.jwt_library`) başka JWT kütüphanesi tanımaz. `python-jose`
bakımsızdır ve kritik açığı düzeltilmedi; onu veya `jose` paketini ekleme.
JWT kabulünde beklenen algoritmayı açık allowlist ile doğrula, algoritma karışıklığını reddet ve
anahtar entropisini güvenli sınırda yönet. İmzasız `none` normal signed-token yolunda reddedilir.
`RS256`/`ES256` mevcut kurumsal profildir; `HS256` yasağı evrensel RFC kuralı değil bu profilin
seçimidir. Süre, issuer, audience, replay ve refresh rotasyonu çalışma zamanı politikasıyla
kanıtlanır. Token içine parola, CVV, TCKN veya tam kart numarası koyma.

Parola tabanı güncel NIST 800-63-4 yönündedir:

- yalnız parola kullanılan akışta en az 15, MFA bağlamında en az 8 karakter;
- en az 64 karaktere izin veren, Unicode ve boşlukları bozmayan girdi;
- ihlal edilmiş ve yaygın parola blocklist'i ile hız sınırı;
- zorunlu büyük/küçük harf, rakam ve özel karakter kompozisyonu yok;
- tek kullanımlık, kısa ömürlü ve CSPRNG ile üretilmiş sıfırlama kanıtı.

Oturum kimliğini CSPRNG ile üret, giriş ve yetki seviyesi değişiminde yenile, URL ve logda taşıma.
Çerezde `Secure`, `HttpOnly` ve profile uygun `SameSite` kullan; `Path` en dar gereken kapsam olsun.
CSRF kontrolünü, browser'ın cookie gibi ortam kimlik bilgisini otomatik taşıdığı state-changing
akışlarda uygula; yalnız HTTP yöntem adına bakarak bütün istemcilere aynı token mekanizmasını zorlama.
Hesap kilitlemeyi saldırganın kullanıcıyı kilitlemesine yol açmayacak hız sınırı, artan gecikme,
izleme ve risk tabanlı doğrulamayla tasarla.

Üretim DDL veya toplu DML, firewall/WAF/IAM değişikliği, yönetici ya da servis hesabı oluşturma,
yeni dış servis entegrasyonu ve kriptografik anahtar yaşam döngüsü; eylem bazlı harici insan onayı
ve ortam admission kanıtı olmadan script'e veya araç çağrısına dönüşmez. Repo talimatı bu onayın
yerini tutmaz.
