"""Per-rule live-tester samples: each shows violating lines (-- HATA) next to the correct form (-- DOĞRU)."""

SAMPLES = {
"DWH-PART-01": dict(database="EDW", object_name="TRX.ins_SampleTransaction", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleTransaction (@EdwLoadId INT)
AS
BEGIN
    SET NOCOUNT ON;
    -- HATA: >= mantıklı temel prosedür; staging'deki en küçük tarihten sonraki TÜM partition'ları siler
    EXEC EDWUTIL.OPR.spTruncateWithPartitions
         @StgTableName = 'EDWSTG.BOA.TRN_Transaction',
         @EdwTableName = 'EDW.TRX.SampleTransaction',
         @PartitionColumn = 'TranDate',
         @PartitionColumnSource = 'TranDate',
         @PartitionPeriod = 'date',
         @EdwFilterColumn = 'TranDate';

    -- DOĞRU: yalnız staging'de bulunan tarihlerin partition'larını silen IN mantıklı varyant
    -- EXEC EDWUTIL.OPR.spTruncateWithPartitions_withDate @StgTableName = 'EDWSTG.BOA.TRN_Transaction', ...

    INSERT INTO EDW.TRX.SampleTransaction WITH (TABLOCK) (EdwLoadId, TranDate, Amount)
    SELECT @EdwLoadId, STG.TranDate, STG.Amount
    FROM EDWSTG.BOA.TRN_Transaction STG WITH (NOLOCK);
END"""),

"DWH-SCD-01": dict(database="EDWDM", object_name="CON.ins_SampleBalance", object_type="PROCEDURE", sql="""CREATE PROCEDURE CON.ins_SampleBalance (@DataDate DATE)
AS
BEGIN
    DECLARE @DataDateDT DATETIME = @DataDate;

    SELECT A.AccountNumber, B.BranchName, F.FECName
    FROM EDW.CON.Account A WITH (NOLOCK)
    -- DOĞRU: SCD tablo geçerlilik aralığı filtresiyle okunuyor
    INNER JOIN EDW.CHN.Branch B WITH (NOLOCK)
        ON B.BranchId = A.BranchId
       AND @DataDateDT BETWEEN B.EdwValidFrom AND B.EdwValidUntil
    -- HATA: SCD tablo (EDW.COR.LKPFEC) geçerlilik filtresi olmadan okunuyor
    INNER JOIN EDW.COR.LKPFEC F WITH (NOLOCK)
        ON F.FECId = A.FECId
    WHERE @DataDateDT BETWEEN A.EdwValidFrom AND A.EdwValidUntil;
END"""),

"DWH-SCD-02": dict(database="EDWDM", object_name="CUS.ins_SampleCustomer", object_type="PROCEDURE", sql="""CREATE PROCEDURE CUS.ins_SampleCustomer
AS
BEGIN
    SELECT C.CustomerPartyId, C.CustomerName, C.EdwStatus   -- DOĞRU: alanın kendisini seçmek sorun değil
    FROM EDW.PTY.Customer C WITH (NOLOCK)
    WHERE C.EdwStatus = 1;                                  -- HATA: EdwStatus ile güncel kayıt filtresi

    SELECT C.CustomerPartyId
    FROM EDW.PTY.Customer C WITH (NOLOCK)
    WHERE GETDATE() BETWEEN C.EdwValidFrom AND C.EdwValidUntil;   -- DOĞRU: geçerlilik aralığı

    UPDATE T SET EdwValidUntil = GETDATE(), EdwStatus = 0         -- DOĞRU: atama ihlal değil
    FROM EDW.PTY.Customer T
    WHERE T.CustomerPartyId = -1;
END"""),

"DWH-DM-01": dict(database="EDWDM", object_name="CUS.vSampleCustomerInfo", object_type="VIEW", sql="""CREATE VIEW CUS.vSampleCustomerInfo
AS
SELECT C.CustomerPartyId,                 -- DOĞRU: istisna
       C.CustomerPartyNk AS CustomerId,   -- DOĞRU: NK değeri ID adıyla sunuluyor
       C.CustomerName,
       B.BranchId,                        -- HATA: veri ambarı vekil anahtarı son kullanıcıya sunuluyor
       B.BranchNk AS BranchCode,
       I.IdentityOrTAXId AS MaskedIdentityId   -- DOĞRU: LKPIdentityNumber ile bilinçli maskeleme
FROM EDW.PTY.Customer C WITH (NOLOCK)
INNER JOIN EDW.CHN.Branch B WITH (NOLOCK) ON B.BranchId = C.BranchId
LEFT JOIN EDWUTIL.DTG.LKPIdentityNumber I WITH (NOLOCK) ON I.IdentityOrTAXNk = C.IdentityNumber;"""),

"DWH-DM-02": dict(database="EDWDM", object_name="CUS.vSampleCustomerInfoPersonnelExcluded", object_type="VIEW", sql="""CREATE VIEW CUS.vSampleCustomerInfoPersonnelExcluded
AS
-- Not: kolon adı/sıra/tip karşılaştırması katalogdan yapılır; tam sonuç için analiz çalıştırın.
SELECT T1.[DataDate],
       T1.[CustomerPartyId],
       T1.[CustomerId],
       T1.[CustomerName]
FROM [EDWDM].[CUS].[vSampleCustomerInfoOther] T1 WITH (NOLOCK);   -- HATA: asıl view'dan (vSampleCustomerInfo) okumuyor
-- HATA: PersonnelExcluded türevinde WHERE T1.PersonnelFlag = 0 filtresi yok"""),

"DWH-NK-01": dict(database="EDWDM", object_name="CUS.ins_SampleGroupSummary", object_type="PROCEDURE", sql="""CREATE PROCEDURE CUS.ins_SampleGroupSummary
AS
BEGIN
    SELECT R.GroupPartyId,
           MAX(R.GroupPartyNk) AS MaxGroupNk,                     -- HATA: varchar NK üzerinde MAX ('9' > '10')
           MAX(CAST(R.GroupPartyNk AS BIGINT)) AS MaxGroupNo      -- DOĞRU: sayısala çevrilmiş
    FROM EDW.PTY.PartyPartyRelation R WITH (NOLOCK)
    WHERE R.GroupPartyNk > '1000'                                  -- HATA: metinsel büyüktür karşılaştırması
    GROUP BY R.GroupPartyId
    ORDER BY CAST(MAX(R.GroupPartyNk) AS BIGINT);                  -- DOĞRU
END"""),

"DWH-NOLOCK-01": dict(database="EDWDM", object_name="CON.ins_SampleNolock", object_type="PROCEDURE", sql="""CREATE PROCEDURE CON.ins_SampleNolock
AS
BEGIN
    -- Not: tablo/view ayrımı katalogdan yapılır; tam sonuç için analiz çalıştırın.
    SELECT A.AccountNumber, B.BranchName
    FROM EDW.CON.Account A                                -- HATA: fiziksel tablo NOLOCK olmadan okunuyor
    INNER JOIN EDW.CHN.Branch B WITH (NOLOCK)             -- DOĞRU
        ON B.BranchId = A.BranchId
    INNER JOIN #ActiveAccounts T                          -- DOĞRU: temp tabloya NOLOCK konmaz
        ON T.AccountNumber = A.AccountNumber;
END"""),

"DWH-NOLOCK-02": dict(database="EDWDM", object_name="CON.ins_SampleTempRead", object_type="PROCEDURE", sql="""CREATE PROCEDURE CON.ins_SampleTempRead
AS
BEGIN
    INSERT INTO #Accounts WITH (TABLOCK) (AccountNumber)   -- DOĞRU: temp tabloya yazarken TABLOCK
    SELECT A.AccountNumber FROM EDW.CON.Account A WITH (NOLOCK);

    SELECT T.AccountNumber
    FROM #Accounts T WITH (NOLOCK)                          -- HATA: temp tablo NOLOCK ile okunuyor
    INNER JOIN #Limits L (TABLOCK)                           -- HATA: temp tablo TABLOCK ile okunuyor
        ON L.AccountNumber = T.AccountNumber
    INNER JOIN #Branches B                                   -- DOĞRU
        ON B.AccountNumber = T.AccountNumber;
END"""),

"DWH-HINT-01": dict(database="EDWDM", object_name="TRX.ins_SampleHints", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleHints
AS
BEGIN
    SELECT T.TranDate, SUM(T.Amount) AS Amount
    FROM EDW.TRX.CardTransaction T WITH (NOLOCK, INDEX(IX_CardTransaction_TranDate))   -- HATA: INDEX ipucu
    INNER HASH JOIN EDW.CHN.Branch B WITH (NOLOCK)                                       -- HATA: HASH JOIN ipucu
        ON B.BranchId = T.BranchId
    GROUP BY T.TranDate
    OPTION (MAXDOP 8);                                                                   -- HATA: MAXDOP

    SELECT T.TranDate FROM EDW.TRX.CardTransaction T WITH (NOLOCK);                     -- DOĞRU
    -- Not: bilinçli kullanımlar (örn. OPTION (MIN_GRANT_PERCENT = 5)) için kurala istisna tanımlayabilirsiniz.
END"""),

"DWH-JOIN-01": dict(database="EDWDM", object_name="CON.ins_SampleJoinOrder", object_type="PROCEDURE", sql="""CREATE PROCEDURE CON.ins_SampleJoinOrder
AS
BEGIN
    SELECT A.AccountNumber, C.CustomerName, B.BranchName
    FROM EDW.CON.Account A WITH (NOLOCK)
    LEFT JOIN EDW.PTY.Customer C WITH (NOLOCK) ON C.CustomerPartyId = A.CustomerPartyId
    INNER JOIN EDW.CHN.Branch B WITH (NOLOCK) ON B.BranchId = A.BranchId;      -- HATA: LEFT JOIN'den sonra INNER JOIN

    SELECT A.AccountNumber, C.CustomerName, B.BranchName                       -- DOĞRU: önce INNER, sonra LEFT
    FROM EDW.CON.Account A WITH (NOLOCK)
    INNER JOIN EDW.CHN.Branch B WITH (NOLOCK) ON B.BranchId = A.BranchId
    LEFT JOIN EDW.PTY.Customer C WITH (NOLOCK) ON C.CustomerPartyId = A.CustomerPartyId;
END"""),

"DWH-JOIN-02": dict(database="EDWDM", object_name="CON.ins_SampleJoinTypes", object_type="PROCEDURE", sql="""CREATE PROCEDURE CON.ins_SampleJoinTypes
AS
BEGIN
    -- Not: kolon tipleri katalogdan çözülür; tam sonuç için analiz çalıştırın.
    SELECT A.AccountNumber
    FROM EDW.CON.Account A WITH (NOLOCK)
    INNER JOIN EDW.CHN.Branch B WITH (NOLOCK)
        ON B.BranchNk = A.BranchId            -- HATA: varchar Nk = int Id (farklı tip aileleri)
    INNER JOIN EDW.PTY.Customer C WITH (NOLOCK)
        ON C.CustomerPartyId = A.CustomerPartyId;   -- DOĞRU: aynı tip
END"""),

"DWH-ID-01": dict(database="EDWDM", object_name="CON.ins_SampleIdFilter", object_type="PROCEDURE", sql="""CREATE PROCEDURE CON.ins_SampleIdFilter
AS
BEGIN
    -- Not: vekil anahtar tespiti katalogdan yapılır; tam sonuç için analiz çalıştırın.
    SELECT A.AccountNumber
    FROM EDW.CON.Account A WITH (NOLOCK)
    INNER JOIN EDW.COR.LKPFEC F WITH (NOLOCK) ON F.FECId = A.FECId
    WHERE A.FECId = 5                 -- HATA: veri ambarı Id'si sabit değerle filtreleniyor
      AND F.FECNk = '0'               -- DOĞRU: kaynak sistem değeri NK üzerinden
      AND A.BranchId NOT IN (-98, -99);   -- DOĞRU: standart bilinmeyen değerler
END"""),

"DWH-INS-01": dict(database="EDWDM", object_name="TRX.ins_SampleInsertTablock", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleInsertTablock (@EdwLoadId INT)
AS
BEGIN
    -- Not: hedefin fiziksel tablo olduğu katalogdan anlaşılır; tam sonuç için analiz çalıştırın.
    INSERT INTO EDWDM.TRX.SampleSummary (TranDate, Amount)                -- HATA: TABLOCK yok
    SELECT T.TranDate, SUM(T.Amount) FROM EDW.TRX.CardTransaction T WITH (NOLOCK) GROUP BY T.TranDate;

    INSERT INTO EDWDM.TRX.SampleSummary WITH (TABLOCK) (TranDate, Amount) -- DOĞRU
    SELECT T.TranDate, SUM(T.Amount) FROM EDW.TRX.CardTransaction T WITH (NOLOCK) GROUP BY T.TranDate;

    INSERT INTO EDWUTIL.OPR.DMExecutionStepTimeControl (SpName, Step, Time, EdwLoadId)   -- DOĞRU: log tablosu
    VALUES ('TRX.ins_SampleInsertTablock', 1, GETDATE(), @EdwLoadId);
END"""),

"DWH-INS-02": dict(database="EDWDM", object_name="TRX.ins_SampleTempInsert", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleTempInsert
AS
BEGIN
    INSERT INTO #Transactions (TranDate, Amount)                    -- HATA: temp tabloya TABLOCK olmadan insert
    SELECT T.TranDate, T.Amount FROM EDW.TRX.CardTransaction T WITH (NOLOCK);

    INSERT INTO #Transactions WITH (TABLOCK) (TranDate, Amount)     -- DOĞRU
    SELECT T.TranDate, T.Amount FROM EDW.TRX.CardTransaction T WITH (NOLOCK);

    SELECT T.TranDate INTO #Days FROM EDW.TRX.CardTransaction T WITH (NOLOCK);   -- DOĞRU: SELECT INTO
END"""),

"DWH-SQL-01": dict(database="EDWDM", object_name="CUS.ins_SampleDistinct", object_type="PROCEDURE", sql="""CREATE PROCEDURE CUS.ins_SampleDistinct
AS
BEGIN
    SELECT DISTINCT C.CustomerPartyId, C.CustomerName     -- HATA: GROUP BY zaten tekilleştiriyor
    FROM EDW.PTY.Customer C WITH (NOLOCK)
    GROUP BY C.CustomerPartyId, C.CustomerName;

    SELECT COUNT(DISTINCT A.CustomerPartyId)               -- DOĞRU: COUNT(DISTINCT ...)
    FROM EDW.CON.Account A WITH (NOLOCK);
END"""),

"DWH-SQL-02": dict(database="EDWDM", object_name="TRX.ins_SampleSubselect", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleSubselect
AS
BEGIN
    SELECT T.TranDate,
           T.Amount,
           (SELECT TOP 1 R.Rate FROM EDW.COR.FXRate R WITH (NOLOCK)   -- HATA: SELECT listesinde alt sorgu
             WHERE R.FECId = T.FECId AND R.RateDate = T.TranDate) AS FXRate
    FROM EDW.TRX.CardTransaction T WITH (NOLOCK);

    SELECT T.TranDate, T.Amount, R.Rate AS FXRate                               -- DOĞRU: JOIN ile
    FROM EDW.TRX.CardTransaction T WITH (NOLOCK)
    LEFT JOIN EDW.COR.FXRate R WITH (NOLOCK) ON R.FECId = T.FECId AND R.RateDate = T.TranDate;
END"""),

"DWH-SQL-03": dict(database="EDWDM", object_name="TRX.ins_SampleDoubleInsert", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleDoubleInsert (@DataDate DATE)
AS
BEGIN
    -- HATA: final veri seti temp tabloya yazılıp hiçbir işlem yapılmadan hedefe aktarılıyor
    SELECT T.TranDate, T.CustomerPartyId, SUM(T.Amount) AS Amount
    INTO #Final
    FROM EDW.TRX.CardTransaction T WITH (NOLOCK)
    WHERE T.TranDate = @DataDate
    GROUP BY T.TranDate, T.CustomerPartyId;

    INSERT INTO EDWDM.TRX.CustomerDailyAmount WITH (TABLOCK) (TranDate, CustomerPartyId, Amount)
    SELECT TranDate, CustomerPartyId, Amount FROM #Final;
    -- DOĞRU: son SELECT doğrudan hedef tabloya INSERT edilmeli
END"""),

"DWH-SQL-04": dict(database="EDWDM", object_name="CON.ins_SampleCount", object_type="PROCEDURE", sql="""CREATE PROCEDURE CON.ins_SampleCount
AS
BEGIN
    SELECT COUNT(*) AS AccountCount FROM EDW.CON.Account WITH (NOLOCK);    -- HATA
    SELECT COUNT(1) AS AccountCount FROM EDW.CON.Account WITH (NOLOCK);    -- DOĞRU
    IF EXISTS (SELECT * FROM #Accounts) PRINT 'var';                        -- DOĞRU: EXISTS içinde kural dışı
END"""),

"DWH-SQL-05": dict(database="EDWDM", object_name="CUS.ins_SampleUnion", object_type="PROCEDURE", sql="""CREATE PROCEDURE CUS.ins_SampleUnion
AS
BEGIN
    -- HATA: dallar sabit ayırt edici değerle birbirini dışlıyor; UNION ALL yeterli
    SELECT C.CustomerPartyId, 'Bireysel' AS CustomerType
    FROM EDW.PTY.Customer C WITH (NOLOCK) WHERE C.PersonTypeNk = '0'
    UNION
    SELECT C.CustomerPartyId, 'Kurumsal' AS CustomerType
    FROM EDW.PTY.Customer C WITH (NOLOCK) WHERE C.PersonTypeNk = '1';
END"""),

"DWH-SQL-06": dict(database="EDWDM", object_name="TRX.ins_SampleRowNumber", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleRowNumber
AS
BEGIN
    SELECT T.CustomerPartyId,
           ROW_NUMBER() OVER (PARTITION BY T.CustomerPartyId ORDER BY (SELECT NULL)) AS Rn1,   -- HATA: belirsiz sıralama
           ROW_NUMBER() OVER (PARTITION BY T.CustomerPartyId ORDER BY T.SecurityCode) AS Rn2,  -- HATA: metin tipli alan (katalogdan)
           ROW_NUMBER() OVER (PARTITION BY T.CustomerPartyId ORDER BY T.TranDate DESC) AS Rn3  -- DOĞRU: tarih tipli alan
    FROM EDW.TRX.SecurityTransaction T WITH (NOLOCK);
END"""),

"DWH-PERF-01": dict(database="EDWDM", object_name="TRX.ins_SampleSargable", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleSargable (@DataDate DATE)
AS
BEGIN
    SELECT T.TranDate, T.Amount
    FROM EDW.TRX.CardTransaction T WITH (NOLOCK)
    INNER JOIN EDW.CHN.Branch B WITH (NOLOCK)
        ON LTRIM(B.BranchNk) = T.BranchCode                -- HATA: join kolonunda fonksiyon
    INNER JOIN EDW.CON.Card K WITH (NOLOCK)
        ON CAST(K.CardNumber AS VARCHAR(20)) = T.CardNo     -- HATA: EDW tablo kolonunda dönüşüm
    INNER JOIN EDWSTG.BOA.TRN_Card S WITH (NOLOCK)
        ON T.CardNo = CAST(S.CardNumber AS VARCHAR(20))     -- DOĞRU: staging kolonunda dönüşüm istisna (index yok)
    WHERE YEAR(T.TranDate) = 2026                          -- HATA: filtre kolonunda fonksiyon
      AND T.TranDate >= @DataDate                          -- DOĞRU
      AND T.TranDate < DATEADD(DAY, 1, @DataDate);         -- DOĞRU: fonksiyon değişkende
END"""),

"DWH-PERF-02": dict(database="EDWDM", object_name="TRX.vSampleTransactionDaily", object_type="VIEW", sql="""CREATE VIEW TRX.vSampleTransactionDaily
AS
SELECT CONVERT(DATE, T.SystemDate) AS DataDate,                -- HATA: DataDate filtresi SystemDate index'ini kullanamaz
       FORMAT(T.TranDate, 'yyyyMM') AS Period,                 -- HATA: türetilmiş period
       CAST(T.CustomerPartyNk AS BIGINT) AS CustomerId,        -- HATA: dönüştürülmüş çıktı kolonu
       T.TranDate,                                             -- DOĞRU: dönüştürülmeden sunuluyor
       T.Amount
FROM EDW.TRX.CardTransaction T WITH (NOLOCK);"""),

"DWH-PERF-03": dict(database="EDWDM", object_name="TRX.ins_SampleOr", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleOr (@BranchId INT = NULL)
AS
BEGIN
    SELECT T.TranDate, T.Amount
    FROM EDW.TRX.CardTransaction T WITH (NOLOCK)
    INNER JOIN EDW.PTY.Customer C WITH (NOLOCK)
        ON C.CustomerPartyId = T.CustomerPartyId OR C.CustomerPartyNk = T.CustomerCode   -- HATA: JOIN'de OR
    WHERE (@BranchId IS NULL OR T.BranchId = @BranchId)                                  -- HATA: opsiyonel parametre kalıbı
      AND (T.ChannelId = 1 OR T.ChannelId = 2);                                          -- DOĞRU: aynı kolon (IN tercih edilebilir)
END"""),

"DWH-PERF-04": dict(database="EDWDM", object_name="PTY.ins_SampleLike", object_type="PROCEDURE", sql="""CREATE PROCEDURE PTY.ins_SampleLike
AS
BEGIN
    SELECT C.CustomerPartyId, C.CustomerName
    FROM EDW.PTY.Customer C WITH (NOLOCK)
    WHERE C.CustomerName LIKE '%TİCARET%'      -- HATA: başında % olan arama index kullanamaz
       OR C.CustomerName LIKE 'ABC%';          -- DOĞRU: önek araması
END"""),

"DWH-PERF-05": dict(database="EDWDM", object_name="CON.ins_SampleCursor", object_type="PROCEDURE", sql="""CREATE PROCEDURE CON.ins_SampleCursor
AS
BEGIN
    DECLARE @AccountNumber VARCHAR(20);
    DECLARE acc CURSOR LOCAL FAST_FORWARD FOR          -- HATA: satır satır işlem
        SELECT A.AccountNumber FROM EDW.CON.Account A WITH (NOLOCK);
    OPEN acc;
    FETCH NEXT FROM acc INTO @AccountNumber;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        UPDATE EDWDM.CON.AccountSummary SET Checked = 1 WHERE AccountNumber = @AccountNumber;
        FETCH NEXT FROM acc INTO @AccountNumber;
    END
    CLOSE acc; DEALLOCATE acc;
    -- DOĞRU: UPDATE S SET Checked = 1 FROM EDWDM.CON.AccountSummary S INNER JOIN EDW.CON.Account A ...
END"""),

"DWH-PERF-06": dict(database="EDWDM", object_name="CUS.ins_SampleNotIn", object_type="PROCEDURE", sql="""CREATE PROCEDURE CUS.ins_SampleNotIn
AS
BEGIN
    SELECT C.CustomerPartyId
    FROM EDW.PTY.Customer C WITH (NOLOCK)
    WHERE C.CustomerPartyId NOT IN (SELECT A.CustomerPartyId FROM EDW.CON.Account A WITH (NOLOCK));   -- HATA

    SELECT C.CustomerPartyId                                                                         -- DOĞRU
    FROM EDW.PTY.Customer C WITH (NOLOCK)
    WHERE NOT EXISTS (SELECT 1 FROM EDW.CON.Account A WITH (NOLOCK) WHERE A.CustomerPartyId = C.CustomerPartyId);
END"""),

"DWH-PERF-07": dict(database="EDWDM", object_name="CUS.ins_SampleScalarUdf", object_type="PROCEDURE", sql="""CREATE PROCEDURE CUS.ins_SampleScalarUdf
AS
BEGIN
    -- Not: fonksiyonun scalar olduğu katalogdan anlaşılır; tam sonuç için analiz çalıştırın.
    DECLARE @Today DATE = dbo.fnGetBusinessDate(GETDATE());       -- DOĞRU: tek değişkene atama

    SELECT C.CustomerPartyId,
           dbo.fnGetCustomerSegment(C.CustomerPartyId) AS Segment  -- HATA: her satır için scalar UDF
    FROM EDW.PTY.Customer C WITH (NOLOCK);
END"""),

"DWH-PF-01": dict(database="EDWDM", object_name="CUS.vSampleCustomerInfo", object_type="VIEW", sql="""CREATE VIEW CUS.vSampleCustomerInfo
AS
-- Not: kaynakların PersonnelFlag içerip içermediği katalogdan çözülür; tam sonuç için analiz çalıştırın.
SELECT CI.CustomerPartyId,
       CI.CustomerId,
       CI.PersonnelFlag                                      -- DOĞRU: EDWDM kaynağındaki PersonnelFlag kullanılıyor
FROM EDWDM.CUS.CustomerInfo CI WITH (NOLOCK)
LEFT JOIN EDWUTIL.DTG.LKPCustomerParty L WITH (NOLOCK)      -- HATA: EDWDM kaynağı varken LKP tablosu kullanılmamalı
    ON L.CustomerPartyId = CI.CustomerPartyId;"""),

"DWH-PF-02": dict(database="EDWDM", object_name="CUS.ins_SamplePersonnel", object_type="PROCEDURE", sql="""CREATE PROCEDURE CUS.ins_SamplePersonnel
AS
BEGIN
    INSERT INTO EDWDM.CUS.SampleCustomer WITH (TABLOCK) (CustomerPartyId)
    SELECT C.CustomerPartyId
    FROM EDW.PTY.Customer C WITH (NOLOCK)
    LEFT JOIN EDWUTIL.DTG.LKPCustomerParty L WITH (NOLOCK)   -- HATA: PersonnelFlag harici maskeleme mekanizmasıyla dolar
        ON L.CustomerPartyId = C.CustomerPartyId;
END"""),

"DWH-PF-03": dict(database="EDWDM", object_name="CUS.ins_SampleDefaults", object_type="PROCEDURE", sql="""CREATE PROCEDURE CUS.ins_SampleDefaults
AS
BEGIN
    INSERT INTO EDWDM.CUS.SampleCustomer WITH (TABLOCK)   -- HATA: EdwEtlDate/PersonnelFlag default constraint ile dolar
        (CustomerPartyId, CustomerName, EdwEtlDate, PersonnelFlag)
    SELECT C.CustomerPartyId, C.CustomerName, GETDATE(), 0
    FROM EDW.PTY.Customer C WITH (NOLOCK);

    INSERT INTO EDWDM.CUS.SampleCustomer WITH (TABLOCK)
        (CustomerPartyId, CustomerName)                               -- DOĞRU
    SELECT C.CustomerPartyId, C.CustomerName
    FROM EDW.PTY.Customer C WITH (NOLOCK);
END"""),

"DWH-CAL-01": dict(database="EDWDM", object_name="TRX.ins_SampleCalendar", object_type="PROCEDURE", sql="""CREATE PROCEDURE TRX.ins_SampleCalendar (@ReportDate DATE)
AS
BEGIN
    DECLARE @Period INT = CAST(CONVERT(VARCHAR(6), @ReportDate, 112) AS INT);   -- DOĞRU: değişken tanımı kapsam dışı

    SELECT T.TranDate, T.Amount
    FROM EDW.TRX.CardTransaction T WITH (NOLOCK)
    WHERE CONVERT(DATE, T.SystemDate) = @ReportDate;           -- ÖNERİ: kolon dönüştürülerek filtreleniyor

    SELECT T.TranDate, T.Amount                                 -- DOĞRU: Calendar ile aralık join'i
    FROM EDW.TRX.CardTransaction T WITH (NOLOCK)
    INNER JOIN EDW.COR.Calendar C WITH (NOLOCK)
        ON T.SystemDate >= C.CalendarDate AND T.SystemDate < DATEADD(DAY, 1, C.CalendarDate)
    WHERE C.CalendarDate = @ReportDate;
END"""),

"DWH-DATE-01": dict(database="EDWDM", object_name="CON.ins_SampleDateTypes", object_type="PROCEDURE", sql="""CREATE PROCEDURE CON.ins_SampleDateTypes (@DataDate DATE)
AS
BEGIN
    -- Not: kolon tipleri katalogdan çözülür; tam sonuç için analiz çalıştırın.
    DECLARE @DataDateDT DATETIME = @DataDate;

    SELECT A.AccountNumber
    FROM EDW.CON.Account A WITH (NOLOCK)
    WHERE @DataDate BETWEEN A.EdwValidFrom AND A.EdwValidUntil;     -- HATA: DATE değişken ↔ DATETIME alan

    SELECT A.AccountNumber
    FROM EDW.CON.Account A WITH (NOLOCK)
    WHERE @DataDateDT BETWEEN A.EdwValidFrom AND A.EdwValidUntil;   -- DOĞRU
END"""),
}
