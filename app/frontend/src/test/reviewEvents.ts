import type {LiveObjectResult, ObjectResult, ReviewStreamEvent} from '@/types/sqlReview';

const base = {
  kind: 'object' as const,
  database: 'DWH',
  object_index: 0,
  objects_total: 1,
  object_label: '[DWH] dbo.usp_load (P)',
  schema: 'dbo',
  name: 'usp_load',
  type_code: 'P',
};

/** A complete, contract-shaped event sequence for one object reviewed against two rules. */
export function objectRunEvents(results: LiveObjectResult[] = [liveResult()]): ReviewStreamEvent[] {
  return [
    {phase: 'run_started', run_id: 'run-1', rule_version: 2, objects_total: 1, kind: 'object', all_rules: true, selected_rule_groups: []},
    {...base, phase: 'object_start'},
    {...base, phase: 'definition_fetch'},
    {...base, phase: 'sql_ready', sql_length: 1200},
    {...base, phase: 'rules_batch_start', rules_total: 2},
    {...base, phase: 'rule_start', rule_id: 'Kural01', tier: 'critical', rule_index: 1, rules_total: 2, sql_two_part: false},
    {...base, phase: 'llm_stream', rule_id: 'Kural01', completion_tokens: 12, total_chars: 48},
    {
      ...base,
      phase: 'rule_done',
      rule_id: 'Kural01',
      tier: 'critical',
      rule_index: 1,
      rules_total: 2,
      sql_two_part: false,
      ok: true,
      completion_tokens: 30,
      total_chars: 120,
    },
    {...base, phase: 'rule_start', rule_id: 'Kural03', tier: 'normal', rule_index: 2, rules_total: 2, sql_two_part: false},
    {
      ...base,
      phase: 'rule_done',
      rule_id: 'Kural03',
      tier: 'normal',
      rule_index: 2,
      rules_total: 2,
      sql_two_part: false,
      ok: false,
      completion_tokens: null,
      total_chars: null,
    },
    {...base, phase: 'object_done'},
    {phase: 'complete', run_id: 'run-1', results, results_omitted: false},
  ];
}

export function liveResult(overrides: Partial<LiveObjectResult> = {}): LiveObjectResult {
  return {
    database: 'DWH',
    schema: 'dbo',
    name: 'usp_load',
    object_type: 'PROCEDURE',
    type_code: 'P',
    error_code: null,
    error_message: null,
    parse_warning: null,
    source_sql: 'SELECT 1',
    rule_results: [
      {
        id: 'rr-1',
        rule_id: 'Kural01',
        tier: 'critical',
        status: 'FAIL',
        severity: 'HIGH',
        decision_basis: null,
        description: 'NOLOCK kullanılmış.',
        line_reference: 'Satır 12',
        code_snippet: 'FROM t WITH (NOLOCK)',
        false_positive: false,
      },
      {
        id: 'rr-2',
        rule_id: 'Kural03',
        tier: 'normal',
        status: 'UNKNOWN',
        severity: null,
        decision_basis: null,
        description: 'LLM sunucusu yanıt vermedi (zaman aşımı).',
        line_reference: '',
        code_snippet: '',
        false_positive: false,
      },
      {
        id: 'rr-3',
        rule_id: 'Kural04',
        tier: 'normal',
        status: 'FAIL',
        severity: 'LOW',
        decision_basis: 'metin',
        description: 'Yorum eksik.',
        line_reference: '',
        code_snippet: '',
        false_positive: false,
      },
      {
        id: 'rr-4',
        rule_id: 'Kural05',
        tier: 'normal',
        status: 'NOT_APPLICABLE',
        severity: null,
        decision_basis: null,
        description: '',
        line_reference: '',
        code_snippet: '',
        false_positive: false,
      },
    ],
    findings: [
      {
        id: 'f-1',
        rule_id: 'Kural01',
        severity: 'HIGH',
        description: 'usp_load: NOLOCK kullanılmış.',
        line_reference: 'Satır 12',
        code_snippet: 'FROM t WITH (NOLOCK)',
        false_positive: false,
      },
    ],
    ...overrides,
  };
}

/** The same result as the history detail returns it: without the reviewed SQL text. */
export function storedResult(overrides: Partial<LiveObjectResult> = {}): ObjectResult {
  const result: Partial<LiveObjectResult> = liveResult(overrides);
  delete result.source_sql;
  return result as ObjectResult;
}

/** A fetch response whose body streams the events as `data:` lines with a keep-alive comment. */
export function eventStreamResponse(events: ReviewStreamEvent[], {close = true} = {}): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(': ping\n\n'));
      for (const event of events) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      if (close) controller.close();
    },
  });
  return new Response(body, {status: 200, headers: {'Content-Type': 'text/event-stream'}});
}
