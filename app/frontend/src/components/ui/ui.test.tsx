import {describe, expect, it} from 'vitest';
import {render, screen} from '@testing-library/react';
import {SeverityBadge, StatusPill} from './Badge';
import {SeverityBar} from './Charts';
import {SqlViewer} from '@/components/analysis/SqlViewer';
import {buildLineMarks} from '@/lib/findings';

describe('ui components', () => {
  it('renders Turkish severity and status labels', () => {
    render(
      <>
        <SeverityBadge severity="critical" />
        <StatusPill status="running" />
      </>,
    );
    expect(screen.getByText('Kritik')).toBeInTheDocument();
    expect(screen.getByText('Çalışıyor')).toBeInTheDocument();
  });

  it('labels the severity bar for screen readers', () => {
    render(<SeverityBar counts={{critical: 1, high: 0, medium: 2, low: 0, info: 0}} />);
    expect(screen.getByLabelText(/Kritik 1, Yüksek 0, Orta 2/)).toBeInTheDocument();
  });

  it('renders numbered SQL lines with marks', () => {
    const {container} = render(<SqlViewer source={'SELECT 1\nFROM t'} marks={buildLineMarks([{line: 2, severity: 'high', message: 'x'}])} />);
    expect(container.querySelectorAll('[data-line]')).toHaveLength(2);
    expect(screen.getByText('SELECT')).toBeInTheDocument();
  });
});
