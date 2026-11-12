-- Test amaçlı örnek DWH veritabanları ve kurallara takılacak/takılmayacak nesneler.
IF DB_ID('SalesDWH') IS NULL CREATE DATABASE SalesDWH;
IF DB_ID('FinanceDWH') IS NULL CREATE DATABASE FinanceDWH;
GO
USE SalesDWH;
GO
IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg');
IF SCHEMA_ID('dwh') IS NULL EXEC('CREATE SCHEMA dwh');
IF SCHEMA_ID('rpt') IS NULL EXEC('CREATE SCHEMA rpt');
GO
IF OBJECT_ID('stg.Sales') IS NULL CREATE TABLE stg.Sales (SaleId INT IDENTITY PRIMARY KEY, CustomerId INT, Amount DECIMAL(18,2), SaleDate DATE);
IF OBJECT_ID('dwh.FactSales') IS NULL CREATE TABLE dwh.FactSales (SaleKey INT IDENTITY PRIMARY KEY, CustomerKey INT, Amount DECIMAL(18,2), DateKey INT);
IF OBJECT_ID('dwh.DimCustomer') IS NULL CREATE TABLE dwh.DimCustomer (CustomerKey INT IDENTITY PRIMARY KEY, CustomerId INT, Name NVARCHAR(200));
GO
CREATE OR ALTER PROCEDURE stg.usp_LoadSales
AS
BEGIN
    -- SET NOCOUNT ON eksik, SELECT * ve NOLOCK kullanımı
    SELECT * FROM stg.Sales WITH (NOLOCK);
    INSERT INTO dwh.FactSales (CustomerKey, Amount, DateKey)
    SELECT c.CustomerKey, s.Amount, CONVERT(INT, FORMAT(s.SaleDate, 'yyyyMMdd'))
    FROM stg.Sales s JOIN dwh.DimCustomer c ON c.CustomerId = s.CustomerId
    WHERE YEAR(s.SaleDate) = 2023 AND s.SaleDate > '2023-01-01';
    SELECT @@IDENTITY;
END
GO
CREATE OR ALTER PROCEDURE dwh.usp_RebuildFact
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        TRUNCATE TABLE dwh.FactSales;
        DECLARE @sql NVARCHAR(MAX) = N'SELECT COUNT(1) FROM dwh.FactSales';
        EXEC(@sql);
    END TRY
    BEGIN CATCH
        THROW;
    END CATCH
END
GO
CREATE OR ALTER PROCEDURE dwh.sp_CursorLoop
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @id INT;
    DECLARE cur CURSOR FOR SELECT CustomerKey FROM dwh.DimCustomer;
    OPEN cur;
    FETCH NEXT FROM cur INTO @id;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        WAITFOR DELAY '00:00:01';
        FETCH NEXT FROM cur INTO @id;
    END
    CLOSE cur; DEALLOCATE cur;
END
GO
CREATE OR ALTER PROCEDURE dwh.usp_CleanProcedure
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        -- SELECT * yorum satırında, bulgu üretmemeli
        DECLARE @note NVARCHAR(100) = N'SELECT * FROM x WITH (NOLOCK)';
        UPDATE dwh.DimCustomer SET Name = LTRIM(RTRIM(Name)) WHERE CustomerKey > 0;
    END TRY
    BEGIN CATCH
        THROW;
    END CATCH
END
GO
CREATE OR ALTER VIEW rpt.vw_SalesByCustomer
AS
SELECT DISTINCT TOP 100 PERCENT c.Name, f.Amount
FROM dwh.FactSales f, dwh.DimCustomer c
ORDER BY c.Name;
GO
CREATE OR ALTER VIEW rpt.vw_CleanSales
AS
SELECT f.SaleKey, f.Amount, c.Name
FROM dwh.FactSales AS f
INNER JOIN dwh.DimCustomer AS c ON c.CustomerKey = f.CustomerKey;
GO
CREATE OR ALTER FUNCTION dwh.fn_GetCustomerName (@key INT)
RETURNS NVARCHAR(200)
AS
BEGIN
    DECLARE @n NVARCHAR(200);
    SELECT @n = Name FROM dwh.DimCustomer WITH (NOLOCK) WHERE CustomerKey = @key;
    RETURN @n;
END
GO
CREATE OR ALTER FUNCTION rpt.fn_SalesOfYear (@y INT)
RETURNS TABLE
AS
RETURN (SELECT SaleKey, Amount FROM dwh.FactSales WHERE DateKey / 10000 = @y);
GO
USE FinanceDWH;
GO
IF SCHEMA_ID('fin') IS NULL EXEC('CREATE SCHEMA fin');
GO
IF OBJECT_ID('fin.Ledger') IS NULL CREATE TABLE fin.Ledger (Id INT IDENTITY PRIMARY KEY, Account NVARCHAR(50), Amount DECIMAL(18,2), PostDate DATE);
GO
CREATE OR ALTER PROCEDURE fin.usp_PostLedger @account NVARCHAR(50)
AS
BEGIN
    DECLARE @cmd NVARCHAR(400) = N'SELECT * FROM fin.Ledger WHERE Account = ''' + @account + N'''';
    EXEC('SELECT * FROM fin.Ledger WHERE Account = ''' + @account + '''');
    EXEC master..xp_cmdshell 'dir';
    SELECT * INTO #tmp FROM fin.Ledger;
    DROP TABLE #tmp;
END
GO
CREATE OR ALTER VIEW fin.vw_Ledger
AS
SELECT Id, Account, Amount, PostDate FROM fin.Ledger;
GO
