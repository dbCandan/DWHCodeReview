import {useQuery} from '@tanstack/react-query';
import {api} from '@/lib/api';

export const qk = {
  dashboard: ['dashboard'] as const,
  rules: ['rules'] as const,
  groups: ['rule-groups'] as const,
  connections: ['connections'] as const,
  analyses: ['analyses'] as const,
  analysis: (id: number) => ['analysis', id] as const,
  findings: (id: number) => ['analysis', id, 'findings'] as const,
  source: (id: number, objectId: number) => ['analysis', id, 'source', objectId] as const,
  llm: ['settings', 'llm'] as const,
  health: ['health'] as const,
  schedules: ['schedules'] as const,
  schedule: (id: number) => ['schedules', id] as const,
  scheduleRuns: (id: number) => ['schedules', id, 'runs'] as const,
  runDiff: (runId: number) => ['scheduled-runs', runId, 'diff'] as const,
  assistantSessions: ['rule-assistant', 'sessions'] as const,
  assistantSession: (id: number) => ['rule-assistant', 'session', id] as const,
  exceptions: (ruleId: number) => ['rule-exceptions', ruleId] as const,
  databases: (id: number) => ['connections', id, 'databases'] as const,
  schemas: (id: number, dbs: string[]) => ['connections', id, 'schemas', [...dbs].sort().join(',')] as const,
};

export const useRules = () => useQuery({queryKey: qk.rules, queryFn: () => api.rules.list()});
export const useGroups = () => useQuery({queryKey: qk.groups, queryFn: api.groups.list});
export const useConnections = () => useQuery({queryKey: qk.connections, queryFn: api.connections.list});
export const useLlmSettings = () => useQuery({queryKey: qk.llm, queryFn: api.llm.get});
export const useAnalyses = () =>
  useQuery({
    queryKey: qk.analyses,
    queryFn: () => api.analyses.list(),
    refetchInterval: (q) => (q.state.data?.some((a) => a.status === 'queued' || a.status === 'running') ? 2000 : false),
  });
export const useHealth = () =>
  useQuery({queryKey: qk.health, queryFn: api.health, refetchInterval: 15000, retry: false, refetchOnWindowFocus: true});
