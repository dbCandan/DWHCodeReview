import {fireEvent, screen} from '@testing-library/react';
import {useState} from 'react';
import {describe, expect, it, vi} from 'vitest';
import {RuleGroupPicker} from './RuleGroupPicker';
import {RuleSetService} from '@/services/ruleSet';
import {apiError, renderWithSession} from '@/test/render';
import type {RuleSetVersionDetail} from '@/types/sqlReview';

function version(groups: RuleSetVersionDetail['groups']): RuleSetVersionDetail {
  return {
    number: 3,
    published_at: '2026-10-06T10:00:00Z',
    published_by_name: 'Mehmet Kural',
    source: 'arayuz',
    critical: [
      {id: 'Kural01', text: 'a', summary: '', requires_metadata: false, rule_group_ids: ['grp-sec']},
      {id: 'Kural03', text: 'b', summary: '', requires_metadata: false, rule_group_ids: ['grp-perf', 'grp-sec']},
    ],
    normal: [{id: 'Kural09', text: 'c', summary: '', requires_metadata: false, rule_group_ids: ['grp-perf']}],
    groups,
    critical_count: 2,
    normal_count: 1,
  };
}

const GROUPS = [
  {id: 'grp-perf', name: 'Performans', description: ''},
  {id: 'grp-sec', name: 'Güvenlik', description: ''},
];

function Harness({onChange}: {onChange: (ids: string[]) => void}) {
  const [value, setValue] = useState<string[]>([]);
  return (
    <RuleGroupPicker
      value={value}
      disabled={false}
      onChange={(ids) => {
        setValue(ids);
        onChange(ids);
      }}
    />
  );
}

describe('rule group picker of scheduled reviews (rule-group-selection Requirement 4)', () => {
  it('lists the groups with their rule counts; a rule in two groups counts in both', async () => {
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(version(GROUPS));
    renderWithSession(<Harness onChange={() => undefined} />);
    expect(await screen.findByLabelText('Performans (2 kural)')).not.toBeChecked();
    expect(screen.getByLabelText('Güvenlik (2 kural)')).not.toBeChecked();
    expect(screen.getByText('Hiçbir grup seçilmezse tüm kurallar çalışır.')).toBeInTheDocument();
  });

  it('reports one or more selected groups in version order', async () => {
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(version(GROUPS));
    const changes: string[][] = [];
    renderWithSession(<Harness onChange={(ids) => changes.push(ids)} />);
    fireEvent.click(await screen.findByLabelText('Güvenlik (2 kural)'));
    fireEvent.click(screen.getByLabelText('Performans (2 kural)'));
    expect(changes.at(-1)).toEqual(['grp-perf', 'grp-sec']);
    fireEvent.click(screen.getByLabelText('Performans (2 kural)'));
    expect(changes.at(-1)).toEqual(['grp-sec']);
  });

  it('shows nothing when the version has no groups or nothing is published', async () => {
    const latest = vi.spyOn(RuleSetService, 'latest').mockResolvedValue(version([]));
    const {unmount} = renderWithSession(<Harness onChange={() => undefined} />);
    await vi.waitFor(() => expect(latest).toHaveBeenCalled());
    expect(screen.queryByRole('group', {name: 'Kural grupları'})).toBeNull();
    unmount();

    latest.mockRejectedValue(apiError(404, 'no_published_rule_set'));
    renderWithSession(<Harness onChange={() => undefined} />);
    await vi.waitFor(() => expect(latest).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('group', {name: 'Kural grupları'})).toBeNull();
  });
});
