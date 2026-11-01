<!-- kt-scaffold tarafından ÜRETİLDİ. rules/ dizinini düzenleyip yeniden üretin. -->
---
paths:
  - app/backend/**
  - app/infra/observability/**
---

# Taban telemetriyi yararlı, sınırlı ve hassas veriden arınmış tut

# Arka uç gözlemlenebilirliği

Taban, standart çıktıya yapılandırılmış `JSON` günlüğü gönderir. Her `HTTP` tamamlanma günlüğü;
doğrulanmış veya üretilmiş istek tanımlayıcısını, yöntemi, eşleşen rota şablonunu, yanıt durumunu ve
süreyi içerir. Ham yol ve sorgu parametresi günlüklenmez. Tarayıcı, vekil ve arka uç kanıtı
ilişkilendirilebilsin diye istek tanımlayıcısını `x-request-id` olarak döndür. Yetkilendirme başlığını,
`JWT`'yi, çerezi, istek/yanıt gövdesini, parolayı, sorgu dizesini, kiracı kaydını veya gelişigüzel
istisna metnini asla günlükleme.

Sağlık ve canlılık yalnız süreç durumunu raporlar. Hazırlık zorunlu bağımlılıkları kontrol edebilir
ancak bağlantı ayrıntısı sızdırmamalıdır. İsteğe bağlı kapalı yerel gözlemlenebilirlik ortamı;
toplayıcı `Grafana Alloy`, `Prometheus`, `Tempo`, `Loki` ve `Grafana`'dan oluşur. `Alloy` uygulamanın
`OpenTelemetry` sinyalini yalnız iç ağda alır ve bu üç depoya aktarır; Grafana'ya kullanım raporu
göndermez. Bu bir altyapı alıcısı ve inceleme yüzeyidir; uygulama sinyalinin bulunduğunun kanıtı
değildir. İlk kök Helm chart'ı gözlemlenebilirlik iş yükü içermez; Kubernetes dağıtımı ayrı kabul
edilmiş proje PRD'si ister.

Yeteneğe özgü ölçüm ve iz; sinyal adını, niteliği, kardinalite sınırını, saklama beklentisini ve onu
tüketen test veya gösterge panosu sorgusunu tanımlayan kabul edilmiş `PRD` gerektirir. Kiracı, kullanıcı,
istem ve iş tanımlayıcıları sınırsız ölçüm etiketi olarak yasaktır. Gerçek uygulama sinyali deposuna
ulaşmadan ve adlandırılmış sorgu doğrulanmadan gösterge panosunun, alarmın, iz kaydının veya `SLO`'nun
işlevsel olduğunu iddia etme.
