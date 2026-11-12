# DWH Code Review — Backend

SQL Server DWH nesnelerini (prosedür, view, fonksiyon) regex ve LLM kurallarıyla inceleyen
yerel, tek kullanıcılı FastAPI servisi. API sözleşmesi: `../API_CONTRACT.md`.

## Gereksinimler

- Python 3.12
- "ODBC Driver 18 for SQL Server" (yoksa 17 kullanılır)

## Kurulum

```powershell
cd app\backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Testler için: `.venv\Scripts\python -m pip install -r requirements-dev.txt`

## Çalıştırma

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload
```

- API: http://127.0.0.1:8000/api/health — etkileşimli dokümantasyon: http://127.0.0.1:8000/docs
- Veriler `data/` klasöründe tutulur: `dwhcr.db` (SQLite) ve `secret.key` (kayıtlı SQL Server
  parolası ile LLM API anahtarını şifreleyen anahtar). `secret.key` silinirse kayıtlı parolalar
  yeniden girilmelidir. Farklı bir klasör için `DWHCR_DATA_DIR` ortam değişkenini kullanın.
- İlk açılışta örnek kurallar, kural grupları ve (kapalı) LLM ayarları oluşturulur.

## Testler

```powershell
.venv\Scripts\python -m pytest
```

## Yapı

```
app/
  main.py            uygulama, CORS, hata işleyicileri, başlangıç (tablo oluşturma + seed)
  config.py db.py models.py schemas.py crypto.py seed.py
  routers/           rules, groups, connections, settings, analyses, dashboard
  services/
    catalog.py        pyodbc ile SQL Server katalog erişimi
    rule_engine.py    regex kuralları, yorum/string maskeleme
    llm.py            OpenAI uyumlu /chat/completions istemcisi
    analysis_runner.py arka plan analiz çalıştırıcısı
    report.py         HTML / CSV rapor
tests/
```
