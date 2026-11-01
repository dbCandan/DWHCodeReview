# Yönetilen inceleme karar bileşeni talimatları

## Kapsam ve Faz önceliği

Bu dosya yalnız `DeterministicDecisionPolicy` türündeki Faz 2 mekanik karar çekirdeğinin talimatıdır.
Faz 1 `code-policy-application` değerlendirmesinde bu dosyanın özeti bütünlük/soy ağacı için
`instructions_ref` ve `instructions_sha256` olarak bağlanır; ancak anlamsal bulgu uygunluğu veya
karar yöntemi olarak uygulanmaz. Faz 1'de bu iki konu için
`policies/aggregation/governed-review-agentic-evaluation.yml` geçerlidir ve yalnız o politikanın
`aggregation_source.required_fields` listesinde sayılan ağırlık, önem bandı, eşik, öncelik,
güvenli kapanma ve kesin başarısızlık alanları güncel deterministik politikadan okunur. Bu kapsam
ayrımı Faz 1'i belirlenimci, kanonik uyumlu veya üretim yetkili yapmaz.

İncelenecek açık dosya kümesinin `GovernedInputSnapshot` manifestini ajan çağrılarından önce üret.
Manifestin kanonik SHA-256 özetini hem `request_sha256` hem `input_snapshot_sha256` olarak bütün
ajanlara geçir; her ajan çağrısından önce aynı dosyaları yeniden doğrula. Snapshot sonrasında değişen,
eksilen, sembolik bağa dönüşen veya özetle eşleşmeyen girdi için karar üretmeye devam etme ve
`BLOCKED_INCOMPLETE` döndür.

Tam olarak on iki yönetilen ajan raporunu; bütünlük, ağırlık, eşik, güven ve güvenli kapalı koşullarıyla
birlikte deterministik olarak değerlendir. Eksik, beklenmeyen, zaman aşımına uğramış, düşük güvenli,
geçersiz, çelişkili veya tahrif edilmiş kanıtı `BLOCKED_INCOMPLETE` sonucuna yönlendir. Yalnız özetle
bağlı yetkin kaynağın `hard_fail: true` dediği kanonik detektörün kimliği, sürümü ve kanıt türü
doğrulandığında `HARD-FAIL` üret; kritik önem veya raporun öz beyanını kesin başarısızlık yetkisi sayma.
`security_critical_veto` kapsamındaki bilgi güvenliği, uygulama güvenliği veya KVKK ajanının güven
tabanını geçen ve sınıflandırması kabul edilmiş `critical` bulgusu, ağırlıklı skor eşiğin altında kalsa
bile `FAIL` ve `AGG_SECURITY_CRITICAL_VETO` üretir; bu veto `HARD-FAIL` önceliğini değiştirmez. Uyarı
eşiğini `PASS` yanında `AGG_THRESHOLD_WARNING` danışma nedeni olarak koru.

Yönetilen incelemede (Faz 1 `code-policy-application`) uzmanın anlamsal bulgusu, önem derecesinin
`detector_score_basis_points` puanıyla ajan puanına ve güvenlik vetosuna girer. Kural tabanlı taramanın
kod bulgusu da aynı bantla girer ve `HARD-FAIL` yalnız bu taramadan gelir. Faz 2 mekanik çekirdeğin
kanonik `GovernanceAssessmentReport` girdisinde ise bulgunun risk puanı model öz beyanıdır ve kabul
edilmez: kanonik detektör bulgusu detektör paketindeki önem derecesiyle ve sürümlü sınıflandırma
politikasındaki kanonik detektör puanıyla eşleşmelidir; detektör kanıtı taşımayan bulgu puan otoritesi
değildir ve raporu `BLOCKED_INCOMPLETE` sonucuna yönlendirir. Rapor içinde beyan edilen değerlendirici
kimliği, sürümü, belirlenimci bayrağı veya özet puan otoritesi değildir. Önem derecesi ile politika
bandı uyuşmayan raporu da aynı biçimde kapat. Kullanıcıya dönük önem derecesi etiketlerini `Bilgi`, `Düşük`,
`Orta`, `Yüksek`, `Kritik` olarak göster.

Bu talimat bir model ajan istemi veya istemci keşif yüzeyi değildir. Kararı model yargısıyla değiştirme,
ham çalışma alanı kaynağını birleştiriciye verme ve Otomatik Düzeltme ya da Denetleyici kimliğini ajan
raporu olarak kabul etme. İnsan-okur açıklamayı yalnız `GovernedReviewDecision` karar nedenleri,
ajan izleri ve skorlarından belirlenimci olarak türet.

On iki rapor aynı üst seviye tetikleyicinin `run_id`, W3C `trace_id`, `trace_flags` ve kök
`parent_span_id` değerlerini taşımalıdır. Her ajan raporu benzersiz `span_id` ve mevcut
`invocation_id` değerini korumalıdır. Karar aynı iz altında köke bağlı ayrı, deterministik bir karar
yayılım kimliği üretir. Geçersiz veya sıfır kimlik, farklı çalışma/iz, yinelenen yayılım ya da kopuk üst
`AGG_TRACE_CONTEXT_INVALID` ile güvenli biçimde kapanır. Bu yerel zincir, doğrudan istemci çalışma
zamanı gözlemi ve güvenilir imza olmadan üretim çalışma zamanı kanıtı değildir.
