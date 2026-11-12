import {Fragment, useMemo, useState} from 'react';
import {ChevronDown, ChevronRight, CircleCheck, EyeOff, FileCode2, ListChecks, SearchX, ShieldOff} from 'lucide-react';
import {cn} from '@/lib/utils';
import {formatNumber, matchesSearch} from '@/lib/format';
import {countBySeverity, SEVERITIES, SEVERITY_LABEL, SEVERITY_VAR, SEVERITY_RANK} from '@/lib/severity';
import {groupFindings, type GroupBy} from '@/lib/findings';
import type {AnalysisDetail, AnalysisObject, Finding, Severity} from '@/types';
import {KindBadge, SeverityBadge, TypeBadge} from '@/components/ui/Badge';
import {Button} from '@/components/ui/Button';
import {SearchInput} from '@/components/ui/Input';
import {Select} from '@/components/ui/Select';
import {Chip, Segmented} from '@/components/ui/Tabs';
import {Table, THead, Th, Tr, Td} from '@/components/ui/Table';
import {EmptyState, SkeletonRows} from '@/components/ui/Feedback';
import {SeverityCountsInline} from '@/components/ui/Charts';
import {Tooltip} from '@/components/ui/Tooltip';
import {ExceptionDialog, type ExceptionTarget} from '@/components/rules/ExceptionDialog';
import {ObjectStatusIcon} from './ExecutionPanel';

const PAGE = 150;

export function FindingsTab({
  findings,
  loading,
  analysis,
  onOpenSource,
}: {
  findings: Finding[];
  loading: boolean;
  analysis: AnalysisDetail;
  onOpenSource: (objectId: number, line: number | null) => void;
}) {
  const [severities, setSeverities] = useState<Severity[]>([]);
  const [rule, setRule] = useState('');
  const [objectId, setObjectId] = useState('');
  const [q, setQ] = useState('');
  const [groupBy, setGroupBy] = useState<GroupBy>('none');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set()); // groups start collapsed
  const [limit, setLimit] = useState(PAGE);
  const [exceptionTarget, setExceptionTarget] = useState<{key: number; target: ExceptionTarget} | null>(null);
  const ruleByCode = useMemo(() => new Map(analysis.rules.map((r) => [r.code, r])), [analysis.rules]);
  const objectById = useMemo(() => new Map(analysis.objects.map((o) => [o.id, o])), [analysis.objects]);
  const openException = (f: Finding) => {
    const rule = ruleByCode.get(f.rule_code);
    const o = objectById.get(f.object_id);
    setExceptionTarget({
      key: f.id,
      target: {
        rule: {id: rule?.id ?? null, code: f.rule_code, name: f.rule_name},
        object: o ? {database: o.database, schema: o.schema, name: o.name} : null,
        snippet: f.snippet,
      },
    });
  };

  const counts = useMemo(() => countBySeverity(findings), [findings]);
  const ruleOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const f of findings) map.set(f.rule_code, f.rule_name);
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [findings]);
  const objectOptions = useMemo(() => {
    const ids = new Set(findings.map((f) => f.object_id));
    return analysis.objects.filter((o) => ids.has(o.id));
  }, [findings, analysis.objects]);

  const filtered = useMemo(
    () =>
      findings.filter(
        (f) =>
          (!severities.length || severities.includes(f.severity)) &&
          (!rule || f.rule_code === rule) &&
          (!objectId || f.object_id === Number(objectId)) &&
          matchesSearch(q, f.rule_code, f.rule_name, f.object_label, f.snippet, f.message),
      ),
    [findings, severities, rule, objectId, q],
  );
  const groups = useMemo(() => (groupBy === 'none' ? null : groupFindings(filtered, groupBy)), [filtered, groupBy]);

  const toggleRow = (id: number) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const toggleGroup = (key: string) =>
    setOpenGroups((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  const filtersActive = severities.length > 0 || !!rule || !!objectId || !!q;

  const renderRow = (f: Finding) => {
    const open = expanded.has(f.id);
    return (
      <Fragment key={f.id}>
        <Tr interactive onClick={() => toggleRow(f.id)} className={cn(open && 'bg-surface-2/50')}>
          <Td className="w-8 pr-0">
            {open ? <ChevronDown className="size-3.5 text-fg-subtle" /> : <ChevronRight className="size-3.5 text-fg-subtle" />}
          </Td>
          <Td className="w-24">
            <SeverityBadge severity={f.severity} />
          </Td>
          <Td className="max-w-0 w-[24%]">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[11.5px] font-semibold text-fg">{f.rule_code}</span>
              {f.kind === 'llm' && <KindBadge kind="llm" />}
            </div>
            <div className="truncate text-[11.5px] text-fg-subtle">{f.rule_name}</div>
          </Td>
          <Td className="max-w-0 w-[24%]">
            <span className="block truncate font-mono text-[11.5px] text-fg-muted">{f.object_label}</span>
          </Td>
          <Td className="w-16 font-mono text-[11.5px] text-fg-muted tnum">{f.line ? `L${f.line}` : '—'}</Td>
          <Td className="max-w-0">
            <code className="block truncate rounded bg-surface-2/80 px-1.5 py-0.5 font-mono text-[11.5px] text-fg">{f.snippet || '—'}</code>
          </Td>
          <Td className="w-10 pl-0 text-right" onClick={(e) => e.stopPropagation()}>
            <Tooltip content="İstisna tanımla">
              <Button
                variant="ghost"
                size="xs"
                iconOnly
                aria-label="İstisna tanımla"
                className="opacity-60 group-hover/row:opacity-100 focus-visible:opacity-100"
                onClick={() => openException(f)}
              >
                <ShieldOff className="size-3.5" />
              </Button>
            </Tooltip>
          </Td>
        </Tr>
        {open && (
          <tr>
            <td colSpan={7} className="border-b border-line bg-surface-2/30 px-4 pt-2 pb-4">
              <div className="ml-8 grid gap-3 md:grid-cols-2">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Açıklama</p>
                  <p className="mt-1 text-[12.5px] leading-5 whitespace-pre-wrap text-fg-muted">{f.message || '—'}</p>
                </div>
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Öneri</p>
                  <p className="mt-1 text-[12.5px] leading-5 whitespace-pre-wrap text-fg-muted">{f.recommendation || '—'}</p>
                </div>
                {f.snippet && (
                  <pre className="overflow-x-auto rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[11.5px] leading-5 whitespace-pre-wrap text-fg md:col-span-2">
                    {f.line ? <span className="mr-3 select-none text-fg-subtle">{f.line}</span> : null}
                    {f.snippet}
                  </pre>
                )}
                <div className="flex flex-wrap gap-2 md:col-span-2">
                  <Button size="sm" icon={<FileCode2 className="size-3.5" />} onClick={() => onOpenSource(f.object_id, f.line)}>
                    Kaynakta göster
                  </Button>
                  <Button size="sm" variant="ghost" icon={<ShieldOff className="size-3.5" />} onClick={() => openException(f)}>
                    İstisna tanımla
                  </Button>
                </div>
              </div>
            </td>
          </tr>
        )}
      </Fragment>
    );
  };

  const head = (
    <THead>
      <tr>
        <Th className="w-8 pr-0" />
        <Th className="w-24">Önem</Th>
        <Th>Kural</Th>
        <Th>Nesne</Th>
        <Th className="w-16">Satır</Th>
        <Th>Kod parçası</Th>
        <Th className="w-10" />
      </tr>
    </THead>
  );

  return (
    <div>
      <div className="flex flex-col gap-2.5 border-b border-line p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {SEVERITIES.map((s) => {
            const on = severities.includes(s);
            return (
              <Chip
                key={s}
                active={on}
                onClick={() => setSeverities(on ? severities.filter((x) => x !== s) : [...severities, s])}
              >
                <span className="size-2 rounded-full" style={{background: SEVERITY_VAR[s]}} />
                {SEVERITY_LABEL[s]}
                <span className="text-fg-subtle tnum">{counts[s]}</span>
              </Chip>
            );
          })}
          <span className="ml-auto">
            <Segmented
              size="sm"
              value={groupBy}
              onChange={setGroupBy}
              options={[
                {value: 'none', label: 'Düz liste'},
                {value: 'rule', label: 'Kurala göre'},
                {value: 'object', label: 'Nesneye göre'},
              ]}
            />
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput value={q} onChange={setQ} placeholder="Kod, mesaj, nesne ara…" className="w-full sm:w-64" />
          <Select value={rule} onChange={(e) => setRule(e.target.value)} className="w-52">
            <option value="">Tüm kurallar</option>
            {ruleOptions.map(([code, name]) => (
              <option key={code} value={code}>
                {code} · {name}
              </option>
            ))}
          </Select>
          <Select value={objectId} onChange={(e) => setObjectId(e.target.value)} className="w-60">
            <option value="">Tüm nesneler</option>
            {objectOptions.map((o) => (
              <option key={o.id} value={o.id}>
                {o.schema}.{o.name}
              </option>
            ))}
          </Select>
          {filtersActive && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSeverities([]);
                setRule('');
                setObjectId('');
                setQ('');
              }}
            >
              Temizle
            </Button>
          )}
          <span className="ml-auto flex items-center gap-3 text-xs text-fg-subtle tnum">
            {(analysis.suppressed_count ?? 0) > 0 && (
              <Tooltip content="Kural istisnalarıyla eşleştiği için kaydedilmeyen bulgular">
                <span className="inline-flex items-center gap-1 text-fg-muted">
                  <EyeOff className="size-3.5" />
                  {formatNumber(analysis.suppressed_count ?? 0)} gizlendi
                </span>
              </Tooltip>
            )}
            <span>
              {formatNumber(filtered.length)} / {formatNumber(findings.length)} bulgu
            </span>
          </span>
        </div>
      </div>

      {loading && findings.length === 0 ? (
        <SkeletonRows rows={6} />
      ) : findings.length === 0 ? (
        <EmptyState
          icon={<CircleCheck className="text-ok" />}
          title={analysis.status === 'running' || analysis.status === 'queued' ? 'Henüz bulgu yok' : 'Bulgu bulunamadı'}
          description={
            analysis.status === 'running' || analysis.status === 'queued'
              ? 'Kontroller ilerledikçe bulgular burada belirecek.'
              : 'Seçilen kurallar bu nesnelerde hiçbir ihlal tespit etmedi.'
          }
        />
      ) : filtered.length === 0 ? (
        <EmptyState compact icon={<SearchX />} title="Filtreyle eşleşen bulgu yok" />
      ) : groups ? (
        <Table>
          {head}
          <tbody>
            {groups.map((g) => {
              const collapsed = !openGroups.has(g.key);
              return (
                <Fragment key={g.key}>
                  <tr className="cursor-pointer" onClick={() => toggleGroup(g.key)}>
                    <td colSpan={7} className="border-b border-line bg-surface-2/60 px-4 py-2">
                      <div className="flex items-center gap-2.5">
                        {collapsed ? <ChevronRight className="size-3.5 text-fg-subtle" /> : <ChevronDown className="size-3.5 text-fg-subtle" />}
                        <span className="size-2 rounded-full" style={{background: SEVERITY_VAR[g.severity]}} />
                        <span className={cn('text-[12.5px] font-semibold text-fg', groupBy === 'object' ? 'font-mono' : '')}>
                          {groupBy === 'rule' ? <span className="font-mono">{g.label}</span> : g.label}
                        </span>
                        {g.sublabel && <span className="truncate text-[12.5px] text-fg-muted">{g.sublabel}</span>}
                        <span className="ml-auto flex items-center gap-3">
                          <SeverityCountsInline counts={countBySeverity(g.items)} />
                          <span className="rounded-md bg-surface-3 px-1.5 py-px text-[11px] text-fg-muted tnum">{g.items.length}</span>
                        </span>
                      </div>
                    </td>
                  </tr>
                  {!collapsed && g.items.slice(0, limit).map(renderRow)}
                </Fragment>
              );
            })}
          </tbody>
        </Table>
      ) : (
        <>
          <Table>
            {head}
            <tbody>{filtered.slice(0, limit).map(renderRow)}</tbody>
          </Table>
          {filtered.length > limit && (
            <div className="flex justify-center p-3">
              <Button size="sm" onClick={() => setLimit((l) => l + PAGE)}>
                Daha fazla göster ({formatNumber(filtered.length - limit)} kaldı)
              </Button>
            </div>
          )}
        </>
      )}
      <ExceptionDialog key={exceptionTarget?.key ?? 'none'} target={exceptionTarget?.target ?? null} onClose={() => setExceptionTarget(null)} />
    </div>
  );
}

export function ObjectsTab({analysis, onOpen}: {analysis: AnalysisDetail; onOpen: (o: AnalysisObject) => void}) {
  const [q, setQ] = useState('');
  const [onlyFindings, setOnlyFindings] = useState(false);
  const hasSuppressed = analysis.objects.some((o) => (o.suppressed_count ?? 0) > 0);
  const list = useMemo(
    () =>
      analysis.objects
        .filter((o) => (!onlyFindings || o.finding_count > 0 || o.status === 'error') && matchesSearch(q, o.database, o.schema, o.name))
        .sort((a, b) => b.finding_count - a.finding_count || a.name.localeCompare(b.name)),
    [analysis.objects, q, onlyFindings],
  );
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <SearchInput value={q} onChange={setQ} placeholder="Nesne ara…" className="w-full sm:w-64" />
        <Chip active={onlyFindings} onClick={() => setOnlyFindings(!onlyFindings)}>
          Yalnızca bulgulu / hatalı
        </Chip>
        <span className="ml-auto text-xs text-fg-subtle tnum">
          {list.length} / {analysis.objects.length} nesne
        </span>
      </div>
      {list.length === 0 ? (
        <EmptyState compact icon={<SearchX />} title="Eşleşen nesne yok" />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th className="w-10" />
              <Th>Nesne</Th>
              <Th className="w-20">Tip</Th>
              <Th className="w-20 text-right">Satır</Th>
              <Th className="w-24 text-right">Bulgu</Th>
              {hasSuppressed && <Th className="w-24 text-right">Gizlenen</Th>}
              <Th className="w-[30%]">Durum</Th>
            </tr>
          </THead>
          <tbody>
            {list.map((o) => (
              <Tr key={o.id} interactive onClick={() => onOpen(o)}>
                <Td>
                  <ObjectStatusIcon status={o.status} />
                </Td>
                <Td className="max-w-0">
                  <div className="truncate font-mono text-[12px]">
                    <span className="text-fg-subtle">
                      {o.database}.{o.schema}.
                    </span>
                    <span className="text-fg">{o.name}</span>
                  </div>
                </Td>
                <Td>
                  <TypeBadge type={o.type} />
                </Td>
                <Td className="text-right text-xs text-fg-muted tnum">{formatNumber(o.line_count)}</Td>
                <Td className="text-right">
                  <span className={cn('text-[13px] font-semibold tnum', o.finding_count ? 'text-fg' : 'text-fg-subtle')}>{o.finding_count}</span>
                </Td>
                {hasSuppressed && (
                  <Td className="text-right">
                    {(o.suppressed_count ?? 0) > 0 ? (
                      <Tooltip content={`${o.suppressed_count} bulgu istisna nedeniyle gizlendi`}>
                        <span className="inline-flex items-center gap-1 text-xs text-fg-muted tnum">
                          <EyeOff className="size-3" />
                          {o.suppressed_count}
                        </span>
                      </Tooltip>
                    ) : (
                      <span className="text-xs text-fg-subtle">—</span>
                    )}
                  </Td>
                )}
                <Td className="max-w-0">
                  {o.error ? (
                    <span className="block truncate text-xs text-bad" title={o.error}>
                      {o.error}
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5 text-xs text-fg-subtle">
                      <FileCode2 className="size-3.5" /> Kaynağı görüntüle
                    </span>
                  )}
                </Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  );
}

export function RulesTab({analysis, findings}: {analysis: AnalysisDetail; findings: Finding[]}) {
  const stats = useMemo(() => {
    const byRule = new Map<string, {count: number; objects: Set<number>}>();
    for (const f of findings) {
      let s = byRule.get(f.rule_code);
      if (!s) byRule.set(f.rule_code, (s = {count: 0, objects: new Set()}));
      s.count += 1;
      s.objects.add(f.object_id);
    }
    return analysis.rules
      .map((r) => ({rule: r, count: byRule.get(r.code)?.count ?? 0, objects: byRule.get(r.code)?.objects.size ?? 0}))
      .sort((a, b) => b.count - a.count || SEVERITY_RANK[b.rule.severity] - SEVERITY_RANK[a.rule.severity] || a.rule.code.localeCompare(b.rule.code));
  }, [analysis.rules, findings]);
  const max = Math.max(1, ...stats.map((s) => s.count));
  if (!stats.length) return <EmptyState compact icon={<ListChecks />} title="Kural bilgisi yok" />;
  return (
    <Table>
      <THead>
        <tr>
          <Th className="w-28">Kod</Th>
          <Th>Kural</Th>
          <Th className="w-24">Önem</Th>
          <Th className="w-20">Tür</Th>
          <Th className="w-[28%]">Bulgu</Th>
          <Th className="w-32 text-right">Etkilenen nesne</Th>
        </tr>
      </THead>
      <tbody>
        {stats.map(({rule, count, objects}) => (
          <Tr key={rule.code}>
            <Td className="font-mono text-[12px] font-medium text-fg">{rule.code}</Td>
            <Td className="max-w-0">
              <span className="block truncate text-fg">{rule.name}</span>
            </Td>
            <Td>
              <SeverityBadge severity={rule.severity} />
            </Td>
            <Td>
              <KindBadge kind={rule.kind} />
            </Td>
            <Td>
              <div className="flex items-center gap-2.5">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
                  <div className="h-full rounded-full transition-[width] duration-500" style={{width: `${(count / max) * 100}%`, background: SEVERITY_VAR[rule.severity]}} />
                </div>
                <span className={cn('w-10 text-right text-[13px] font-semibold tnum', count ? 'text-fg' : 'text-fg-subtle')}>{count}</span>
              </div>
            </Td>
            <Td className="text-right text-xs text-fg-muted tnum">
              {objects} / {analysis.object_count}
            </Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}
