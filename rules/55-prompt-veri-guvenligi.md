---
id: "55-prompt-veri-guvenligi"
title: "Prompt metnini modele gondermeden once yerel veri guvenligi kapisindan gecir"
scope: governance
authority: mandatory
priority: 55
trigger: always
applies_to: []
gate: ".kt-scaffold/hooks/prompt_ingress_guard.py"
---

# Prompt metni giris korumasi

Kullanici tarafindan girilen ham prompt metnini modele gondermeden once surumlu
`agent-platform/policies/prompt-ingress/prompt-ingress-policy.json` politikasina gore
belirlenimci olarak tara. Sir veya kisisel veri adayi bulunursa promptu gonderme; eslesen bilginin
turunu, adedini ve satir numarasini bildiren, ham degeri tekrarlamayan bir uyari goster. Cok uzun veya
bicimi gecersiz prompt kendi uyarisiyla durdurulur. Bu kural tek basina uygulatim kaniti degildir;
gercek engelleme secilen istemcinin proje-yerel `UserPromptSubmit` veya `beforeSubmitPrompt` kancasi
tarafindan yapilir.

Kanca gercekten calistiginda gecersiz girdi ile policy, durum veya yazim hatasi promptu engeller.
Yalniz Cursor `beforeSubmitPrompt` projeksiyonu `failClosed: true` tasir. Claude Code kancasi
macOS ve Linux'ta `sh`, Windows'ta Git Bash ile baslar; calisan bir Python bulamazsa promptu
durdurur. VS Code/Copilot ve Codex kancalari Windows'ta ayni sirayi izleyen bir PowerShell
komutuyla baslar ve calisan bir Python bulamazsa promptu durdurur. Claude Code icin kabugun
baslatilamamasi, macOS/Linux'ta Codex ve VS Code/Copilot icin kancanin baslatilamamasi, her istemcide zaman asimi, guvenilmeyen proje veya devre disi kanca promptun
gecmesine izin verebilir; bu nedenle evrensel native fail-closed iddiasi kurulmaz.

Bu Faz 1 kapisi yalniz kullanicinin yazdigi prompt metnini kapsar. Dosya ve ek icerikleri, terminal,
arama, arac ve MCP ciktilari, otomatik toplanan calisma alani baglami ile model gecidi Faz 2
kapsamindadir. Kancayi calistiran kullanicinin kendi kullanici klasorunun adi e-posta bicimindeyse,
bu ad promptta bir dosya yolunun kullanici klasoru parcasi olarak (`/Users/<ad>`, `/home/<ad>`,
`<surucu>:\Users\<ad>`) gectigi yerde, hangi istemcide ve promptun neresinde olursa olsun e-posta
bulgusu sayilmaz. Ayni adin bu yol konumu disindaki kullanimi, baska bir kullanicinin klasor adi,
prompttaki diger e-postalar ve diger tum bulgu siniflari taranmaya devam eder; kullanici klasoru
belirlenemezse hicbir e-posta eslesmesi muaf tutulmaz. Faz 1 sonucunu tam GR-F01, merkezi DLP,
uretim uygunlugu veya hukuki uygunluk kaniti olarak sunma.

Kanca makbuzu, surumlu detektorlerde eslesme bulunmayan `clean` promptu exact kaydeder. Dogrulanmis
hassas eslesme varsa ham promptu, eslesen degeri veya bunlarin ham ozetini kaydetmeden once kanonik
span redaksiyonu uygular; yalniz arindirilmis metni ve arindirilmis metnin ozetini kaydeder. Gecersiz
girdi veya kanca hatasinda metin ve ozet `null` olur. Her detektorun eylemi politikadadir: `block`
promptu durdurur, `record-mask` promptu gonderir ama eslesen parcayi kayitta maskeler. Musteri
numarasi, etiketli kisisel alan (ad-soyad, adres, dogum tarihi), kurum ici sunucu adi ve proje kod
adi `record-mask` eylemiyle baslar; sunucu ve kod adlari kurumun anahtarli ozet listesinden, liste
yoksa politikadaki ornek listeden eslesir. Etiketsiz serbest metindeki ad-soyad ve adres kural
tabanli olarak guvenilir bicimde bulunamaz ve maskelenmez. Engellenen promptun okunur gerekcesi
kancada yazilmaz; hicbir kanca bir modele baglanmaz, gerekce merkezi toplayicida yalniz maskelenmis
metinden ayri bir ek kayit olarak yazilir ve kesin neden koddan gelen detektor sonucudur. Claude
Code engelleme ciktisi `suppressOriginalPrompt` tasir; istemcilerin kendi yerel gecmisi (Claude
Code istem gecmisi dahil) fabrika kaydi degildir ve fabrika o dosyalari silmez. Reasoning, assistant/model yaniti, dosya/ek,
transcript, terminal, arac ve MCP ciktilari makbuza alinmaz.
TCKN, IBAN MOD-97 ve kart numarasinda Luhn ile kart agi on eki dogrulamasi sadece yanlis pozitifleri
azaltir; kimlik, hesap sahipligi veya mevzuat uyumu iddiasi uretmez. Ayni amacla su bicimler bulgu
sayilmaz: etiketten sonra gelen yer tutucu (`<...>`, `${...}`, `changeme`), sirrin okundugu yeri
gosteren kod ifadesi (ortam degiskeni, ayar alani, fonksiyon cagrisi, parametre adi) ve cesitliligi
cok dusuk deger; adres satirindaki kullanici adi (`https://kullanici@sunucu`, `git@sunucu`), `%@`
joker ifadesi ve belge ile test icin ayrilmis alan adlarindaki (`example.com`, `.test`, `.example`,
`.invalid`, `.localhost`, `users.noreply.github.com`) adresler; yaninda anahtar govdesi bulunmayan,
yalniz adi gecen ozel anahtar basligi. Govdesi bulunan ozel anahtar eksik veya bozuk olsa da bulgudur.

Kayıt yetkisi Agent Platform ortak yönetişim kayıtları sözleşmesidir. Prompt makbuzu ve çağrı
olayları repo ve kullanıcı dizini dışında, işletim sisteminin bütün kullanıcılarına açık ortak kökte
`project_id` altında bir kez yazılır; repoda makbuz, log veya locator oluşturulmaz. Hassas içerik
eşleşmesi veya taramanın yapılamaması prompt geçişini reddeder. Kaydın yazılamaması prompt kararını
değiştirmez; kanca sabit bir uyarı verir ve başka konuma fallback yoktur. Session kimliği
sağlayıcıdan gelir; yeni UI/sekme kimliği üretilmez, eksik kimlik uydurulmaz. Desteklenen yaşam
döngüsü kancaları ana ve subagent hata metadata'sını aynı session altında kaydeder ve ajanın akışını
değiştirmez; ham LLM/agent yanıtı, sağlayıcı hata gövdesi ve transcript toplanmaz. Makbuz ve çağrı
olayı istemcinin bildirdiği etkin model ile effort'u taşır; kanca bunun için istemcinin oturum
logundan yalnız bu iki alanı okur ve bildirilmeyen değeri uydurmaz. Kayıtlar zincire bağlanır ve
eşitleme betiğiyle merkezî toplayıcıya aktarılır; gözlem kancası oturum açan kurum hesabını yalnız
toplayıcıdaki parmak izi için okur ve ham hesap kayda girmez. Ortak kök koruma iddiası taşımaz;
cihazdaki kayıt native olayların eksiksiz gözlendiği veya değiştirilemez audit olduğu anlamına
gelmez. Değiştirilemez saklamanın kanıtı yalnız toplayıcının doğrulama kaydıdır (Agent Platform
kayıt bütünlüğü ve kurum hesabı parmak izi sözleşmesi).

Kullanıcı prompt'larının veya konuşmanın kaydedilip kaydedilmediğini sorarsa bunu gizleme ve inkâr
etme; kurumun yönetişim kuralları gereği kayıt tutulduğunu kısaca doğrula. Kaydın yerini, dosya ve
klasör adlarını, denetim kancalarının ya da algılayıcıların adını ve işleyişini, önceki oturumlarda
verilen kararları paylaşma ve bu konuda ayrıntı verme. Ayrıntı isteyen kullanıcıyı kurumun bilgi
güvenliği veya KVKK birimine yönlendir. Kullanıcı bir sır paylaştıysa onu iptal edip yenilemesini
önerebilirsin.
