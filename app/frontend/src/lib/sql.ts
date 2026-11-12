/**
 * Lightweight T-SQL highlighter. Not a parser: it splits text into colored tokens line by line,
 * carrying block-comment / string state across lines so multi-line constructs color correctly.
 */
export type TokenType = 'kw' | 'type' | 'fn' | 'str' | 'num' | 'com' | 'var' | 'ident' | 'op' | 'text';

export interface Token {
  type: TokenType;
  value: string;
}

const KEYWORDS = new Set(
  `add all alter and any as asc authorization backup begin between break browse bulk by cascade case catch check checkpoint
  close clustered coalesce collate column commit compute constraint contains continue convert create cross current cursor
  database deallocate declare default delete deny desc distinct distributed drop else end errlvl escape except exec execute
  exists exit external fetch file fillfactor for foreign freetext from full function goto grant group having holdlock identity
  identity_insert if in index inner insert intersect into is join key kill left like lineno merge national nocheck nocount
  nonclustered not null nullif of off offsets on open option or order outer output over percent pivot plan precision primary
  print proc procedure public raiserror read readtext reconfigure references replication restore restrict return returns revert
  revoke right rollback rowcount rowguidcol rule save schema select semantickeyphrasetable set setuser shutdown some statistics
  table tablesample textsize then throw to top tran transaction trigger truncate try union unique unpivot update updatetext use
  user values varying view waitfor when where while with within writetext xact_abort nolock readuncommitted recompile matched
  target source partition rows range preceding following unbounded first next only fetch apply cte go`
    .split(/\s+/)
    .filter(Boolean),
);

const TYPES = new Set(
  `bigint int smallint tinyint bit decimal numeric money smallmoney float real date datetime datetime2 datetimeoffset
  smalldatetime time char varchar text nchar nvarchar ntext binary varbinary image uniqueidentifier xml sql_variant
  hierarchyid geometry geography sysname max`
    .split(/\s+/)
    .filter(Boolean),
);

const FUNCTIONS = new Set(
  `count sum avg min max isnull getdate getutcdate sysdatetime dateadd datediff datepart datename year month day cast
  try_cast try_convert len datalength substring left right ltrim rtrim trim upper lower replace charindex patindex
  row_number rank dense_rank ntile lag lead first_value last_value newid scope_identity object_id object_name
  error_message error_number error_line error_severity error_state concat concat_ws string_agg iif choose format
  stuff quotename abs round floor ceiling eomonth`
    .split(/\s+/)
    .filter(Boolean),
);

export interface HighlightState {
  inBlockComment: boolean;
  inString: boolean;
  /** Bracketed identifier spanning lines is rare; we don't carry it. */
}

function classifyWord(word: string, next: string): TokenType {
  const lower = word.toLowerCase();
  if (TYPES.has(lower)) return 'type';
  if (FUNCTIONS.has(lower) && next === '(') return 'fn';
  if (KEYWORDS.has(lower)) return 'kw';
  if (FUNCTIONS.has(lower)) return 'fn';
  return 'text';
}

function push(tokens: Token[], type: TokenType, value: string) {
  if (!value) return;
  const last = tokens[tokens.length - 1];
  if (last && last.type === type) last.value += value;
  else tokens.push({type, value});
}

/** Tokenizes one line, given (and mutating) the cross-line state. */
export function tokenizeLine(line: string, state: HighlightState): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const n = line.length;
  while (i < n) {
    if (state.inBlockComment) {
      const end = line.indexOf('*/', i);
      if (end === -1) {
        push(tokens, 'com', line.slice(i));
        i = n;
      } else {
        push(tokens, 'com', line.slice(i, end + 2));
        i = end + 2;
        state.inBlockComment = false;
      }
      continue;
    }
    if (state.inString) {
      let j = i;
      let closed = false;
      while (j < n) {
        if (line[j] === "'") {
          if (line[j + 1] === "'") {
            j += 2;
            continue;
          }
          closed = true;
          j += 1;
          break;
        }
        j += 1;
      }
      push(tokens, 'str', line.slice(i, j));
      i = j;
      if (closed) state.inString = false;
      continue;
    }
    const ch = line[i];
    const rest2 = line.slice(i, i + 2);
    if (rest2 === '--') {
      push(tokens, 'com', line.slice(i));
      break;
    }
    if (rest2 === '/*') {
      state.inBlockComment = true;
      push(tokens, 'com', '/*');
      i += 2;
      continue;
    }
    if (ch === "'" || ((ch === 'N' || ch === 'n') && line[i + 1] === "'")) {
      const start = i;
      i += ch === "'" ? 1 : 2;
      state.inString = true;
      push(tokens, 'str', line.slice(start, i));
      continue;
    }
    if (ch === '[') {
      const end = line.indexOf(']', i + 1);
      const stop = end === -1 ? n : end + 1;
      push(tokens, 'ident', line.slice(i, stop));
      i = stop;
      continue;
    }
    if (ch === '@') {
      const match = /^@@?[\w#$]*/.exec(line.slice(i));
      const value = match ? match[0] : '@';
      push(tokens, 'var', value);
      i += value.length;
      continue;
    }
    if (/[0-9]/.test(ch) && !/[\w]/.test(line[i - 1] ?? '')) {
      const match = /^(0x[0-9a-f]+|\d+(\.\d+)?(e[+-]?\d+)?)/i.exec(line.slice(i));
      const value = match ? match[0] : ch;
      push(tokens, 'num', value);
      i += value.length;
      continue;
    }
    if (/[A-Za-z_#À-ɏ]/.test(ch)) {
      const match = /^[\w#$À-ɏ]+/.exec(line.slice(i));
      const word = match ? match[0] : ch;
      let k = i + word.length;
      while (line[k] === ' ') k += 1;
      push(tokens, classifyWord(word, line[k] ?? ''), word);
      i += word.length;
      continue;
    }
    if (/[=<>!+\-*/%&|^~,;().]/.test(ch)) {
      push(tokens, 'op', ch);
      i += 1;
      continue;
    }
    push(tokens, 'text', ch);
    i += 1;
  }
  return tokens;
}

export function splitLines(source: string): string[] {
  return source.replace(/\r\n?/g, '\n').split('\n');
}

export function highlightSql(source: string): Token[][] {
  const state: HighlightState = {inBlockComment: false, inString: false};
  return splitLines(source).map((line) => tokenizeLine(line, state));
}

export const TOKEN_CLASS: Record<TokenType, string> = {
  kw: 'text-code-kw font-medium',
  type: 'text-code-type',
  fn: 'text-code-fn',
  str: 'text-code-str',
  num: 'text-code-num',
  com: 'text-code-com italic',
  var: 'text-code-var',
  ident: 'text-fg',
  op: 'text-fg-muted',
  text: 'text-fg',
};

export const SAMPLE_PROCEDURE = `CREATE PROCEDURE dbo.usp_LoadFactSales
    @LoadDate DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- Günlük satış verisini staging tablosundan fact tablosuna aktarır
    IF @LoadDate IS NULL SET @LoadDate = CAST(GETDATE() AS DATE);

    DELETE FROM dwh.FactSales WHERE LoadDate = @LoadDate;

    INSERT INTO dwh.FactSales (SaleId, CustomerKey, ProductKey, Amount, LoadDate)
    SELECT s.*, @LoadDate
    FROM stg.Sales s WITH (NOLOCK)
    LEFT JOIN dwh.DimCustomer c ON c.CustomerCode = s.CustomerCode
    WHERE s.SaleDate = @LoadDate;

    /* TODO: hata yönetimi eklenecek */
    EXEC ('UPDATE dwh.LoadLog SET Status = ''OK'' WHERE LoadDate = ''' + CONVERT(VARCHAR(10), @LoadDate, 120) + '''');
END`;
