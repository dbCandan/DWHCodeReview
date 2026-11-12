"""The v1.0 seed rule set (21 rules, 4 groups); tests use it as regex/LLM fixtures."""

from typing import Any

# Functions that make a predicate non-SARGable when applied to a column.
_WHERE_FUNCS = (
    "YEAR|MONTH|DAY|DATEPART|DATEDIFF|CONVERT|CAST|TRY_CONVERT|TRY_CAST|"
    "UPPER|LOWER|LTRIM|RTRIM|TRIM|ISNULL|COALESCE|SUBSTRING|LEFT|RIGHT|LEN|REPLACE|FORMAT"
)

SEED_RULES: list[dict[str, Any]] = [
    {
        "code": "DWH001",
        "name": "SELECT * kullanımı",
        "severity": "medium",
        "pattern": r"(?<!EXISTS\()(?<!EXISTS \()(?<!EXISTS\( )(?<!EXISTS \( )\bSELECT\s+(?:ALL\s+|DISTINCT\s+)?"
        r"(?:TOP\s*\(?\s*\d+\s*\)?\s*(?:PERCENT\s+)?)?(?:\w+\.)?\*",
        "description": "SELECT * gereksiz kolonları okur, I/O ve ağ trafiğini artırır; tablo şeması "
        "değiştiğinde view ve ETL akışları sessizce bozulabilir.",
        "recommendation": "İhtiyaç duyulan kolonları açıkça listeleyin. EXISTS (SELECT * ...) "
        "kullanımı bu kuraldan muaftır.",
    },
    {
        "code": "DWH002",
        "name": "NOLOCK / READ UNCOMMITTED kullanımı",
        "severity": "medium",
        "pattern": r"\b(?:NOLOCK|READUNCOMMITTED)\b|\bISOLATION\s+LEVEL\s+READ\s+UNCOMMITTED\b",
        "description": "NOLOCK ipucu kirli okuma (dirty read), satırların iki kez okunması veya "
        "atlanması gibi tutarsız sonuçlara yol açabilir.",
        "recommendation": "Okuma tutarlılığı gerekiyorsa ipucunu kaldırın; okuyucu-yazıcı "
        "çakışmaları için READ COMMITTED SNAPSHOT tercih edin.",
    },
    {
        "code": "DWH003",
        "name": "CURSOR kullanımı",
        "severity": "medium",
        "pattern": r"\bCURSOR\b",
        "description": "Cursor'lar satır satır işlem yapar; büyük DWH hacimlerinde küme tabanlı "
        "sorgulara göre çok yavaştır ve kilitleri uzun süre tutar.",
        "recommendation": "İşlemi küme tabanlı (set-based) INSERT/UPDATE/MERGE ile yeniden yazın. "
        "Kaçınılmazsa LOCAL FAST_FORWARD cursor kullanın.",
    },
    {
        "code": "DWH004",
        "name": "SET NOCOUNT ON eksik",
        "severity": "low",
        "pattern": r"\bSET\s+NOCOUNT\s+ON\b",
        "match_mode": "absent",
        "object_types": ["PROCEDURE"],
        "description": "SET NOCOUNT ON olmadan her DML ifadesi istemciye 'n satır etkilendi' "
        "mesajı gönderir; bu gereksiz ağ trafiği ve bazı istemcilerde hata oluşturur.",
        "recommendation": "Prosedür gövdesinin başına SET NOCOUNT ON; ekleyin.",
    },
    {
        "code": "DWH005",
        "name": "EXEC(...) ile dinamik SQL",
        "severity": "high",
        "pattern": r"\bEXEC(?:UTE)?\s*\(",
        "description": "EXEC(@sql) veya EXEC('...' + @param) ile birleştirilen dinamik SQL, SQL "
        "enjeksiyonuna açıktır ve plan önbelleğini verimsiz kullanır.",
        "recommendation": "Dinamik SQL'i sp_executesql ile parametreli çalıştırın; nesne adları "
        "için QUOTENAME kullanın.",
    },
    {
        "code": "DWH006",
        "name": "@@IDENTITY kullanımı",
        "severity": "medium",
        "pattern": r"@@IDENTITY\b",
        "description": "@@IDENTITY, tetikleyiciler (trigger) tarafından başka tablolara eklenen "
        "satırların kimliğini döndürebilir ve yanlış değere yol açar.",
        "recommendation": "SCOPE_IDENTITY() veya OUTPUT INSERTED.<kolon> kullanın.",
    },
    {
        "code": "DWH007",
        "name": "Prosedür adı sp_ ile başlıyor",
        "severity": "medium",
        "pattern": r"(?:^|\.)sp_",
        "target": "name",
        "object_types": ["PROCEDURE"],
        "description": "sp_ öneki sistem prosedürleri için ayrılmıştır; SQL Server önce master "
        "veritabanında arar, bu da performans kaybına ve isim çakışmasına neden olur.",
        "recommendation": "Prosedürü farklı bir önekle (ör. usp_) yeniden adlandırın.",
    },
    {
        "code": "DWH008",
        "name": "GOTO kullanımı",
        "severity": "low",
        "pattern": r"\bGOTO\s+\w+",
        "description": "GOTO akışın izlenmesini zorlaştırır ve bakım maliyetini artırır.",
        "recommendation": "Akışı IF/ELSE, WHILE veya TRY/CATCH blokları ile yapılandırın.",
    },
    {
        "code": "DWH009",
        "name": "Eski stil dış birleşim (*= / =*)",
        "severity": "high",
        "pattern": r"(?<![@\w])\w+(?:\.\w+)*\s*\*=\s*[\w@]|\w\s*=\*\s*\w",
        "description": "*= ve =* ANSI öncesi dış birleşim söz dizimidir; SQL Server 2012 ve "
        "sonrası uyumluluk seviyelerinde desteklenmez ve belirsiz sonuç üretir.",
        "recommendation": "LEFT/RIGHT OUTER JOIN ... ON söz dizimine dönüştürün.",
    },
    {
        "code": "DWH010",
        "name": "Kullanımdan kalkmış TEXT / NTEXT / IMAGE tipi",
        "severity": "medium",
        "pattern": r"@\w+\s+(?:AS\s+)?(?:N?TEXT|IMAGE)\b"
        r"|\bCONVERT\s*\(\s*(?:N?TEXT|IMAGE)\b"
        r"|\bCAST\s*\([^;]*?\bAS\s+(?:N?TEXT|IMAGE)\s*\)"
        r"|^\s*(?!AS\b|SELECT\b)\[?\w+\]?\s+(?:N?TEXT|IMAGE)\b\s*(?:NOT\b|NULL\b|,|\)|$)",
        "description": "TEXT, NTEXT ve IMAGE veri tipleri kullanımdan kaldırılmıştır; çoğu dize "
        "fonksiyonu ile çalışmaz ve gelecek sürümlerde kaldırılacaktır.",
        "recommendation": "VARCHAR(MAX), NVARCHAR(MAX) veya VARBINARY(MAX) kullanın.",
    },
    {
        "code": "DWH011",
        "name": "Sabit kodlanmış tarih",
        "severity": "low",
        "pattern": r"'(?:19|20)\d{2}-?(?:0[1-9]|1[0-2])-?(?:0[1-9]|[12]\d|3[01])"
        r"(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?'",
        "ignore_comments": False,
        "description": "Kod içine gömülü tarih sabitleri ('2023-01-01' gibi) zamanla geçersizleşir, "
        "yükleme dönemleri değiştiğinde fark edilmeden yanlış veri üretir.",
        "recommendation": "Tarihleri parametre, yapılandırma tablosu veya GETDATE() tabanlı "
        "hesaplamalarla verin.",
    },
    {
        "code": "DWH012",
        "name": "Prosedürde TRUNCATE TABLE / DROP TABLE",
        "severity": "high",
        "pattern": r"\bTRUNCATE\s+TABLE\b|\bDROP\s+TABLE\s+(?!(?:IF\s+EXISTS\s+)?(?:\w+\.)?#)",
        "object_types": ["PROCEDURE"],
        "description": "Kalıcı tablolar üzerinde TRUNCATE/DROP geri alınması zor veri kaybına yol "
        "açabilir ve yüksek yetki gerektirir. Geçici (#) tablolar muaftır.",
        "recommendation": "İşlemin gerekliliğini doğrulayın; yetkiyi sınırlayın, işlem (transaction) "
        "ve yedekleme stratejisi ile koruyun ya da partition switch kullanın.",
    },
    {
        "code": "DWH013",
        "name": "TRY/CATCH hata yönetimi eksik",
        "severity": "medium",
        "pattern": r"\bBEGIN\s+TRY\b",
        "match_mode": "absent",
        "object_types": ["PROCEDURE"],
        "description": "Veri değiştiren prosedürlerde TRY/CATCH olmadan hatalar yakalanmaz, açık "
        "transaction'lar kalabilir ve ETL hatası loglanmaz.",
        "recommendation": "Gövdeyi BEGIN TRY ... END TRY BEGIN CATCH ... END CATCH ile sarın; "
        "CATCH içinde ROLLBACK ve THROW kullanın.",
    },
    {
        "code": "DWH014",
        "name": "View içinde TOP 100 PERCENT ... ORDER BY",
        "severity": "medium",
        "pattern": r"\bTOP\s*\(?\s*100\s*\)?\s*PERCENT\b(?=[\s\S]*\bORDER\s+BY\b)",
        "object_types": ["VIEW"],
        "description": "View içindeki ORDER BY sonuç sırasını garanti etmez; TOP 100 PERCENT "
        "hilesi optimizer tarafından yok sayılır ve yanıltıcıdır.",
        "recommendation": "ORDER BY'ı view'den kaldırın ve view'i sorgulayan ifadede kullanın.",
    },
    {
        "code": "DWH015",
        "name": "DISTINCT kullanımı",
        "severity": "info",
        "pattern": r"\bSELECT\s+DISTINCT\b",
        "description": "DISTINCT pahalı bir sıralama/hash işlemi gerektirir ve çoğu zaman hatalı "
        "join kaynaklı tekrarlı satırları gizler.",
        "recommendation": "Tekrarların nedenini (join koşulu, veri modeli) inceleyin; gerekirse "
        "GROUP BY veya EXISTS kullanın.",
    },
    {
        "code": "DWH016",
        "name": "WHERE koşulunda kolon üzerinde fonksiyon",
        "severity": "medium",
        "pattern": rf"\b(?:WHERE|AND|OR)\s+(?:NOT\s+)?\(?\s*(?:{_WHERE_FUNCS})\s*\(\s*(?!@)",
        "description": "Kolonu fonksiyon içine almak (YEAR(Tarih) = 2024, CONVERT(date, Kolon) "
        "= ...) koşulu SARGable olmaktan çıkarır; indeks seek yerine tarama yapılır.",
        "recommendation": "Fonksiyonu sabit tarafa taşıyın, ör. Tarih >= '20240101' AND Tarih < "
        "'20250101' biçiminde aralık koşulu yazın.",
    },
    {
        "code": "DWH017",
        "name": "SELECT ... INTO ile geçici tablo",
        "severity": "info",
        "pattern": r"(?<!INSERT )(?<!INSERT  )(?<!INSERT\t)(?<!INSERT\n)(?<!INSERT\r\n)\bINTO\s+#{1,2}\w+",
        "description": "SELECT ... INTO geçici tablo oluştururken kolon tiplerini kaynaktan "
        "türetir; tip/nullable farkları ve tempdb kilitleri beklenmeyen sorunlar doğurabilir.",
        "recommendation": "Büyük veri setlerinde geçici tabloyu CREATE TABLE ile açıkça tanımlayıp "
        "INSERT ... SELECT kullanmayı değerlendirin.",
    },
    {
        "code": "DWH018",
        "name": "WAITFOR DELAY / TIME kullanımı",
        "severity": "medium",
        "pattern": r"\bWAITFOR\s+(?:DELAY|TIME)\b",
        "description": "WAITFOR oturumu ve tuttuğu kilitleri bekletir; ETL sürelerini uzatır ve "
        "zamanlama sorunlarını gizler.",
        "recommendation": "Bekleme yerine zamanlayıcı (SQL Agent / orkestrasyon aracı) veya olay "
        "tabanlı tetikleme kullanın.",
    },
    {
        "code": "DWH019",
        "name": "xp_cmdshell kullanımı",
        "severity": "critical",
        "pattern": r"\bxp_cmdshell\b",
        "description": "xp_cmdshell veritabanı sunucusunda işletim sistemi komutu çalıştırır; "
        "ciddi güvenlik riski oluşturur ve yetki yükseltmeye açıktır.",
        "recommendation": "İşletim sistemi işlemlerini SSIS, SQL Agent CmdExec adımı veya harici "
        "bir orkestrasyon aracına taşıyın; xp_cmdshell'i kapalı tutun.",
    },
    {
        "code": "LLM001",
        "name": "İş mantığı açıklaması / karmaşıklık",
        "severity": "low",
        "kind": "llm",
        "llm_prompt": "Nesnedeki karmaşık iş mantığının (iç içe CASE ifadeleri, çok adımlı "
        "dönüşümler, sihirli sayılar/kodlar, uzun ve çok amaçlı bloklar) yorum satırı ile "
        "açıklanıp açıklanmadığını değerlendir. Yalnızca açıklaması OLMAYAN ve anlaşılması "
        "açıkça zor olan blokları ihlal olarak raporla; blokun başladığı satırı ver.",
        "description": "Karmaşık iş kuralları açıklama olmadan bakımı zorlaştırır ve hatalı "
        "değişikliklere yol açar.",
        "recommendation": "Karmaşık blokların başına amacını ve iş kuralını anlatan kısa yorumlar "
        "ekleyin; gerekirse mantığı daha küçük adımlara bölün.",
    },
    {
        "code": "LLM002",
        "name": "Join koşulu eksikliği (kartezyen çarpım riski)",
        "severity": "high",
        "kind": "llm",
        "llm_prompt": "FROM ifadesinde virgülle ayrılmış tablolar arasında WHERE içinde ilişki "
        "koşulu olmayan, ON koşulu eksik/her zaman doğru (ON 1=1) olan veya bilinçli olmadığı "
        "açıkça anlaşılan CROSS JOIN kullanımlarını bul. Bu durumlar kartezyen çarpıma yol açar. "
        "Küçük sabit kümelerle yapılan bilinçli CROSS JOIN'leri ihlal sayma.",
        "description": "Eksik join koşulu satır sayısını katlayarak hem performansı hem veri "
        "doğruluğunu bozar.",
        "recommendation": "Tablolar arasındaki ilişki koşulunu ANSI JOIN ... ON söz dizimi ile "
        "açıkça yazın.",
    },
]

SEED_GROUPS: list[dict[str, Any]] = [
    {
        "name": "Performans",
        "description": "Sorgu performansını ve kaynak kullanımını etkileyen kurallar.",
        "color": "#2563EB",
        "rules": ["DWH001", "DWH002", "DWH003", "DWH004", "DWH014", "DWH015", "DWH016",
                  "DWH017", "DWH018", "LLM002"],
    },
    {
        "name": "Güvenlik",
        "description": "Güvenlik ve yetki riski taşıyan kullanımlar.",
        "color": "#DC2626",
        "rules": ["DWH005", "DWH012", "DWH019"],
    },
    {
        "name": "Kodlama Standartları",
        "description": "Okunabilirlik, bakım kolaylığı ve standartlara uyum.",
        "color": "#7C3AED",
        "rules": ["DWH001", "DWH006", "DWH007", "DWH008", "DWH009", "DWH010", "DWH011", "LLM001"],
    },
    {
        "name": "Hata Yönetimi",
        "description": "Hata yakalama ve veri bütünlüğü ile ilgili kurallar.",
        "color": "#D97706",
        "rules": ["DWH006", "DWH012", "DWH013"],
    },
]
