import {fireEvent, render, screen} from '@testing-library/react';
import {useState} from 'react';
import {describe, expect, it} from 'vitest';
import {Tabs} from './Tabs';

type Id = 'a' | 'b' | 'c';

function Harness() {
  const [value, setValue] = useState<Id>('a');
  return (
    <Tabs
      label="Örnek"
      value={value}
      onChange={setValue}
      items={[
        {id: 'a', label: 'Birinci', count: 2, attention: true},
        {id: 'b', label: 'İkinci', count: 0, attention: true},
        {id: 'c', label: 'Üçüncü'},
      ]}
    />
  );
}

describe('tabs', () => {
  it('names a counted tab with its count and keeps one tab stop', () => {
    render(<Harness />);
    const first = screen.getByRole('tab', {name: 'Birinci (2)'});
    expect(first).toHaveAttribute('aria-selected', 'true');
    expect(first).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tab', {name: 'İkinci (0)'})).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('tab', {name: 'Üçüncü'})).toBeInTheDocument();
    expect(screen.getByRole('tablist', {name: 'Örnek'})).toBeInTheDocument();
  });

  it('moves the selection with the arrow, Home and End keys', () => {
    render(<Harness />);
    fireEvent.keyDown(screen.getByRole('tab', {name: 'Birinci (2)'}), {key: 'ArrowRight'});
    expect(screen.getByRole('tab', {name: 'İkinci (0)'})).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', {name: 'İkinci (0)'})).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('tab', {name: 'İkinci (0)'}), {key: 'End'});
    expect(screen.getByRole('tab', {name: 'Üçüncü'})).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(screen.getByRole('tab', {name: 'Üçüncü'}), {key: 'ArrowRight'});
    expect(screen.getByRole('tab', {name: 'Birinci (2)'})).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(screen.getByRole('tab', {name: 'Birinci (2)'}), {key: 'ArrowLeft'});
    expect(screen.getByRole('tab', {name: 'Üçüncü'})).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(screen.getByRole('tab', {name: 'Üçüncü'}), {key: 'Home'});
    expect(screen.getByRole('tab', {name: 'Birinci (2)'})).toHaveAttribute('aria-selected', 'true');
  });
});
