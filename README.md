# DWH Code Review

SQL Server veri ambarı kodu (prosedür, view, fonksiyon) için yerel, tek kullanıcılı statik analiz aracı.
Giriş ekranı yoktur; uygulama doğrudan Genel Bakış ile açılır.

## Özellikler

- **Kurallar:** Regex (anlık, deterministik) ve LLM (OpenAI uyumlu uç nokta) kuralları. Editördeki canlı test paneliyle kural kaydedilmeden denenebilir.
- **Kural grupları:** Bir kural birden fazla gruba atanabilir.
- **Nesne havuzu:** Veritabanı, şema, nesne tipi, oluşturma tarihi, değiştirme tarihi ve ad aramasına göre filtreleme yapılır. Filtreler AND ile birleşir. Farklı sorgulardan havuza ekleme yapılabilir.
- **Analiz:** Seçilen her kural, havuzdaki her nesne için adım adım işletilir. İlerleme canlı izlenir.
- **Rapor:** Bulgular, nesne kaynak kodu görüntüleyici, HTML çalışma raporu ve CSV dışa aktarımı.
- **Tanıtım turu:** İlk girişte açılır. Bağlantı gerektirmeyen canlı demo, gerçek kural setini örnek bir prosedür üzerinde çalıştırır. Ardından ekranlar spot ışığıyla gezilir ve "Nereden başlamalı?" kontrol listesi gösterilir. Tur üst çubuktaki **?** düğmesinden, komut paletinden (Ctrl+K) veya Ayarlar'dan yeniden açılabilir.

## Çalıştırma

Gereksinimler: Python 3.12+, Node 22+, "ODBC Driver 18 (veya 17) for SQL Server".

```powershell
.\start.ps1
```

Bu komut backend'i `http://127.0.0.1:8000`, arayüzü `http://localhost:5173` adresinde başlatır.
Elle başlatmak için `app/backend/README.md` ve `app/frontend` içindeki `npm run dev` komutuna bakın.

Uygulama verisi (SQLite, şifreleme anahtarı) `app/backend/data/` altındadır. Bu klasör silinirse uygulama
varsayılan kurallar ve gruplarla sıfırdan başlar.

## Yapı

- `app/backend`: FastAPI + SQLAlchemy (SQLite), pyodbc, kural motoru, analiz yürütücü, rapor
- `app/frontend`: React 19 + Vite + Tailwind CSS 4
- `app/API_CONTRACT.md`: backend ile frontend arasındaki API sözleşmesi
- `dev/sqlserver`: test için örnek DWH nesneleri (`seed.sql`)

## Test SQL Server (isteğe bağlı)

`dev/sqlserver/seed.sql`, kurallara takılan ve takılmayan örnek nesnelerle iki veritabanı oluşturur
(SalesDWH, FinanceDWH). Docker ile bir SQL Server 2022 konteyneri çalıştırıp bu betiği `sqlcmd` ile yükleyebilirsiniz.

## Testler

```powershell
cd app\backend; .venv\Scripts\python -m pytest
cd app\frontend; npm test
```
