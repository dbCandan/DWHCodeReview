import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from 'react';
import {describeError, messageForCode} from '@/lib/errorMessages';
import {applyEvent, createProgress, type LiveProgress} from '@/lib/reviewProgress';
import {applyFalsePositive, type FalsePositiveTarget} from '@/lib/reviewResults';
import {ReviewService, type ReviewEventHandler} from '@/services/reviews';
import type {LiveObjectResult, ObjectSelection, ReviewKind, ReviewStreamEvent} from '@/types/sqlReview';

/**
 * The one live review of this browser tab (sql-review object-review Requirement 14, 15, 19 and
 * script-review Requirement 11). It lives above the routes so the progress survives navigation;
 * results stay in memory only and are stored on the server, never in browser storage.
 */
export type ReviewPhase = 'idle' | 'running' | 'completed' | 'failed' | 'cancelled';
export type ReviewView = 'none' | 'live' | 'results';

export const STOPPED_MESSAGE = 'İnceleme durduruldu.';
const DISCONNECTED_MESSAGE = 'Sunucu bağlantısı koptu; inceleme tamamlanamadı.';
const FAILED_MESSAGE = 'İnceleme hata ile sona erdi.';

export interface ReviewSessionState {
  phase: ReviewPhase;
  kind: ReviewKind | null;
  title: string;
  subtitle: string;
  progress: LiveProgress | null;
  results: LiveObjectResult[];
  /** The run is larger than one result page: its results are read from the stored run. */
  resultsOmitted: boolean;
  runId: string | null;
  errorMessage: string | null;
  view: ReviewView;
  /** The results window was opened from the finished live window, which it can return to. */
  resultsFromLive: boolean;
  /** "Analizi durdur" was pressed and the stop request is on its way. */
  stopping: boolean;
  /** The server confirmed the stop: its LLM calls for this run were cut off. */
  stopConfirmed: boolean;
}

type Action =
  | {type: 'start'; kind: ReviewKind; title: string; subtitle: string; objectsTotal: number}
  | {type: 'event'; event: ReviewStreamEvent}
  | {type: 'complete'; runId: string; results: LiveObjectResult[]; resultsOmitted: boolean}
  | {type: 'fail'; message: string}
  | {type: 'cancelled'}
  | {type: 'stopping'}
  | {type: 'stopConfirmed'}
  | {type: 'show'; view: ReviewView; fromLive?: boolean}
  | {type: 'clear'}
  | {type: 'mark'; target: FalsePositiveTarget; value: boolean};

const initialState: ReviewSessionState = {
  phase: 'idle',
  kind: null,
  title: '',
  subtitle: '',
  progress: null,
  results: [],
  resultsOmitted: false,
  runId: null,
  errorMessage: null,
  view: 'none',
  resultsFromLive: false,
  stopping: false,
  stopConfirmed: false,
};

function reducer(state: ReviewSessionState, action: Action): ReviewSessionState {
  switch (action.type) {
    case 'start':
      return {
        ...initialState,
        phase: 'running',
        kind: action.kind,
        title: action.title,
        subtitle: action.subtitle,
        progress: createProgress(action.objectsTotal),
        view: 'live',
      };
    case 'event': {
      if (state.phase !== 'running' || state.progress === null) return state;
      const progress = applyEvent(state.progress, action.event);
      return {...state, progress, runId: progress.runId ?? state.runId};
    }
    case 'complete':
      return {
        ...state,
        phase: 'completed',
        runId: action.runId,
        results: action.results,
        resultsOmitted: action.resultsOmitted,
        errorMessage: null,
      };
    case 'fail':
      return {...state, phase: 'failed', results: [], errorMessage: action.message};
    case 'cancelled':
      // Partial results are neither stored nor shown (object-review Requirement 15).
      return {...state, phase: 'cancelled', results: [], errorMessage: STOPPED_MESSAGE, stopping: false};
    case 'stopping':
      return state.phase === 'running' ? {...state, stopping: true} : state;
    case 'stopConfirmed':
      return {...state, stopConfirmed: true};
    case 'show':
      // A running review may be sent to the background (the dock) but has no results yet.
      if (state.phase === 'running' && action.view === 'results') return state;
      if (action.view === 'results' && state.results.length === 0) return state;
      return {...state, view: action.view, resultsFromLive: action.view === 'results' && Boolean(action.fromLive)};
    case 'clear':
      return state.phase === 'running' ? state : initialState;
    case 'mark':
      return {...state, results: applyFalsePositive(state.results, action.target, action.value)};
  }
}

type Executor = (signal: AbortSignal, onEvent: ReviewEventHandler) => Promise<void>;

interface ReviewSessionValue {
  session: ReviewSessionState;
  /** `ruleCodes` empty runs every rule (rule-group-selection Requirement 4, Decision 6). */
  startObjectReview: (selections: ObjectSelection[], ruleCodes?: string[]) => void;
  startScriptReview: (sql: string, label: string, ruleCodes?: string[]) => void;
  /**
   * "Analizi durdur": asks the server to stop the run, then closes the stream. The request does not
   * rely on a proxy passing the closed connection on (object-review Decision 9).
   */
  stop: () => void;
  showLive: () => void;
  showResults: (fromLive?: boolean) => void;
  closeWindows: () => void;
  clear: () => void;
  /** Record a false-positive mark saved on the server in the live results. */
  applyMark: (target: FalsePositiveTarget, value: boolean) => void;
}

const Context = createContext<ReviewSessionValue | null>(null);

export const SCRIPT_DEFAULT_LABEL = 'Yapıştırılan SQL';

function objectRunTitle(selections: ObjectSelection[]): {title: string; subtitle: string} {
  const databases = [...new Set(selections.map((selection) => selection.database))];
  const database =
    databases.length === 1 ? databases[0] : `${databases.length} veritabanı (${databases.join(', ')})`;
  const targets = selections
    .slice(0, 3)
    .map((selection) => `[${selection.database}] ${selection.schema}.${selection.name} (${selection.type_code})`);
  const subtitle = selections.length <= 3 ? targets.join(', ') : `${targets.join(', ')} +${selections.length - 3}`;
  return {title: `${database} · ${selections.length} nesne`, subtitle};
}

export function ReviewSessionProvider({children}: {children: ReactNode}) {
  const [session, dispatch] = useReducer(reducer, initialState);
  const controllerRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);
  const runIdRef = useRef<string | null>(null);

  // Leaving the signed-in area (sign-out) closes the stream, which stops the run on the server.
  useEffect(
    () => () => {
      generationRef.current += 1;
      controllerRef.current?.abort();
    },
    [],
  );

  const run = useCallback(
    async (kind: ReviewKind, title: string, subtitle: string, objectsTotal: number, execute: Executor) => {
      controllerRef.current?.abort();
      const generation = ++generationRef.current;
      const controller = new AbortController();
      controllerRef.current = controller;
      runIdRef.current = null;
      dispatch({type: 'start', kind, title, subtitle, objectsTotal});
      let finished = false;
      try {
        await execute(controller.signal, (event) => {
          if (generation !== generationRef.current || finished) return;
          if (event.phase === 'complete') {
            finished = true;
            dispatch({
              type: 'complete',
              runId: event.run_id,
              results: event.results,
              resultsOmitted: Boolean(event.results_omitted),
            });
          } else if (event.phase === 'error') {
            finished = true;
            dispatch({type: 'fail', message: messageForCode(event.code) ?? FAILED_MESSAGE});
          } else {
            if (event.phase === 'run_started') runIdRef.current = event.run_id;
            dispatch({type: 'event', event});
          }
        });
        if (generation === generationRef.current && !finished) dispatch({type: 'fail', message: DISCONNECTED_MESSAGE});
      } catch (error) {
        if (generation !== generationRef.current) return;
        if (controller.signal.aborted) dispatch({type: 'cancelled'});
        else dispatch({type: 'fail', message: describeError(error)});
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    },
    [],
  );

  const startObjectReview = useCallback(
    (selections: ObjectSelection[], ruleCodes: string[] = []) => {
      if (selections.length === 0) return;
      const {title, subtitle} = objectRunTitle(selections);
      void run('object', title, subtitle, selections.length, (signal, onEvent) =>
        ReviewService.streamObjectReview(selections, signal, onEvent, ruleCodes),
      );
    },
    [run],
  );

  const startScriptReview = useCallback(
    (sql: string, label: string, ruleCodes: string[] = []) => {
      const trimmedLabel = label.trim();
      void run('script', trimmedLabel || SCRIPT_DEFAULT_LABEL, '', 1, (signal, onEvent) =>
        ReviewService.streamScriptReview(sql, trimmedLabel, signal, onEvent, ruleCodes),
      );
    },
    [run],
  );

  const stop = useCallback(() => {
    const controller = controllerRef.current;
    if (controller === null) return;
    const runId = runIdRef.current;
    if (runId === null) {
      controller.abort();
      return;
    }
    dispatch({type: 'stopping'});
    ReviewService.cancelRun(runId)
      .then(
        () => dispatch({type: 'stopConfirmed'}),
        // A run that has just ended answers 409; closing the stream still stops it.
        () => undefined,
      )
      .finally(() => controller.abort());
  }, []);
  const showLive = useCallback(() => dispatch({type: 'show', view: 'live'}), []);
  const showResults = useCallback((fromLive = false) => dispatch({type: 'show', view: 'results', fromLive}), []);
  const closeWindows = useCallback(() => dispatch({type: 'show', view: 'none'}), []);
  const clear = useCallback(() => dispatch({type: 'clear'}), []);
  const applyMark = useCallback(
    (target: FalsePositiveTarget, value: boolean) => dispatch({type: 'mark', target, value}),
    [],
  );

  const value = useMemo(
    () => ({
      session,
      startObjectReview,
      startScriptReview,
      stop,
      showLive,
      showResults,
      closeWindows,
      clear,
      applyMark,
    }),
    [session, startObjectReview, startScriptReview, stop, showLive, showResults, closeWindows, clear, applyMark],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useReviewSession(): ReviewSessionValue {
  const value = useContext(Context);
  if (!value) throw new Error('useReviewSession must be used inside ReviewSessionProvider');
  return value;
}
