"""The DWH rule sets and the initial LLM settings.

Rule texts come verbatim from the team's specifications: v2 = RULES_SPEC.md (v1.1, the 8
"DWH Standartları" rules), v3 = RULES_SPEC_v13.md (the "DWH Kodlama ve Performans" rules plus
updates to DWH-NOLOCK-02 and DWH-SCD-01). `seed` creates the LLM settings row; the startup
migration calls `apply_ruleset` (ruleset version < 2: replace everything with v2) and
`apply_ruleset_v3` (version < 3: add the v3 rules, update the two v2 rules).
"""

from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import models
from app.rule_samples import SAMPLES

RULESET_VERSION = 7

GROUP = {
    "name": "DWH Standartları",
    "description": "Veri ambarı ekibinin zorunlu kodlama standartları.",
    "color": "#DC2626",
}

_TEXTS: dict[str, dict[str, Any]] = (
{'DWH-PART-01': {'name': 'Partition silme yöntemi standarda uygun değil',
                 'description': "Partition'lı tablolarda veri silme/yenileme, EDWUTIL.OPR "
                                'altındaki standart prosedürlerle veya standart $PARTITION + '
                                'TRUNCATE ... WITH (PARTITIONS) kalıbıyla, tablonun partition '
                                'yapısına uygun biçimde yapılmalıdır.',
                 'recommendation': 'Yüklenen tarih/period kümesi için IN mantığıyla çalışan '
                                   'EDWUTIL.OPR.spTruncateWithPartitions_withDate (date) veya '
                                   '_withPeriod (INT period) kullanın; parametreleri hedef/kaynak '
                                   'tabloyla tutarlı verin; satır içi kalıpta partition fonksiyonu '
                                   'ile partition kolonunun tipini eşleştirin ve IF '
                                   '@PartitionNumber IS NOT NULL kontrolü ekleyin.',
                 'pattern': None,
                 'precondition': '\\$PARTITION|WITH\\s*\\(\\s*PARTITIONS|sp(?:Truncate|Delete)WithPartitions|\\bSWITCH\\b[^;]*\\bPARTITION\\b|\\bDELETE\\b',
                 'name_pattern': None,
                 'llm_prompt': "Bu kural, partition'lı tablolarda veri silme/yenileme işleminin "
                               'veri ambarı standardına uygunluğunu denetler.\n'
                               '\n'
                               'STANDART (uygun kabul edilenler):\n'
                               '- Partition\'a bakmaksızın tüm tabloyu boşaltan düz "TRUNCATE '
                               'TABLE <tablo>" UYGUNDUR, ihlal değildir.\n'
                               "- EDWUTIL.OPR.spTruncateWithPartitions_withDate: staging'de "
                               "bulunan TARİHLERİN partition'larını siler (IN mantığı). "
                               "Date/datetime günlük partition'lı tablolar için kullanılır.\n"
                               "- EDWUTIL.OPR.spTruncateWithPartitions_withPeriod: staging'de "
                               "bulunan PERIOD (INT, örn. 202410) değerlerinin partition'larını "
                               "siler (IN mantığı). INT period partition'lı tablolar için "
                               'kullanılır.\n'
                               '- EDWUTIL.OPR.spDeleteWithPartitions: kriterden ESKİ '
                               "partition'ları siler; yalnızca saklama süresi (retention/arşiv "
                               'temizliği) amacıyla kullanılır.\n'
                               '- EDWDM satır içi kalıp: DECLARE @PartitionNumber INT = '
                               '<db>.$PARTITION.[fn_...](<değer>); IF @PartitionNumber IS NOT NULL '
                               'TRUNCATE TABLE <tablo> WITH(PARTITIONS(@PartitionNumber));\n'
                               '\n'
                               'İHLAL SAY (yalnız bunlar):\n'
                               "1. Yüklenen veri kümesine ait partition'ları yenilemek için IN "
                               'mantıklı prosedür (_withDate/_withPeriod) yerine ">=" mantığıyla '
                               'çalışan EDWUTIL.OPR.spTruncateWithPartitions (son eki olmayan '
                               "temel prosedür) çağrılması. Bu prosedür staging'deki en küçük "
                               "tarihten sonraki TÜM partition'ları siler; staging'de olmayan "
                               "sonraki partition'lar da silinir.\n"
                               '2. Yükleme öncesi temizlik için spDeleteWithPartitions ("<" '
                               'mantığı, retention) kullanılması.\n'
                               '3. Eski/standart dışı kopyaların çağrılması: '
                               'EDW.dbo.spTruncateWithPartitions*, EDW.dbo.spDeleteWithPartitions, '
                               'EDWDM.dbo.spTruncateWithPartitionsNew, EDWArchive.dbo.* veya '
                               'EDWUTIL dışındaki herhangi bir kopya.\n'
                               '4. Prosedür parametrelerinin tutarsız olması: @EdwTableName '
                               'prosedürün INSERT ettiği hedef tablo değil; @StgTableName '
                               "INSERT'ün okuduğu staging kaynağı değil; @PartitionPeriod değeri "
                               "çağrılan varyantla veya KATALOG METADATASI'ndaki partition "
                               "fonksiyonu tipiyle uyumsuz (örn. _withDate ile 'month', INT period "
                               "tabloda 'date'); @PartitionColumn hedef tablonun gerçek partition "
                               'kolonu değil.\n'
                               '5. Partition fonksiyonu / değer tipi uyumsuzluğu: KATALOG '
                               "METADATASI'na göre partition kolonu DATE iken DATETIME parametreli "
                               'partition fonksiyonu kullanılması (veya tersi), ya da '
                               '$PARTITION.fn_...() fonksiyonuna verilen değişkenin tipinin '
                               'fonksiyon parametre tipiyle uyuşmaması (örn. INT period '
                               'fonksiyonuna DATE değişken).\n'
                               '6. $PARTITION.fn_...() fonksiyonunun TRUNCATE edilen tabloya ait '
                               'olmaması (fonksiyon adı/metadatadaki tablo eşleşmiyor).\n'
                               '7. Satır içi TRUNCATE ... WITH(PARTITIONS(@PartitionNumber)) '
                               'öncesinde IF @PartitionNumber IS NOT NULL kontrolünün olmaması.\n'
                               "8. KATALOG METADATASI'na göre partition'lı olan bir tablonun "
                               'yükleme öncesi DELETE FROM ... WHERE <partition kolonu> ... ile '
                               'temizlenmesi (standart truncate yöntemleri yerine).\n'
                               '\n'
                               'Metadata yoksa veya bir tablonun partition bilgisi bilinmiyorsa '
                               '4/5/6/8 için tahmin yürütme, yalnız metinden kesin olanları '
                               'raporla.\n'
                               'reason alanında hangi maddenin ihlal edildiğini ve beklenen doğru '
                               'kullanımı tek cümlede yaz.'},
 'DWH-SCD-01': {'name': 'SCD tablo geçerlilik aralığı filtresi hatalı veya eksik',
                'description': 'SCD (EdwValidFrom/EdwValidUntil kolonlu) tablolardan okuma '
                               'yapılırken, her SCD tablo örneği için doğru geçerlilik aralığı '
                               'filtresi uygulanmalıdır.',
                'recommendation': 'Her SCD tablo referansına ilgili alias ile <tarih> BETWEEN '
                                  'X.EdwValidFrom AND X.EdwValidUntil filtresi ekleyin; tarih için '
                                  'tercihen @DataDate gibi bir parametre, en güncel veri '
                                  'isteniyorsa GETDATE() kullanın. EdwStatus filtresi kullanmayın.',
                'pattern': None,
                'precondition': None,
                'name_pattern': None,
                'llm_prompt': 'Bu kural, SCD (Slowly Changing Dimension) tablolarının geçerlilik '
                              'aralığı kolonlarının (EdwValidFrom, EdwValidUntil) doğru '
                              'kullanımını denetler.\n'
                              'KATALOG METADATASI\'nda "SCD" olarak işaretlenen tablolar SCD '
                              'tablodur. Metadata yoksa EdwValidFrom/EdwValidUntil kullanılan '
                              'tabloları SCD say.\n'
                              '\n'
                              'STANDART:\n'
                              "- Bir SCD tablo FROM/JOIN ile OKUNDUĞUNDA, o tablonun alias'ı "
                              'üzerinden şu filtre bulunmalıdır (ON veya WHERE içinde):\n'
                              '  <tarih> BETWEEN <alias>.EdwValidFrom AND <alias>.EdwValidUntil\n'
                              '  - <tarih> için tercih edilen: @DataDate (veya @ReportDate, '
                              '@DataDateDT gibi tarih parametresi/değişkeni).\n'
                              '  - GETDATE() BETWEEN ... da UYGUNDUR (verinin en güncel hali '
                              'isteniyor demektir).\n'
                              '  - Eşdeğer yazım "<alias>.EdwValidFrom <= <tarih> AND '
                              '<alias>.EdwValidUntil >= <tarih>" uygundur.\n'
                              '- SCD merge/yükleme prosedürlerinde kayıt kapatma (UPDATE ... SET '
                              'EdwValidUntil = DATEADD(SS, -1, ...)) ve yeni kayıt ekleme ihlal '
                              'değildir.\n'
                              '\n'
                              'İHLAL SAY:\n'
                              '1. Okunan bir SCD tablo için geçerlilik filtresinin hiç olmaması '
                              "(aynı tablonun birden fazla alias'la kullanıldığı durumda her alias "
                              'ayrı değerlendirilir).\n'
                              "2. Filtrenin yanlış alias'a uygulanması (örn. SKEY3 tablosunun "
                              'filtresi SKEY2.EdwValidFrom ile yazılmış).\n'
                              '3. Standart dışı kayıt filtreleri: EdwStatus = 1 veya EdwStatus = 0 '
                              'ile (ya da <>, !=, IN eşdeğerleriyle) filtrelemek (EdwStatus '
                              'alanını kolon olarak seçmek veya SET ile atamak ihlal DEĞİLDİR), '
                              "EdwValidUntil IS NULL, EdwValidUntil = '9999-12-31' gibi sabit "
                              'tarih karşılaştırması, sadece EdwValidUntil > GETDATE() (alt sınır '
                              'olmadan).\n'
                              '4. BETWEEN sınırlarının ters yazılması (BETWEEN EdwValidUntil AND '
                              'EdwValidFrom) veya tarih yerine farklı tipte/ilgisiz bir alanın '
                              'kullanılması.\n'
                              '5. Aynı sorguda farklı SCD tablolar için tutarsız tarih kullanımı '
                              '(biri @DataDate, diğeri GETDATE()) — yalnız açıkça tutarsızsa.\n'
                              '\n'
                              "reason alanında SCD tablonun adını/alias'ını ve eksik/hatalı "
                              'filtreyi belirt.'},
 'DWH-SCD-02': {'name': 'EdwStatus ile kayıt filtrelenmiş',
                'description': 'Kayıt seçimi EdwStatus = 1 / EdwStatus = 0 (veya <>, !=, IN '
                               'eşdeğerleri) filtresiyle yapılmamalıdır. EdwStatus alanının '
                               'kendisini kullanmak (kolon listesi, SET ile atama) sorun değildir; '
                               'sorun EdwStatus ile filtrelemektir.',
                'recommendation': 'EdwStatus filtresini kaldırın; güncel kayıt için GETDATE() '
                                  'BETWEEN X.EdwValidFrom AND X.EdwValidUntil, tarihsel kayıt için '
                                  '@DataDate BETWEEN X.EdwValidFrom AND X.EdwValidUntil kullanın.',
                'pattern': "\\b(?:WHERE|AND|OR|ON)\\s+\\(?\\s*(?:\\[?\\w+\\]?\\.)?\\[?EdwStatus\\]?\\s*(?:(?:=|<>|!=)\\s*'?[01]'?(?!\\d)|(?:NOT\\s+)?IN\\s*\\(\\s*'?[01]'?(?:\\s*,\\s*'?[01]'?)*\\s*\\))",
                'precondition': None,
                'name_pattern': None,
                'llm_prompt': None},
 'DWH-DM-01': {'name': "DM view'ında veri ambarına özgü ID değeri sunuluyor",
               'description': "DM katmanındaki asıl view'lar son kullanıcıya veri ambarının "
                              'ürettiği vekil ID/Key değerlerini sunmamalıdır; kaynak sistemdeki '
                              'doğal anahtarlar (NK) ID isimlendirmesiyle sunulmalıdır.',
               'recommendation': 'Kolonu <Ad>Nk AS <Ad>Id şeklinde doğal anahtardan üretin; veri '
                                 'ambarı vekil anahtarını (<Ad>Id/<Ad>Key) çıktıdan kaldırın. '
                                 'CustomerPartyId ve PersonPartyId istisnadır.',
               'pattern': None,
               'precondition': None,
               'name_pattern': '^[^.]+\\.v(?!.*(?:PersonnelMasked|PersonnelExcluded|Masked)$)',
               'llm_prompt': "Bu kural, EDWDM katmanındaki ASIL view'ların son kullanıcıya sunduğu "
                             'kolonları denetler.\n'
                             '\n'
                             'İSİMLENDİRME:\n'
                             '- <Ad>Id (int) kolonları veri ambarının ürettiği vekil anahtarlardır '
                             '(örn. FECId, BranchId, ChannelDetailId kaynak tablodaki int Id '
                             'kolonu).\n'
                             '- <Ad>Nk (çoğunlukla varchar) kolonları kaynak sistemdeki doğal '
                             'anahtarlardır.\n'
                             '- STANDART: Son kullanıcıya doğal anahtar ID isimlendirmesiyle '
                             'sunulur: <alias>.<Ad>Nk AS <Ad>Id veya kaynak sistem numarası (örn. '
                             'a.AccountNumber AS CustomerId).\n'
                             '- İSTİSNA (ihlal değildir): CustomerPartyId ve PersonPartyId '
                             'kolonlarının sunulması.\n'
                             '\n'
                             'İHLAL SAY:\n'
                             "- View'ın EN DIŞ SELECT listesinde (son kullanıcıya dönen kolonlar) "
                             'veri ambarı vekil anahtarının doğrudan sunulması:\n'
                             '  <alias>.<Ad>Id veya <alias>.<Ad>Key (alias ile ya da aliassız), '
                             "kaynağı KATALOG METADATASI'na göre int tipli Id/Key kolonu olan ve "
                             "Nk'dan türetilmemiş kolonlar.\n"
                             "- CTE/alt sorgu içinde kullanılan ama dış SELECT'te sunulmayan "
                             "Id'ler ihlal DEĞİLDİR. JOIN koşullarında Id kullanımı ihlal "
                             'DEĞİLDİR.\n'
                             '- Bir kolon dış katmanda farklı adla sunulsa bile kaynağı veri '
                             "ambarı Id'si ise ihlaldir (örn. b.BranchId AS SubeKodu).\n"
                             "- Nk'dan türetilip Id adıyla sunulan kolonlar UYGUNDUR.\n"
                             '\n'
                             'Emin olmadığın (kaynağı belirlenemeyen) kolonları raporlama. reason '
                             'alanında kolon adını ve doğru NK karşılığını öner.'},
 'DWH-DM-02': {'name': 'Türev view asıl view ile uyumsuz',
               'description': 'v<Ad>Masked / v<Ad>PersonnelExcluded / v<Ad>PersonnelMasked türev '
                              "view'ları asıl v<Ad> view'ından okumalı ve PersonnelFlag dışında "
                              'birebir aynı kolonları (ad, sıra, tip) sunmalıdır.',
               'recommendation': "Türev view'ı asıl view'dan (FROM [EDWDM].[şema].[v<Ad>] T1 "
                                 'WITH(NOLOCK)) üretin, kolon listesini asıl view ile aynı sırada '
                                 'tutun, maskelenen kolonları CAST(NULL AS <asıl tip>) AS [Kolon] '
                                 'ile yazın; Personnel* türevlerde WHERE T1.PersonnelFlag = 0 '
                                 'uygulayın.',
               'pattern': None,
               'precondition': None,
               'name_pattern': '(?:PersonnelMasked|PersonnelExcluded|Masked)$',
               'llm_prompt': None},
 'DWH-NK-01': {'name': 'NK alanı sayısal dönüşüm yapılmadan sıralanıyor/hesaplanıyor',
               'description': 'Metin tipli doğal anahtar (NK) alanları üzerinde sıralama, '
                              'MIN/MAX/AVG/SUM gibi hesaplamalar veya büyük/küçük '
                              'karşılaştırmaları sayısal veri tipine dönüştürülerek yapılmalıdır; '
                              "aksi halde metinsel sıralama yanlış sonuç üretir ('10' < '9').",
               'recommendation': 'İşlemi CAST(<alias>.<Ad>Nk AS INT/BIGINT/DECIMAL) veya '
                                 'TRY_CAST(...) ile sayısal tipe dönüştürerek yapın.',
               'pattern': None,
               'precondition': '(?:ORDER\\s+BY|\\b(?:AVG|MIN|MAX|SUM)\\s*\\(|BETWEEN|[<>])[^;]{0,400}?\\b\\w+Nk\\b|\\b\\w+Nk\\b\\s*(?:[<>]=?|BETWEEN)',
               'name_pattern': None,
               'llm_prompt': 'Bu kural, doğal anahtar (NK) alanlarının (<Ad>Nk, çoğunlukla '
                             'varchar) sayısal anlam taşıyan işlemlerde sayısal tipe dönüştürülüp '
                             'dönüştürülmediğini denetler.\n'
                             '\n'
                             'İHLAL SAY — bir <Ad>Nk alanı aşağıdakilerden birinde '
                             'CAST/TRY_CAST/CONVERT(INT|BIGINT|NUMERIC|DECIMAL|SMALLINT|TINYINT|FLOAT, '
                             '...) olmadan kullanılıyorsa:\n'
                             '- ORDER BY (pencere fonksiyonlarındaki OVER(... ORDER BY ...) '
                             'dahil)\n'
                             '- AVG, SUM, MIN, MAX gibi toplama fonksiyonları\n'
                             '- <, >, <=, >=, BETWEEN karşılaştırmaları (sayısal sabitle veya '
                             'başka bir NK ile)\n'
                             '- Aritmetik işlemler (+, -, *, / — string birleştirme amaçlı + '
                             'hariç)\n'
                             '\n'
                             'İHLAL DEĞİL:\n'
                             '- Eşitlik/eşitsizlik (=, <>, IN) karşılaştırmaları, JOIN '
                             'eşleşmeleri, GROUP BY, DISTINCT, SELECT listesinde düz sunum.\n'
                             "- KATALOG METADATASI'na göre ilgili Nk kolonu zaten sayısal tipteyse "
                             '(int, bigint, decimal, numeric...).\n'
                             '- Dönüşüm daha önce yapılmış bir CTE/alt sorgu kolonu üzerinde işlem '
                             'yapılıyorsa.\n'
                             '- NK değeri açıkça sayısal olmayan bir kod ise (örn. ISOCodeNk, para '
                             'birimi kodu) ve işlem metinsel sıralama amaçlıysa — emin değilsen '
                             'raporlama.\n'
                             '\n'
                             'reason alanında NK alanını ve işlemi belirt.'},
 'DWH-NOLOCK-01': {'name': 'Fiziksel tablo NOLOCK olmadan okunuyor',
                   'description': 'Fiziksel (kalıcı) tablolardan okuma yapılan her FROM/JOIN '
                                  'referansında WITH (NOLOCK) ipucu kullanılmalıdır.',
                   'recommendation': 'Tablo referansına WITH (NOLOCK) ekleyin: FROM '
                                     'EDW.CON.Account A WITH (NOLOCK).',
                   'pattern': None,
                   'precondition': None,
                   'name_pattern': None,
                   'llm_prompt': None},
 'DWH-NOLOCK-02': {'name': 'Temp tablo NOLOCK ile okunuyor',
                   'description': 'Geçici (#temp) tablolar oturuma özeldir; okunurken NOLOCK ipucu '
                                  'kullanılmamalıdır.',
                   'recommendation': 'Temp tablo referansındaki WITH (NOLOCK) ipucunu kaldırın.',
                   'pattern': '#{1,2}\\w+\\]?(?:\\s+(?:AS\\s+)?(?!WITH\\b|ON\\b|WHERE\\b|INNER\\b|LEFT\\b|RIGHT\\b|FULL\\b|CROSS\\b|JOIN\\b|GROUP\\b|ORDER\\b)\\[?\\w+\\]?)?\\s*(?:WITH\\s*)?\\(\\s*(?:NOLOCK|READUNCOMMITTED)\\b',
                   'precondition': None,
                   'name_pattern': None,
                   'llm_prompt': None}})

_TEXTS_V3: dict[str, dict[str, Any]] = (
{'DWH-NOLOCK-02': {'name': 'Temp tablo okumasında NOLOCK/TABLOCK kullanılmış',
                   'description': 'Geçici (#temp) tablolar oturuma özeldir; okunurken (FROM/JOIN) '
                                  'NOLOCK, READUNCOMMITTED veya TABLOCK ipucu kullanılmaz. Temp '
                                  'tabloya INSERT INTO #t WITH (TABLOCK) ile yazmak ise doğrudur '
                                  '(paralel insert / minimal logging sağlar) ve ihlal değildir.',
                   'recommendation': 'Temp tablo okumasındaki ipucunu kaldırın; yalnızca temp '
                                     'tabloya yazarken INSERT INTO #t WITH (TABLOCK) kullanın.',
                   'pattern': '\\b(?:FROM|JOIN)\\s+#{1,2}\\w+\\]?(?:\\s+(?:AS\\s+)?(?!WITH\\b|ON\\b|WHERE\\b|INNER\\b|LEFT\\b|RIGHT\\b|FULL\\b|CROSS\\b|OUTER\\b|JOIN\\b|GROUP\\b|ORDER\\b|UNION\\b)\\[?\\w+\\]?)?\\s*(?:WITH\\s*)?\\(\\s*(?:NOLOCK|READUNCOMMITTED|TABLOCKX?)\\b',
                   'precondition': None,
                   'name_pattern': None,
                   'llm_prompt': None,
                   'builtin_check': None},
 'DWH-HINT-01': {'name': 'Standart dışı sorgu ipucu (MAXDOP, HASH JOIN, INDEX vb.)',
                 'description': 'OPTION(MAXDOP/RECOMPILE/…), HASH/LOOP/MERGE/REMOTE JOIN ipuçları '
                                've INDEX/FORCESEEK/FORCESCAN gibi tablo ipuçları normal şartlarda '
                                'kullanılmaz. Bilinçli eklenmiş istisnalar da raporlanır; '
                                'gerekirse sonradan değerlendirilir.',
                 'recommendation': 'İpucunu kaldırın; gerçekten gerekliyse gerekçesini yorum '
                                   'olarak yazın ve ekip onayı alın.',
                 'pattern': '\\bOPTION\\s*\\((?=[^)]*\\b(?:MAXDOP|RECOMPILE|HASH|LOOP|MERGE|FORCE|OPTIMIZE|USE\\s+HINT|QUERYTRACEON|FAST|KEEP|KEEPFIXED|EXPAND|ROBUST|NO_PERFORMANCE_SPOOL|MAX_GRANT_PERCENT|MIN_GRANT_PERCENT|TABLE\\s+HINT|USE\\s+PLAN|DISABLE_OPTIMIZED_PLAN_FORCING)\\b)|\\b(?:HASH|LOOP|MERGE|REMOTE)\\s+JOIN\\b|\\bWITH\\s*\\((?=[^)]*\\b(?:INDEX\\s*[(=]|FORCESEEK|FORCESCAN|NOEXPAND)\\b)',
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': None},
 'DWH-JOIN-01': {'name': "LEFT JOIN'den sonra INNER JOIN kullanılmış",
                 'description': "Aynı FROM bloğunda INNER JOIN'ler LEFT JOIN'lerden önce "
                                "yazılmalıdır; LEFT JOIN'den sonra gelen INNER JOIN, outer join'in "
                                'sonucunu daraltabilir ve sorgunun anlamını/planını bozar.',
                 'recommendation': "INNER JOIN'leri LEFT JOIN'lerin önüne alın; gerekiyorsa LEFT "
                                   "JOIN'i alt sorgu/CTE içine taşıyın.",
                 'pattern': None,
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': 'left_then_inner_join'},
 'DWH-SQL-01': {'name': 'Gereksiz DISTINCT kullanımı',
                'description': 'DISTINCT yalnızca gerçekten tekrar eden satırları elemek için '
                               'kullanılmalıdır; benzersizliği zaten garanti edilen sorgularda '
                               "gereksiz sıralama/hash maliyeti yaratır ve hatalı join'leri "
                               'gizler.',
                'recommendation': "DISTINCT'i kaldırın; tekrar varsa kaynağını (eksik join koşulu "
                                  'vb.) düzeltin veya GROUP BY ile açıkça toplayın.',
                'pattern': None,
                'precondition': '\\bDISTINCT\\b',
                'name_pattern': None,
                'llm_prompt': 'Bu kural gereksiz DISTINCT kullanımını denetler.\n'
                              'İHLAL SAY (yalnız açıkça gereksizse):\n'
                              "- Seçilen kolonlar arasında KATALOG METADATASI'na göre veya sorgu "
                              'yapısına göre benzersiz olduğu kesin bir anahtar varsa (örn. tek '
                              "tablodan Id/Nk birincil anahtar kolonu seçiliyor ve join'ler satır "
                              'çoğaltmıyor).\n'
                              '- Aynı sorguda GROUP BY ile birlikte DISTINCT (GROUP BY zaten '
                              'tekilleştirir).\n'
                              '- EXISTS / IN alt sorgusu içinde DISTINCT, UNION (ALL olmayan) ile '
                              'birleştirilen dallarda DISTINCT.\n'
                              "İHLAL DEĞİL: COUNT(DISTINCT ...); DISTINCT'in tekrar eden satırları "
                              'gizlemek için bilinçli kullanıldığı durumlar (çoka-çok join sonrası '
                              'tekil liste).\n'
                              'Emin değilsen raporlama. reason alanında neden gereksiz olduğunu '
                              'yaz.',
                'builtin_check': None},
 'DWH-SQL-02': {'name': 'SELECT listesinde alt sorgu (subselect) kullanılmış',
                'description': 'SELECT ile FROM arasındaki kolon listesinde yazılan alt sorgular '
                               'her satır için ayrı çalışabilir ve ciddi performans sorunlarına '
                               'yol açar.',
                'recommendation': 'Alt sorguyu JOIN / OUTER APPLY veya önceden hesaplanan bir '
                                  'CTE/temp tabloya taşıyın.',
                'pattern': None,
                'precondition': None,
                'name_pattern': None,
                'llm_prompt': None,
                'builtin_check': 'select_list_subquery'},
 'DWH-INS-01': {'name': 'Fiziksel tabloya insert WITH (TABLOCK) olmadan yapılmış',
                'description': 'Kalıcı (fiziksel) tablolara toplu INSERT işlemleri WITH (TABLOCK) '
                               'ipucu ile yapılmalıdır (minimal logging / paralel insert).',
                'recommendation': 'INSERT INTO <tablo> WITH (TABLOCK) (kolonlar) SELECT ... '
                                  'şeklinde yazın.',
                'pattern': None,
                'precondition': None,
                'name_pattern': None,
                'llm_prompt': None,
                'builtin_check': 'tablock_physical_insert'},
 'DWH-INS-02': {'name': 'Temp tabloya insert WITH (TABLOCK) olmadan yapılmış',
                'description': 'Geçici (#temp) tablolara INSERT işlemleri WITH (TABLOCK) ipucu ile '
                               'yapılmalıdır; bu ipucu paralel insert ve minimal logging sağlar. '
                               'SELECT ... INTO #t zaten bu avantajlara sahiptir ve ihlal '
                               'değildir; @tablo değişkenleri kapsam dışıdır.',
                'recommendation': 'INSERT INTO #t WITH (TABLOCK) (kolonlar) SELECT ... şeklinde '
                                  'yazın.',
                'pattern': '\\bINSERT\\s+(?:INTO\\s+)?#{1,2}\\w+(?!\\w)(?!\\s*WITH\\s*\\([^)]*\\bTABLOCKX?\\b)',
                'precondition': None,
                'name_pattern': None,
                'llm_prompt': None,
                'builtin_check': None},
 'DWH-SQL-03': {'name': 'Final veri seti temp tablo üzerinden çift insert ediliyor',
                'description': 'Hazırlanan final veri setinin önce bir temp tabloya, ardından '
                               'herhangi bir ek işlem yapılmadan doğrudan hedef tabloya insert '
                               'edilmesi gereksiz çift yazma maliyeti yaratır.',
                'recommendation': "Son SELECT'i doğrudan hedef tabloya INSERT edin; temp tabloyu "
                                  'yalnız ara hesaplamalar için kullanın.',
                'pattern': None,
                'precondition': '(?s)^(?=.*\\bINTO\\s+#)(?=.*\\bINSERT\\s+(?:INTO\\s+)?(?![#@])[\\[\\w])',
                # SCD merge procedures (scd.mrg*) must stage new/changed rows in temp tables
                # before closing target rows; that is the standard pattern, not a double insert.
                'name_pattern': '^(?!scd\\.mrg)',
                'llm_prompt': 'Bu kural "çift insert" durumunu denetler: Final veri seti bir #temp '
                              'tabloya yazılıyor (SELECT ... INTO #t veya INSERT INTO #t),\n'
                              'ardından bu temp tablo, üzerinde başka hiçbir işlem (UPDATE, '
                              'DELETE, ek join, birden fazla kez okunma, index oluşturma, döngü) '
                              'yapılmadan\n'
                              'yalnızca bir kez okunarak ("INSERT INTO <hedef fiziksel tablo> '
                              'SELECT ... FROM #t") hedef tabloya aktarılıyor.\n'
                              'İHLAL SAY: Temp tablonun tek amacının veriyi hedef tabloya taşımak '
                              'olduğu açıksa.\n'
                              'İHLAL DEĞİL: Temp tablo sonradan güncelleniyorsa, birden çok '
                              'kez/başka sorgularda kullanılıyorsa, üzerinde index '
                              'oluşturuluyorsa,\n'
                              'partition truncate öncesinde veri kontrolü/doğrulaması için '
                              'kullanılıyorsa, transaction süresini kısaltmak için açıkça '
                              'ayrılmışsa.\n'
                              'İHLAL DEĞİL: Temp tablo, hedef tablo üzerinde UPDATE/DELETE '
                              'yapılmadan ÖNCE doldurulup bu işlemden SONRA hedefe insert '
                              'ediliyorsa (SCD merge kalıbı: yeni/değişen kayıtlar temp tabloya '
                              'alınır, hedefte eski kayıtlar kapatılır, ardından insert edilir); '
                              'hedef tablo değiştikten sonra aynı seçim yapılamayacağı için temp '
                              'tablo zorunludur. Birden fazla temp tablonun (UNION ile) '
                              'birleştirilerek insert edilmesi de ihlal değildir.\n'
                              'reason alanında temp tablo adını ve hedef tabloyu yaz.',
                'builtin_check': None},
 'DWH-JOIN-02': {'name': "Join'lenen kolonların veri tipleri farklı",
                 'description': 'JOIN koşulunda eşleştirilen kolonların veri tipleri aynı '
                                'olmalıdır (int ↔ varchar, varchar ↔ nvarchar, date ↔ datetime '
                                'gibi farklar örtük dönüşüme ve index kullanılamamasına yol açar).',
                 'recommendation': 'Kaynak tabloda tipleri eşitleyin veya eşleşme için doğru '
                                   'tipteki alanı kullanın.',
                 'pattern': None,
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': 'join_column_type_mismatch'},
 'DWH-PERF-01': {'name': 'Join veya filtre kolonunda dönüşüm/fonksiyon kullanılmış',
                 'description': 'JOIN ON ve WHERE koşullarında kolonun CAST/CONVERT veya fonksiyon '
                                '(YEAR, ISNULL, LTRIM, DATEADD …) içine alınması index kullanımını '
                                'engeller (non-sargable).',
                 'recommendation': 'Dönüşümü kolon yerine karşı tarafa (sabit/değişken) uygulayın, '
                                   'tipleri kaynakta eşitleyin veya hesaplanmış/persisted kolon '
                                   'kullanın; tarih türetmeleri için EDW.COR.Calendar ile join '
                                   'yapın.',
                 'pattern': None,
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': 'non_sargable_predicates'},
 'DWH-PERF-02': {'name': 'View çıktısı kolon dönüşümüyle üretilmiş (index kullanılamaz)',
                 'description': "View'da bir kolonun CAST/CONVERT ile dönüştürülerek sunulması "
                                '(örn. CONVERT(DATE, SystemDate) AS DataDate), view bu kolon '
                                "üzerinden filtrelendiğinde alttaki kolonun index'inin "
                                'kullanılmasını engeller.',
                 'recommendation': 'Kolonu dönüştürmeden sunun veya filtre için kaynakta uygun '
                                   'tipte bir kolon/persisted computed column oluşturun.',
                 'pattern': '\\b(?:CONVERT|TRY_CONVERT)\\s*\\(\\s*\\w+(?:\\s*\\(\\s*(?:\\d+|MAX)(?:\\s*,\\s*\\d+)?\\s*\\))?\\s*,\\s*(?!NULL\\b)(?:\\[?\\w+\\]?\\.)?\\[?[A-Za-z_]\\w*\\]?\\s*(?:,\\s*\\d+\\s*)?\\)\\s*(?:AS\\s+)?\\[?\\w+\\]?\\s*(?=,|\\bFROM\\b|$)|\\b(?:CAST|TRY_CAST)\\s*\\(\\s*(?!NULL\\b)(?:\\[?\\w+\\]?\\.)?\\[?[A-Za-z_]\\w*\\]?\\s+AS\\s+\\w+(?:\\s*\\(\\s*(?:\\d+|MAX)(?:\\s*,\\s*\\d+)?\\s*\\))?\\s*\\)\\s*(?:AS\\s+)?\\[?\\w+\\]?\\s*(?=,|\\bFROM\\b|$)',
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': None},
 'DWH-PERF-03': {'name': 'JOIN veya WHERE koşulunda OR kullanılmış',
                 'description': 'JOIN koşullarında ve farklı kolonları birbirine bağlayan WHERE '
                                'koşullarında OR kullanımı index kullanımını engeller ve sorguyu '
                                'belirgin şekilde yavaşlatır; sorguyu UNION ALL ile iki ayrı '
                                'sorguya bölmek genellikle çok daha hızlıdır.',
                 'recommendation': "OR'u kaldırıp sorguyu UNION ALL ile birleştirilen ayrı "
                                   'sorgulara bölün; aynı kolon için çoklu değerde IN kullanın.',
                 'pattern': None,
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': 'or_in_predicates'},
 'DWH-PERF-04': {'name': 'LIKE başında joker karakter (%) ile kullanılmış',
                 'description': "LIKE '%...' biçimindeki aramalar index kullanamaz ve tabloyu "
                                'baştan sona tarar.',
                 'recommendation': "Mümkünse aramayı LIKE 'değer%' biçimine çevirin veya tam "
                                   'eşitlik/ayrı arama kolonu kullanın.',
                 'pattern': "\\bLIKE\\s+N?'%",
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': None},
 'DWH-PERF-05': {'name': 'CURSOR ile satır satır işlem',
                 'description': 'CURSOR ile satır satır işlem küme tabanlı (set-based) sorgulara '
                                'göre çok yavaştır.',
                 'recommendation': 'İşlemi küme tabanlı INSERT/UPDATE/MERGE sorgularıyla yazın.',
                 'pattern': '\\bDECLARE\\s+@?\\w+\\s+CURSOR\\b|\\bCURSOR\\s+(?:LOCAL|GLOBAL|FORWARD_ONLY|SCROLL|STATIC|KEYSET|DYNAMIC|FAST_FORWARD|READ_ONLY|FOR)\\b',
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': None},
 'DWH-PERF-06': {'name': 'NOT IN (SELECT ...) kullanılmış',
                 'description': 'NOT IN alt sorgusu NULL değerlerde beklenmedik sonuç verir ve '
                                "genellikle NOT EXISTS'e göre kötü plan üretir.",
                 'recommendation': 'NOT EXISTS (SELECT 1 FROM ... WHERE ...) veya LEFT JOIN ... IS '
                                   'NULL kullanın.',
                 'pattern': '\\bNOT\\s+IN\\s*\\(\\s*SELECT\\b',
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': None},
 'DWH-PERF-07': {'name': 'Sorgu içinde scalar fonksiyon (UDF) çağrılmış',
                 'description': 'SELECT/WHERE/JOIN içinde çağrılan kullanıcı tanımlı scalar '
                                'fonksiyonlar her satır için çalışır ve paralelliği engeller.',
                 'recommendation': 'Fonksiyon mantığını sorguya (JOIN/CASE) veya inline '
                                   'table-valued fonksiyona taşıyın.',
                 'pattern': None,
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': 'scalar_udf_in_query'},
 'DWH-SQL-04': {'name': 'COUNT(*) kullanılmış',
                'description': 'Ekip standardı gereği satır sayımında COUNT(1) kullanılır.',
                'recommendation': 'COUNT(*) yerine COUNT(1) yazın.',
                'pattern': '\\bCOUNT(?:_BIG)?\\s*\\(\\s*\\*\\s*\\)',
                'precondition': None,
                'name_pattern': None,
                'llm_prompt': None,
                'builtin_check': None},
 'DWH-SQL-05': {'name': 'Gereksiz UNION (UNION ALL yerine)',
                'description': 'UNION, dallar arasındaki tekrarları elemek için tüm sonucu '
                               'sıralar/tekilleştirir; tekrar oluşamayan veya tekrarın önemsiz '
                               'olduğu durumlarda UNION ALL kullanılmalıdır.',
                'recommendation': 'Dallar birbirini dışlıyorsa veya tekrar sorun değilse UNION ALL '
                                  'kullanın.',
                'pattern': None,
                'precondition': '\\bUNION\\b(?!\\s+ALL\\b)',
                'name_pattern': None,
                'llm_prompt': 'Bu kural ALL olmadan yazılmış UNION kullanımını denetler.\n'
                              'İHLAL SAY: Dallar birbirini açıkça dışlıyorsa (her dalda farklı '
                              'sabit ayırt edici kolon değeri, ayrık WHERE koşulları, farklı '
                              'kaynak tabloların farklı anahtarları),\n'
                              'sonuç zaten sonradan GROUP BY/DISTINCT ile tekilleştiriliyorsa veya '
                              'UNION bir EXISTS/IN alt sorgusunda kullanılıyorsa.\n'
                              'İHLAL DEĞİL: Dallar aynı satırı üretebiliyor ve tekrarların '
                              'elenmesi işlevsel olarak gerekli görünüyorsa. Emin değilsen '
                              'raporlama.\n'
                              "reason alanında neden UNION ALL'ın yeterli olduğunu yaz.",
                'builtin_check': None},
 'DWH-SQL-06': {'name': 'ROW_NUMBER/RANK ORDER BY alanı sıralamaya uygun değil',
                'description': 'ROW_NUMBER, RANK, DENSE_RANK, NTILE pencere fonksiyonlarının ORDER '
                               'BY alanı sıralamaya uygun (sayısal, tarih) bir tipte olmalıdır; '
                               "metin tipli alanlarla sıralama ('10' < '9') veya sabit/(SELECT "
                               'NULL) ile sıralama belirsiz/yanlış sonuç üretir.',
                'recommendation': "ORDER BY'da sayısal/tarih tipli bir alan kullanın veya alanı "
                                  'CAST(... AS INT/BIGINT) ile sayısala çevirin.',
                'pattern': None,
                'precondition': None,
                'name_pattern': None,
                'llm_prompt': None,
                'builtin_check': 'window_order_by_type'},
 'DWH-DATE-01': {'name': 'Tarih parametresi/değişkeni ile karşılaştırılan alanın veri tipi farklı',
                 'description': 'Tarih parametresi veya değişkeni, '
                                'karşılaştırıldığı/ilişkilendirildiği alanla aynı veri tipinde '
                                'olmalıdır (örn. DATE parametre ile DATETIME alan, DATE ile INT '
                                'period). Farklı tipler örtük dönüşüme, hatalı aralık sonuçlarına '
                                '(gün sonu saatleri) ve index kullanılamamasına yol açar.',
                 'recommendation': 'Alanın tipinde ayrı bir değişken tanımlayın (örn. DECLARE '
                                   '@DataDateDT DATETIME = @DataDate) veya karşılaştırmayı '
                                   'EDW.COR.Calendar üzerinden doğru tipteki alanla (CalendarDate, '
                                   'CalendarDateDT, Period) yapın.',
                 'pattern': None,
                 'precondition': None,
                 'name_pattern': None,
                 'llm_prompt': None,
                 'builtin_check': 'date_variable_type_mismatch'},
 'DWH-ID-01': {'name': 'Sabit değer filtresi Id alanı üzerinden yapılmış',
               'description': 'Kaynak sisteme ait özel değerlere göre filtreleme, veri ambarının '
                              'ürettiği Id (vekil anahtar) alanları üzerinden değil, kaynak '
                              'sistemdeki doğal anahtar (Nk) alanları üzerinden yapılmalıdır; Id '
                              'değerleri ortamlar arasında ve yeniden yüklemelerde değişebilir.',
               'recommendation': 'Filtreyi <Ad>Nk alanı ve kaynak sistemdeki değerle yazın (örn. '
                                 "FECId = 5 yerine FECNk = '...').",
               'pattern': "(?<![@\\w])(?:\\[?\\w+\\]?\\.)?\\[?(?!Edw)(?!CustomerPartyId\\b|PersonPartyId\\b)\\w+Id\\]?\\s*(?:(?:=|<>|!=|>=|<=|>|<)\\s*(?!'?-99'?(?![\\d.]))(?!'?-1'?(?![\\d.]))(?:N?'[^']*'|-?\\d+)(?![\\w.])|(?:NOT\\s+)?IN\\s*\\(\\s*(?!'?-99'?\\s*\\))(?:N?'[^']*'|-?\\d+))",
               'precondition': None,
               'name_pattern': None,
               'llm_prompt': None,
               'builtin_check': None},
 'DWH-PF-01': {'name': "Asıl view'da PersonnelFlag kaynağı standarda uygun değil",
               'description': "Personnel* türevleri olan EDWDM asıl view'ları PersonnelFlag "
                              'kolonunu sunmalıdır. View EDWDM altındaki müşteri bilgisi içeren '
                              'bir tablodan/nesneden okuyorsa PersonnelFlag oradan alınmalı ve '
                              'EDWUTIL.DTG LKP tabloları kullanılmamalıdır; doğrudan EDW '
                              'tablolarından okuyorsa PersonnelFlag EDWUTIL.DTG.LKPCustomerParty / '
                              'LKPPersonParty / LKPIdentityNumber tablolarıyla hesaplanmalıdır.',
               'recommendation': "EDWDM kaynağı varsa PersonnelFlag'i o kaynaktan alın ve LKP "
                                 "join'lerini kaldırın; yoksa EDWUTIL.DTG LKP tablolarıyla "
                                 'PersonnelFlag hesaplayın.',
               'pattern': None,
               'precondition': None,
               'name_pattern': '^[^.]+\\.v(?!.*(?:PersonnelMasked|PersonnelExcluded|Masked)$)',
               'llm_prompt': None,
               'builtin_check': 'personnel_flag_view_source'},
 'DWH-PF-02': {'name': 'EDWDM prosedüründe PersonnelFlag LKP tablosu kullanılmış',
               'description': 'EDWDM prosedürleri PersonnelFlag için EDWUTIL.DTG LKP tablolarını '
                              'kullanmamalıdır; PersonnelFlag, EDWUTIL.DTG.MaskingExecutionLog '
                              'tablosunu dolduran harici maskeleme mekanizması tarafından günlük '
                              'akışta güncellenir.',
               'recommendation': "LKP tablo kullanımını kaldırın; PersonnelFlag'i prosedürde "
                                 'hesaplamayın.',
               'pattern': '\\bDTG\\]?\\s*\\.\\s*\\[?LKP(?:CustomerParty|PersonParty|IdentityNumber)(?:History)?\\b',
               'precondition': None,
               'name_pattern': None,
               'llm_prompt': None,
               'builtin_check': None},
 'DWH-PF-03': {'name': 'EdwEtlDate/PersonnelFlag alanına insert yapılmış',
               'description': 'EDWDM tablolarında EdwEtlDate ve PersonnelFlag alanları tablo '
                              'üzerindeki default constraint ile dolar; prosedürlerde bu alanlara '
                              'değer insert edilmemelidir.',
               'recommendation': 'INSERT kolon listesinden EdwEtlDate ve PersonnelFlag alanlarını '
                                 "(ve SELECT'teki karşılıklarını) kaldırın.",
               'pattern': '\\bINSERT\\s+(?:INTO\\s+)?(?![#@])(?:\\[?\\w+\\]?\\s*\\.\\s*){0,2}\\[?\\w+\\]?(?:\\s+WITH\\s*\\([^)]*\\))?\\s*\\([^)]*?\\b(?:EdwEtlDate|PersonnelFlag)\\b',
               'precondition': None,
               'name_pattern': None,
               'llm_prompt': None,
               'builtin_check': None},
 'DWH-CAL-01': {'name': 'Tarih/period türetmesi EDW.COR.Calendar yerine dönüşümle yapılmış',
                'description': 'Period (yyyymm), gün numarası (yyyymmdd), çeyrek, hafta, gün adı, '
                               'iş günü gibi tarih türetmeleri tarih alanlarının dönüştürülmesi '
                               '(CONVERT(...,112), FORMAT, YEAR*100+MONTH, DATEPART, DATENAME) '
                               'yerine EDW.COR.Calendar tablosuyla ilişkilendirilerek '
                               'yapılmalıdır.',
                'recommendation': 'EDW.COR.Calendar ile CalendarDate (date) / CalendarDateDT '
                                  '(datetime) üzerinden join yapıp Period, DateValue, YearValue, '
                                  'MonthValue, QuarterValue, WeekValue, DayNameValue, NextWorkday, '
                                  'PreviousWorkday alanlarını kullanın.',
                'pattern': "\\bCONVERT\\s*\\(\\s*N?(?:VAR)?CHAR\\s*\\(\\s*[468]\\s*\\)\\s*,[^;]{1,150}?,\\s*112\\s*\\)|\\bFORMAT\\s*\\([^;]{1,150}?,\\s*N?'(?:yyyyMM|yyyyMMdd|yyyy-MM|MM)'|\\bYEAR\\s*\\([^()]*(?:\\([^()]*\\))?[^()]*\\)\\s*\\*\\s*100\\s*\\+\\s*MONTH\\s*\\(|\\bDATEPART\\s*\\(\\s*(?:QUARTER|QQ|Q|WEEK|WK|WW|WEEKDAY|DW|DAYOFYEAR|DY|ISO_WEEK|ISOWK)\\s*,|\\bDATENAME\\s*\\(",
                'precondition': None,
                'name_pattern': None,
                'llm_prompt': None,
                'builtin_check': None}})

# Per-rule behaviour of the v2 set (everything except the texts above).
_SETTINGS: dict[str, dict[str, Any]] = {
    "DWH-PART-01": {"kind": "llm", "object_types": ["PROCEDURE"], "requires_metadata": True},
    "DWH-SCD-01": {
        "kind": "llm",
        "requires_metadata": True,
        "metadata_precondition": "references_scd_table",
    },
    "DWH-SCD-02": {"kind": "regex"},
    "DWH-DM-01": {
        "kind": "llm",
        "object_types": ["VIEW"],
        "databases": ["EDWDM"],
        "requires_metadata": True,
    },
    "DWH-DM-02": {
        "kind": "builtin",
        "builtin_check": "derived_view_consistency",
        "object_types": ["VIEW"],
        "databases": ["EDWDM"],
    },
    "DWH-NK-01": {"kind": "llm", "requires_metadata": True},
    "DWH-NOLOCK-01": {"kind": "builtin", "builtin_check": "nolock_physical_tables"},
    "DWH-NOLOCK-02": {"kind": "regex"},
}

# ------------------------------------------------------------------ v3 (RULES_SPEC_v13.md)
GROUP_V3 = {
    "name": "DWH Kodlama ve Performans",
    "description": "Veri ambarı ekibinin önemli kodlama ve performans kuralları.",
    "color": "#D97706",
}

_SCD_TABLE_LINE = (
    "KATALOG METADATASI'nda \"SCD\" olarak işaretlenen tablolar SCD tablodur. "
    "Metadata yoksa EdwValidFrom/EdwValidUntil kullanılan tabloları SCD say."
)
_SCD_ONLY_MARKED = (
    "KATALOG METADATASI verildiyse YALNIZ 'SCD' işaretli tabloları SCD say; EdwValidFrom kolonu "
    "olup SCD işaretli olmayan tablolar (örn. EDWSKEY anahtar tabloları, EDWLRY tabloları) SCD "
    "değildir, onlar için filtre arama."
)
assert _SCD_TABLE_LINE in _TEXTS["DWH-SCD-01"]["llm_prompt"]

_FIELDS_V3_UPDATE = ("name", "description", "recommendation", "pattern")

# Changes v3 makes to rules of the v2 set (applied by the migration and to fresh installs).
V3_UPDATES: dict[str, dict[str, Any]] = {
    "DWH-NOLOCK-02": {f: _TEXTS_V3["DWH-NOLOCK-02"][f] for f in _FIELDS_V3_UPDATE},
    "DWH-SCD-01": {
        "llm_prompt": _TEXTS["DWH-SCD-01"]["llm_prompt"].replace(
            _SCD_TABLE_LINE, f"{_SCD_TABLE_LINE}\n{_SCD_ONLY_MARKED}"
        )
    },
}

_PROC = {"object_types": ["PROCEDURE"]}
_EDWDM_PROC = {"object_types": ["PROCEDURE"], "databases": ["EDWDM"]}

_SETTINGS_V3: dict[str, dict[str, Any]] = {
    "DWH-HINT-01": {"kind": "regex"},
    "DWH-JOIN-01": {"kind": "builtin"},
    "DWH-SQL-01": {"kind": "llm", "requires_metadata": True},
    "DWH-SQL-02": {"kind": "builtin"},
    "DWH-INS-01": {"kind": "builtin", **_PROC},
    "DWH-INS-02": {"kind": "regex"},
    "DWH-SQL-03": {
        "kind": "llm",
        **_PROC,
        # Spec pattern plus (?!INTO\b): otherwise "INSERT INTO #t" matched with INTO as the target.
        "precondition": r"(?s)^(?=.*\bINTO\s+#)"
        r"(?=.*\bINSERT\s+(?:INTO\s+)?(?!INTO\b)(?![#@])[\[\w])",
    },
    "DWH-JOIN-02": {"kind": "builtin"},
    "DWH-PERF-01": {"kind": "builtin"},
    "DWH-PERF-02": {"kind": "regex", "object_types": ["VIEW"]},
    "DWH-PERF-03": {"kind": "builtin"},
    "DWH-PERF-04": {"kind": "regex", "ignore_comments": False},
    "DWH-PERF-05": {"kind": "regex"},
    "DWH-PERF-06": {"kind": "regex"},
    "DWH-PERF-07": {"kind": "builtin"},
    "DWH-SQL-04": {"kind": "regex"},
    "DWH-SQL-05": {"kind": "llm"},
    "DWH-SQL-06": {"kind": "builtin"},
    "DWH-DATE-01": {"kind": "builtin"},
    "DWH-ID-01": {"kind": "regex"},
    "DWH-PF-01": {"kind": "builtin", "object_types": ["VIEW"], "databases": ["EDWDM"]},
    "DWH-PF-02": {"kind": "regex", **_EDWDM_PROC},
    "DWH-PF-03": {"kind": "regex", **_EDWDM_PROC},
    "DWH-CAL-01": {"kind": "regex"},
}

_DEFAULTS: dict[str, Any] = {
    "match_mode": "match",
    "target": "definition",
    "ignore_case": True,
    "ignore_comments": True,
    "enabled": True,
    "object_types": [],
    "databases": [],
    "requires_metadata": False,
    "builtin_check": None,
    "metadata_precondition": None,
    "precondition": None,
    "name_pattern": None,
    "llm_prompt": None,
    "pattern": None,
}

# ------------------------------------------------------------------ v4 (RULES_SPEC_v14.md)
# Field updates of five rules after the first real EDWDM/EDWBridge analyses. The migration
# writes only these fields, so other user edits of the rules survive.
V4_UPDATES: dict[str, dict[str, Any]] = {
    "DWH-INS-01": {
        "description": _TEXTS_V3["DWH-INS-01"]["description"]
        + " Tek satırlık INSERT ... VALUES ve EDWUTIL log/kontrol tabloları kapsam dışıdır.",
    },
    "DWH-PF-01": {
        "description": (
            "Personnel* türevleri olan ve müşteriyi tanımlayan bir kolon (CustomerPartyId / "
            "PersonPartyId) sunan EDWDM asıl view'ları PersonnelFlag kolonunu sunmalıdır. View "
            "EDWDM altındaki müşteri bilgisi içeren bir tablodan/nesneden okuyorsa PersonnelFlag "
            "oradan alınmalı ve EDWUTIL.DTG.LKPCustomerParty / LKPPersonParty tabloları "
            "kullanılmamalıdır (LKPIdentityNumber kimlik maskeleme amaçlı kullanılabilir); "
            "doğrudan EDW tablolarından okuyorsa PersonnelFlag EDWUTIL.DTG.LKPCustomerParty / "
            "LKPPersonParty / LKPIdentityNumber tablolarıyla hesaplanmalıdır."
        ),
        "recommendation": (
            "EDWDM kaynağı varsa PersonnelFlag'i o kaynaktan alın ve LKPCustomerParty / "
            "LKPPersonParty join'lerini kaldırın (LKPIdentityNumber kimlik maskeleme amaçlı "
            "kullanılabilir); yoksa EDWUTIL.DTG LKP tablolarıyla PersonnelFlag hesaplayın."
        ),
    },
    "DWH-ID-01": {
        "kind": "builtin",
        "builtin_check": "id_literal_filter",
        "pattern": None,
        "description": _TEXTS_V3["DWH-ID-01"]["description"]
        + " Vekil anahtar tespiti katalogdan yapılır.",
    },
    "DWH-CAL-01": {
        "kind": "builtin",
        "builtin_check": "calendar_date_predicate",
        "pattern": None,
        "severity": "low",
        "name": "Tarih kolonu dönüştürülerek filtrelenmiş (Calendar aralık join'i önerilir)",
        "description": (
            "Sorgu bloklarındaki (WHERE/ON) tarih kolonlarının CONVERT/CAST/FORMAT/YEAR-MONTH "
            "gibi dönüşümlerle karşılaştırılması index kullanımını engeller. Performans için "
            "tarih kolonunu dönüştürmeden EDW.COR.Calendar ile aralık join'i kurmak önerilir. "
            "Değişken tanımları (DECLARE/SET) ve SELECT listesindeki tarih türetmeleri kapsam "
            "dışıdır."
        ),
        "recommendation": (
            "Kolonu dönüştürmek yerine EDW.COR.Calendar ile `X.Tarih >= C.CalendarDate AND "
            "X.Tarih < DATEADD(DAY, 1, C.CalendarDate)` biçiminde aralık join'i kurun (period "
            "için C.Period üzerinden filtreleyip aynı aralığı kullanın)."
        ),
    },
}

# DWH-PERF-02 v4 (spec 7b): date derivations of a column in view output columns too.
_P2_COL = r"(?!NULL\b)(?:\[?\w+\]?\.)?\[?[A-Za-z_]\w*\]?"
_P2_ALIAS = r"\s*(?:AS\s+)?\[?\w+\]?\s*(?=,|\bFROM\b|$)"
_P2_TYPE = r"\w+(?:\s*\(\s*(?:\d+|MAX)(?:\s*,\s*\d+)?\s*\))?"
_PERF02_DATE_DERIVATIONS = "|".join(
    (
        rf"\bFORMAT\s*\(\s*{_P2_COL}\s*,[^()]*\){_P2_ALIAS}",
        rf"\b(?:YEAR|MONTH|EOMONTH)\s*\(\s*{_P2_COL}\s*\)"
        rf"(?:\s*\*\s*100\s*\+\s*MONTH\s*\(\s*{_P2_COL}\s*\))?{_P2_ALIAS}",
        rf"\b(?:DATEADD|DATEPART)\s*\(\s*\w+\s*,(?:\s*-?\d+\s*,)?\s*{_P2_COL}\s*\){_P2_ALIAS}",
        rf"\b(?:CAST|TRY_CAST)\s*\(\s*(?:TRY_)?CONVERT\s*\(\s*{_P2_TYPE}\s*,\s*{_P2_COL}"
        rf"\s*(?:,\s*\d+\s*)?\)\s+AS\s+{_P2_TYPE}\s*\){_P2_ALIAS}",
    )
)
V4_UPDATES["DWH-PERF-02"] = {
    "pattern": f"{_TEXTS_V3['DWH-PERF-02']['pattern']}|{_PERF02_DATE_DERIVATIONS}",
}

# ------------------------------------------------------------------ v5 (user decision, v1.5)
_DM01_EXCEPTION_LINE = (
    "- İSTİSNA (ihlal değildir): CustomerPartyId ve PersonPartyId kolonlarının sunulması."
)
_DM01_MASKED_IDS = (
    "- İSTİSNA (ihlal değildir): EDWUTIL.DTG LKP tablolarından (LKPIdentityNumber, "
    "LKPCustomerParty, LKPPersonParty ve *History) gelen ve Masked… adıyla sunulan Id kolonları "
    "(örn. I.IdentityOrTAXId AS MaskedIdentityId, I2.IdentityOrTAXId AS MaskedTaxNumberId); "
    "bunlar kimlik bilgisini gizlemek için bilinçli olarak sunulur (maskeleme)."
)
assert _DM01_EXCEPTION_LINE in _TEXTS["DWH-DM-01"]["llm_prompt"]
V5_UPDATES: dict[str, dict[str, Any]] = {
    "DWH-DM-01": {
        "llm_prompt": _TEXTS["DWH-DM-01"]["llm_prompt"].replace(
            _DM01_EXCEPTION_LINE, f"{_DM01_EXCEPTION_LINE}\n{_DM01_MASKED_IDS}"
        )
    },
}

# Current definitions: the v2 set with the v3/v4/v5 updates, then the v3 additions (with v4).
V2_RULES: list[dict[str, Any]] = [
    {
        **_DEFAULTS,
        "code": code,
        "severity": "critical",
        **texts,
        **_SETTINGS[code],
        **V3_UPDATES.get(code, {}),
        **V4_UPDATES.get(code, {}),
        **V5_UPDATES.get(code, {}),
    }
    for code, texts in _TEXTS.items()
]
V3_RULES: list[dict[str, Any]] = [
    {
        **_DEFAULTS,
        "code": code,
        "severity": "high",
        **{k: v for k, v in _TEXTS_V3[code].items() if v is not None},
        **_SETTINGS_V3[code],
        **V4_UPDATES.get(code, {}),
    }
    for code in _SETTINGS_V3
]
def sample_fields(code: str) -> dict[str, Any]:
    """Live-tester sample columns of a seeded rule (empty when no sample exists)."""
    sample = SAMPLES.get(code)
    if not sample:
        return {}
    return {
        "sample_sql": sample["sql"],
        "sample_object_name": sample.get("object_name"),
        "sample_object_type": sample.get("object_type"),
        "sample_database": sample.get("database"),
    }


SEED_RULES: list[dict[str, Any]] = [
    {**data, **sample_fields(data["code"])} for data in V2_RULES + V3_RULES
]


def build_rule(data: dict[str, Any]) -> models.Rule:
    return models.Rule(
        code=data["code"],
        name=data["name"],
        description=data.get("description", ""),
        recommendation=data.get("recommendation", ""),
        severity=data["severity"],
        kind=data.get("kind", "regex"),
        pattern=data.get("pattern"),
        match_mode=data.get("match_mode", "match"),
        target=data.get("target", "definition"),
        ignore_case=data.get("ignore_case", True),
        ignore_comments=data.get("ignore_comments", True),
        llm_prompt=data.get("llm_prompt"),
        object_types=list(data.get("object_types", [])),
        enabled=data.get("enabled", True),
        builtin_check=data.get("builtin_check"),
        precondition=data.get("precondition"),
        metadata_precondition=data.get("metadata_precondition"),
        requires_metadata=bool(data.get("requires_metadata", False)),
        databases=list(data.get("databases", [])),
        name_pattern=data.get("name_pattern"),
        sample_sql=data.get("sample_sql"),
        sample_object_name=data.get("sample_object_name"),
        sample_object_type=data.get("sample_object_type"),
        sample_database=data.get("sample_database"),
    )


def apply_ruleset(session: Session) -> None:
    """v2: replace every rule and rule group with the DWH standards set (caller commits).

    Analysis history keeps its rule snapshots; their link to the deleted rules is cleared so
    that reused ids never point at an unrelated new rule.
    """
    session.execute(update(models.AnalysisRule).values(rule_id=None))
    session.execute(delete(models.rule_group_members))
    session.execute(delete(models.Rule))
    session.execute(delete(models.RuleGroup))
    session.flush()
    rules = [build_rule({**data, **sample_fields(data["code"])}) for data in V2_RULES]
    session.add_all(rules)
    session.add(models.RuleGroup(**GROUP, rules=rules))
    session.flush()


def apply_ruleset_v3(session: Session) -> None:
    """v3: add the missing v3 rules and their group; update DWH-NOLOCK-02 and DWH-SCD-01.

    Other rules (including user-created ones and user edits) are left alone (caller commits).
    """
    existing = {rule.code: rule for rule in session.scalars(select(models.Rule))}
    for code, changes in V3_UPDATES.items():
        rule = existing.get(code)
        if rule is not None:
            for field, value in changes.items():
                setattr(rule, field, value)
    added = [
        build_rule({**data, **sample_fields(data["code"])})
        for data in V3_RULES if data["code"] not in existing
    ]
    session.add_all(added)
    group = session.scalar(select(models.RuleGroup).where(models.RuleGroup.name == GROUP_V3["name"]))
    if group is None:
        group = models.RuleGroup(**GROUP_V3)
        session.add(group)
    group.rules = list(group.rules) + [r for r in added if r not in group.rules]
    session.flush()


def apply_ruleset_v4(session: Session) -> None:
    """v4: write the `V4_UPDATES` fields of the listed rules (caller commits)."""
    for rule in session.scalars(select(models.Rule).where(models.Rule.code.in_(V4_UPDATES))):
        for field, value in V4_UPDATES[rule.code].items():
            setattr(rule, field, value)
    session.flush()


def apply_ruleset_v5(session: Session) -> None:
    """v5: write the `V5_UPDATES` fields (DWH-DM-01 llm_prompt) (caller commits)."""
    for rule in session.scalars(select(models.Rule).where(models.Rule.code.in_(V5_UPDATES))):
        for field, value in V5_UPDATES[rule.code].items():
            setattr(rule, field, value)
    session.flush()


# ------------------------------------------------------------------ v7: topic groups
# Created by the user on the live DB (RULE_ASSISTANT_SPEC "Ek: konu grupları").
TOPIC_GROUPS: list[dict[str, Any]] = [
    {"name": "Hızlı Tarama (LLM'siz)",
     "description": "Tüm regex ve yerleşik kurallar; LLM çağrısı yapmaz, büyük analizler için.",
     "color": "#0EA5E9",
     "rules": ["DWH-CAL-01", "DWH-DATE-01", "DWH-DM-02", "DWH-HINT-01", "DWH-ID-01",
               "DWH-INS-01", "DWH-INS-02", "DWH-JOIN-01", "DWH-JOIN-02", "DWH-NOLOCK-01",
               "DWH-NOLOCK-02", "DWH-PERF-01", "DWH-PERF-02", "DWH-PERF-03", "DWH-PERF-04",
               "DWH-PERF-05", "DWH-PERF-06", "DWH-PERF-07", "DWH-PF-01", "DWH-PF-02",
               "DWH-PF-03", "DWH-SCD-02", "DWH-SQL-02", "DWH-SQL-04", "DWH-SQL-06"]},
    {"name": "LLM Kuralları",
     "description": "Model ile yorumlanan kurallar; seçili nesnelerde derin inceleme için (yavaş).",
     "color": "#8B5CF6",
     "rules": ["DWH-DM-01", "DWH-NK-01", "DWH-PART-01", "DWH-SCD-01", "DWH-SQL-01",
               "DWH-SQL-03", "DWH-SQL-05"]},
    {"name": "Partition ve Yükleme",
     "description": "Partition truncate/silme ve hedef tablolara yükleme standartları.",
     "color": "#F97316",
     "rules": ["DWH-INS-01", "DWH-INS-02", "DWH-PART-01", "DWH-PF-03", "DWH-SQL-03"]},
    {"name": "SCD ve Tarih",
     "description": "SCD geçerlilik aralığı, EdwStatus ve tarih değişkeni/Calendar kullanımı.",
     "color": "#14B8A6",
     "rules": ["DWH-CAL-01", "DWH-DATE-01", "DWH-SCD-01", "DWH-SCD-02"]},
    {"name": "Anahtarlar (Id / Nk)",
     "description": "Vekil (Id) ve doğal (Nk) anahtarların doğru kullanımı.",
     "color": "#EAB308",
     "rules": ["DWH-DM-01", "DWH-ID-01", "DWH-JOIN-02", "DWH-NK-01", "DWH-SQL-06"]},
    {"name": "Kilit ve Sorgu İpuçları",
     "description": "NOLOCK / TABLOCK kullanımı ve standart dışı sorgu ipuçları.",
     "color": "#64748B",
     "rules": ["DWH-HINT-01", "DWH-INS-01", "DWH-INS-02", "DWH-NOLOCK-01", "DWH-NOLOCK-02"]},
    {"name": "DM Katmanı ve PersonnelFlag",
     "description": "EDWDM view/prosedür standartları, türev view uyumu ve PersonnelFlag.",
     "color": "#EC4899",
     "rules": ["DWH-DM-01", "DWH-DM-02", "DWH-PERF-02", "DWH-PF-01", "DWH-PF-02", "DWH-PF-03"]},
    {"name": "Sorgu Performansı",
     "description": "Index kullanımını ve sorgu planını etkileyen kullanımlar.",
     "color": "#22C55E",
     "rules": ["DWH-CAL-01", "DWH-JOIN-01", "DWH-JOIN-02", "DWH-PERF-01", "DWH-PERF-02",
               "DWH-PERF-03", "DWH-PERF-04", "DWH-PERF-05", "DWH-PERF-06", "DWH-PERF-07",
               "DWH-SQL-01", "DWH-SQL-02", "DWH-SQL-05"]},
    {"name": "Kod Yazım Standartları",
     "description": "Okunabilirlik ve ekip yazım standartları.",
     "color": "#06B6D4",
     "rules": ["DWH-JOIN-01", "DWH-SQL-02", "DWH-SQL-04", "DWH-SQL-06"]},
]


def apply_ruleset_v7(session: Session) -> None:
    """v7: create the topic groups that do not exist yet (by name); existing ones are kept."""
    existing = set(session.scalars(select(models.RuleGroup.name)))
    rules = {rule.code: rule for rule in session.scalars(select(models.Rule))}
    for group in TOPIC_GROUPS:
        if group["name"] in existing:
            continue
        session.add(
            models.RuleGroup(
                name=group["name"], description=group["description"], color=group["color"],
                rules=[rules[code] for code in group["rules"] if code in rules],
            )
        )
    session.flush()


def apply_ruleset_v6(session: Session) -> None:
    """v6: fill the live-tester sample of rules that have none (user samples are kept)."""
    for rule in session.scalars(select(models.Rule).where(models.Rule.code.in_(SAMPLES))):
        if rule.sample_sql and rule.sample_sql.strip():
            continue
        for field, value in sample_fields(rule.code).items():
            setattr(rule, field, value)
    session.flush()


def seed(session: Session) -> None:
    if session.get(models.LlmSettings, 1) is None:
        session.add(models.LlmSettings(id=1))
    session.commit()
