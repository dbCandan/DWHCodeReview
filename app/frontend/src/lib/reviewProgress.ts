import type {ReviewStreamEvent} from '@/types/sqlReview';

/**
 * Pure merge of live review events into a progress snapshot for the live window
 * (sql-review object-review Requirement 14, script-review Requirement 7). Only counters and
 * stages are kept; the model's answer never reaches the browser during the run. A run has no
 * object limit, so the snapshot holds only the objects in flight and the last finished ones;
 * everything else is a counter.
 */
export const RECENT_OBJECTS = 20;

export type ObjectStage = 'pending' | 'fetch' | 'metadata' | 'rules' | 'done' | 'error';
export type RuleStage = 'running' | 'done' | 'failed';

export interface LiveRule {
  ruleId: string;
  tier: 'critical' | 'normal' | null;
  stage: RuleStage;
  completionTokens: number | null;
  totalChars: number;
  twoPart: boolean;
}

export interface LiveObject {
  index: number;
  label: string;
  database: string;
  schema: string;
  name: string;
  typeCode: string;
  stage: ObjectStage;
  sqlLength: number | null;
  rulesTotal: number;
  rulesDone: number;
  ruleOrder: string[];
  rules: Record<string, LiveRule>;
  error: {code: string; message: string} | null;
}

export interface LiveProgress {
  runId: string | null;
  ruleVersion: number | null;
  objectsTotal: number;
  /** Objects reviewed to the end. */
  objectsDone: number;
  /** Objects that ended with an object error. */
  objectsFailed: number;
  /** Objects in flight, by index. */
  objects: Record<number, LiveObject>;
  /** The last finished objects, newest first; at most RECENT_OBJECTS. */
  recent: LiveObject[];
}

export function createProgress(objectsTotal: number): LiveProgress {
  return {runId: null, ruleVersion: null, objectsTotal, objectsDone: 0, objectsFailed: 0, objects: {}, recent: []};
}

type ObjectEvent = Extract<ReviewStreamEvent, {object_index: number}>;

function objectFor(progress: LiveProgress, event: ObjectEvent): LiveObject {
  const existing = progress.objects[event.object_index];
  if (existing) return {...existing, rules: {...existing.rules}, ruleOrder: [...existing.ruleOrder]};
  return {
    index: event.object_index,
    label: event.object_label,
    database: event.database,
    schema: event.schema,
    name: event.name,
    typeCode: event.type_code,
    stage: 'pending',
    sqlLength: null,
    rulesTotal: 0,
    rulesDone: 0,
    ruleOrder: [],
    rules: {},
    error: null,
  };
}

function withRule(object: LiveObject, ruleId: string, update: (rule: LiveRule) => LiveRule): void {
  const current: LiveRule = object.rules[ruleId] ?? {
    ruleId,
    tier: null,
    stage: 'running',
    completionTokens: null,
    totalChars: 0,
    twoPart: false,
  };
  if (!object.ruleOrder.includes(ruleId)) object.ruleOrder.push(ruleId);
  object.rules[ruleId] = update(current);
}

export function applyEvent(progress: LiveProgress, event: ReviewStreamEvent): LiveProgress {
  if (event.phase === 'run_started') {
    return {...progress, runId: event.run_id, ruleVersion: event.rule_version, objectsTotal: event.objects_total};
  }
  if (event.phase === 'complete' || event.phase === 'error' || !('object_index' in event)) return progress;
  // An object that already finished left the in-flight map; a late event for it changes nothing.
  if (event.phase === 'object_done' && !(event.object_index in progress.objects)) return progress;

  const object = objectFor(progress, event);
  switch (event.phase) {
    case 'object_start':
    case 'definition_fetch':
      object.stage = 'fetch';
      break;
    case 'sql_ready':
      object.stage = 'rules';
      object.sqlLength = event.sql_length;
      break;
    case 'metadata_fetch':
      object.stage = 'metadata';
      break;
    case 'metadata_ready':
      object.stage = 'rules';
      break;
    case 'rules_batch_start':
      object.stage = 'rules';
      object.rulesTotal = event.rules_total;
      break;
    case 'rule_start':
      object.stage = 'rules';
      object.rulesTotal = Math.max(object.rulesTotal, event.rules_total);
      withRule(object, event.rule_id, (rule) => ({
        ...rule,
        tier: event.tier,
        stage: 'running',
        twoPart: event.sql_two_part,
        completionTokens: null,
        totalChars: 0,
      }));
      break;
    case 'llm_stream':
      withRule(object, event.rule_id, (rule) => ({
        ...rule,
        completionTokens: event.completion_tokens ?? rule.completionTokens,
        totalChars: event.total_chars,
      }));
      break;
    case 'rule_done':
      object.rulesDone += 1;
      withRule(object, event.rule_id, (rule) => ({
        ...rule,
        tier: event.tier,
        stage: event.ok ? 'done' : 'failed',
        completionTokens: event.completion_tokens ?? rule.completionTokens,
        totalChars: event.total_chars ?? rule.totalChars,
      }));
      break;
    case 'object_error':
      object.stage = 'error';
      object.error = {code: event.code, message: event.message};
      return finished(progress, object);
    case 'object_done':
      object.stage = 'done';
      return finished(progress, object);
  }
  return {...progress, objects: {...progress.objects, [object.index]: object}};
}

/** Move a finished object out of the in-flight map into the short list of recent ones. */
function finished(progress: LiveProgress, object: LiveObject): LiveProgress {
  const objects = {...progress.objects};
  delete objects[object.index];
  const failed = object.stage === 'error';
  return {
    ...progress,
    objectsDone: progress.objectsDone + (failed ? 0 : 1),
    objectsFailed: progress.objectsFailed + (failed ? 1 : 0),
    objects,
    recent: [object, ...progress.recent].slice(0, RECENT_OBJECTS),
  };
}

/** The objects in flight, in selection order. */
export function orderedObjects(progress: LiveProgress): LiveObject[] {
  return Object.values(progress.objects).sort((left, right) => left.index - right.index);
}

/** Share of finished rule calls among the planned ones, 0–1; objects not started yet count as 0. */
export function completionRatio(progress: LiveProgress): number {
  if (progress.objectsTotal === 0) return 0;
  let done = progress.objectsDone + progress.objectsFailed;
  for (const object of Object.values(progress.objects)) {
    if (object.rulesTotal > 0) done += Math.min(object.rulesDone / object.rulesTotal, 0.99);
  }
  return Math.min(done / progress.objectsTotal, 1);
}

/**
 * One line of progress: rules for a single object (a script, or one object), objects otherwise,
 * with the object errors when there are any.
 */
export function progressLine(progress: LiveProgress): string {
  const inFlight = Object.values(progress.objects);
  if (progress.objectsTotal === 1 && inFlight.length === 1 && inFlight[0].rulesTotal > 0)
    return `${inFlight[0].rulesDone} / ${inFlight[0].rulesTotal} kural tamamlandı`;
  const failed = progress.objectsFailed > 0 ? ` · ${progress.objectsFailed} nesnede hata` : '';
  return `${progress.objectsDone} / ${progress.objectsTotal} nesne tamamlandı${failed}`;
}

export function stageLabel(stage: ObjectStage): string {
  switch (stage) {
    case 'fetch':
      return 'Tanım okunuyor';
    case 'metadata':
      return 'Meta veri alınıyor';
    case 'rules':
      return 'İnceleniyor';
    case 'done':
      return 'Tamamlandı';
    case 'error':
      return 'Hata';
    default:
      return 'Bekliyor';
  }
}

/** Token count of a rule call: the server's count, else an estimate from the characters. */
export function tokenLabel(rule: LiveRule): string {
  if (rule.completionTokens !== null && rule.completionTokens > 0)
    return `${rule.completionTokens.toLocaleString('tr-TR')} belirteç`;
  if (rule.totalChars > 0) return `~${Math.max(1, Math.ceil(rule.totalChars / 4)).toLocaleString('tr-TR')} belirteç`;
  return rule.stage === 'running' ? 'Yanıt bekleniyor' : '—';
}
