import {fireEvent, screen, within} from '@testing-library/react';
import {useState} from 'react';
import {describe, expect, it, vi} from 'vitest';
import {RuleSelectionPicker} from './RuleSelectionPicker';
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
      {id: 'Kural01', text: 'NOLOCK kullanma.', summary: '', requires_metadata: false, rule_group_ids: ['grp-sec']},
      {id: 'Kural03', text: 'Yıldız kullanma.', summary: '', requires_metadata: false, rule_group_ids: ['grp-perf', 'grp-sec']},
      {id: 'Kural05', text: 'Geçici tabloyu sil.', summary: '', requires_metadata: false, rule_group_ids: []},
    ],
    normal: [{id: 'Kural09', text: 'Adlandırma.', summary: '', requires_metadata: false, rule_group_ids: ['grp-perf']}],
    groups,
    critical_count: 3,
    normal_count: 1,
  };
}

const GROUPS = [
  {id: 'grp-perf', name: 'Performans', description: ''},
  {id: 'grp-sec', name: 'Güvenlik', description: ''},
];

function Harness({onChange}: {onChange: (codes: string[]) => void}) {
  const [value, setValue] = useState<string[]>([]);
  return (
    <RuleSelectionPicker
      value={value}
      disabled={false}
      onChange={(codes) => {
        setValue(codes);
        onChange(codes);
      }}
    />
  );
}

/** The checkbox of the row whose rule code is exactly `code` (text match, no regular expression). */
function ruleBox(code: string): HTMLElement {
  return within(screen.getByText(code, {selector: '.option-title > .mono'}).closest('label')!).getByRole('checkbox');
}

describe('rule selection picker (rule-group-selection Requirement 8, Decision 6)', () => {
  it('lists the groups one under another and opens a group to its rules', async () => {
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(version(GROUPS));
    renderWithSession(<Harness onChange={() => undefined} />);
    expect(await screen.findByLabelText('Performans (2 kural)')).not.toBeChecked();
    expect(screen.getByLabelText('Güvenlik (2 kural)')).not.toBeChecked();
    expect(screen.getByLabelText('Grupsuz (1 kural)')).not.toBeChecked();
    expect(screen.getByText('Hiçbir kural seçilmezse tüm kurallar çalışır.')).toBeInTheDocument();
    // Closed groups keep the list short; opening one shows its rules beneath it.
    expect(screen.queryAllByRole('checkbox', {name: /^Kural/})).toHaveLength(0);
    const toggle = screen.getByRole('button', {name: /Güvenlik/});
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByRole('checkbox', {name: /^Kural/}).map((box) => box.closest('label')?.textContent?.slice(0, 7))).toEqual([
      'Kural01',
      'Kural03',
    ]);
  });

  it('shows the matching rules as one list while searching, with their groups', async () => {
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(version(GROUPS));
    renderWithSession(<Harness onChange={() => undefined} />);
    await screen.findByLabelText('Performans (2 kural)');
    fireEvent.change(screen.getByLabelText('Kural ara'), {target: {value: 'Kural'}});
    expect(screen.getAllByRole('checkbox', {name: /^Kural/})).toHaveLength(4);
    expect(ruleBox('Kural03')).toHaveAccessibleName(/Performans.*Güvenlik/);
  });

  it('selects single rules in version order and counts them', async () => {
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(version(GROUPS));
    const changes: string[][] = [];
    renderWithSession(<Harness onChange={(codes) => changes.push(codes)} />);
    await screen.findByLabelText('Performans (2 kural)');
    fireEvent.click(screen.getByRole('button', {name: /Performans/}));
    fireEvent.click(screen.getByRole('button', {name: /Grupsuz/}));
    fireEvent.click(ruleBox('Kural09'));
    fireEvent.click(ruleBox('Kural05'));
    expect(changes.at(-1)).toEqual(['Kural05', 'Kural09']);
    expect(screen.getByText('2 / 4 kural seçildi.')).toBeInTheDocument();
  });

  it('adds and removes all rules of a group at once and marks a partly chosen group', async () => {
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(version(GROUPS));
    const changes: string[][] = [];
    renderWithSession(<Harness onChange={(codes) => changes.push(codes)} />);
    fireEvent.click(await screen.findByLabelText('Güvenlik (2 kural)'));
    expect(changes.at(-1)).toEqual(['Kural01', 'Kural03']);
    // Kural03 is also in Performans, so that group is now partly chosen.
    const performance = screen.getByLabelText('Performans (2 kural)') as HTMLInputElement;
    expect(performance.indeterminate).toBe(true);
    fireEvent.click(performance);
    expect(changes.at(-1)).toEqual(['Kural01', 'Kural03', 'Kural09']);
    fireEvent.click(screen.getByLabelText('Güvenlik (2 kural)'));
    expect(changes.at(-1)).toEqual(['Kural09']);
    fireEvent.click(screen.getByRole('button', {name: 'Seçimi temizle'}));
    expect(changes.at(-1)).toEqual([]);
  });

  it('searches rules by code or text without dropping the selection', async () => {
    vi.spyOn(RuleSetService, 'latest').mockResolvedValue(version(GROUPS));
    const changes: string[][] = [];
    renderWithSession(<Harness onChange={(codes) => changes.push(codes)} />);
    fireEvent.click(await screen.findByLabelText('Güvenlik (2 kural)'));
    fireEvent.change(screen.getByLabelText('Kural ara'), {target: {value: 'yıldız'}});
    expect(screen.getAllByRole('checkbox', {name: /^Kural/})).toHaveLength(1);
    fireEvent.change(screen.getByLabelText('Kural ara'), {target: {value: 'yok böyle'}});
    expect(screen.getByText('Eşleşen kural yok.')).toBeInTheDocument();
    expect(changes.at(-1)).toEqual(['Kural01', 'Kural03']);
  });

  it('works without groups and shows nothing when nothing is published', async () => {
    const latest = vi.spyOn(RuleSetService, 'latest').mockResolvedValue(version([]));
    const {unmount} = renderWithSession(<Harness onChange={() => undefined} />);
    expect(await screen.findByRole('group', {name: 'Kurallar'})).toBeInTheDocument();
    expect(screen.queryByRole('group', {name: 'Grupla seç'})).toBeNull();
    // Without groups every rule is listed at once.
    expect(screen.getAllByRole('checkbox', {name: /^Kural/})).toHaveLength(4);
    unmount();

    latest.mockRejectedValue(apiError(404, 'no_published_rule_set'));
    renderWithSession(<Harness onChange={() => undefined} />);
    await vi.waitFor(() => expect(latest).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('group', {name: 'Kurallar'})).toBeNull();
  });
});
