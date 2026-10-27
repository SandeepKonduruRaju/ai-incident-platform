import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from '../api/client';
import type { Incident } from '../api/types';
import { AuthProvider } from '../auth/AuthContext';
import { Router } from '../router';
import { fakeApi } from '../test/fakeApi';
import { NO_FILTERS, filterIncidents } from './incidentFilters';
import { IncidentsPage } from './IncidentsPage';

const incident = (id: number, overrides: Partial<Incident>): Incident => ({
  id: `00000000-0000-4000-8000-${String(id).padStart(12, '0')}`,
  title: `Incident ${id}`,
  description: null,
  severity: 'LOW',
  status: 'OPEN',
  affectedService: 'svc',
  createdAt: new Date(Date.now() - 2 * 3600_000).toISOString(),
  ...overrides,
});

const ITEMS = [
  incident(1, { title: 'Checkout API 500 errors', severity: 'CRITICAL', status: 'INVESTIGATING', affectedService: 'checkout-api' }),
  incident(2, { title: 'Slow search results', severity: 'MEDIUM', status: 'OPEN', affectedService: 'search-service' }),
  incident(3, { title: 'Payment retries spiking', severity: 'HIGH', status: 'RESOLVED', affectedService: 'payment-service' }),
];

const page = (items: Incident[]) => ({ items, page: 0, size: 100, totalElements: items.length, totalPages: 1 });

function renderWith(api: ApiClient) {
  return render(
    <AuthProvider apiFactory={() => api}>
      <Router>
        <IncidentsPage page={0} />
      </Router>
    </AuthProvider>,
  );
}

const rowTitles = () => within(screen.getByRole('list', { name: 'Incidents' })).getAllByRole('link').map((a) => a.textContent);

describe('filterIncidents', () => {
  it('matches title or service case-insensitively, and combines with severity and status', () => {
    expect(filterIncidents(ITEMS, NO_FILTERS)).toHaveLength(3);
    expect(filterIncidents(ITEMS, { ...NO_FILTERS, query: '  PAYMENT ' }).map((i) => i.title)).toEqual(['Payment retries spiking']);
    expect(filterIncidents(ITEMS, { ...NO_FILTERS, query: 'search-serv' }).map((i) => i.title)).toEqual(['Slow search results']);
    expect(filterIncidents(ITEMS, { ...NO_FILTERS, severity: 'CRITICAL' }).map((i) => i.title)).toEqual(['Checkout API 500 errors']);
    expect(filterIncidents(ITEMS, { query: 'e', severity: '', status: 'RESOLVED' }).map((i) => i.title)).toEqual(['Payment retries spiking']);
    expect(filterIncidents(ITEMS, { query: 'checkout', severity: 'LOW', status: '' })).toEqual([]);
  });
});

describe('IncidentsPage', () => {
  it('lists rows with title link, severity and status words, relative time and a full-date tooltip', async () => {
    renderWith(fakeApi({ listIncidents: vi.fn().mockResolvedValue(page(ITEMS)) }));

    const link = await screen.findByRole('link', { name: 'Checkout API 500 errors' });
    expect(link).toHaveAttribute('href', `/incidents/${ITEMS[0].id}`);
    const row = link.closest('li')!;
    expect(row).toHaveTextContent('Critical');
    expect(row).toHaveTextContent('Investigating');
    expect(row).toHaveTextContent('checkout-api');
    const time = row.querySelector('time')!;
    expect(time).toHaveTextContent('2 hr ago');
    expect(time.getAttribute('title')).toMatch(/\d{4} at \d{2}:\d{2}$/);
    expect(document.title).toBe('Incidents — Incident Platform');
  });

  it('filters by search, severity and status, and can clear the filters', async () => {
    const user = userEvent.setup();
    renderWith(fakeApi({ listIncidents: vi.fn().mockResolvedValue(page(ITEMS)) }));
    await screen.findByRole('list', { name: 'Incidents' });

    await user.type(screen.getByRole('searchbox', { name: 'Search' }), 'service');
    expect(rowTitles()).toEqual(['Slow search results', 'Payment retries spiking']);
    expect(screen.getByText('2 of 3 incidents on this page match.')).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Severity'), 'HIGH');
    expect(rowTitles()).toEqual(['Payment retries spiking']);

    await user.selectOptions(screen.getByLabelText('Status'), 'OPEN');
    expect(screen.queryByRole('list', { name: 'Incidents' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'No incidents match' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(rowTitles()).toHaveLength(3);
    expect(screen.getByRole('searchbox', { name: 'Search' })).toHaveValue('');
  });

  it('shows an empty state with a "Report an incident" action for a tenant with no incidents', async () => {
    renderWith(fakeApi({ listIncidents: vi.fn().mockResolvedValue(page([])) }));

    expect(await screen.findByRole('heading', { name: 'No incidents yet' })).toBeInTheDocument();
    const actions = screen.getAllByRole('link', { name: 'Report an incident' });
    expect(actions).toHaveLength(1); // only in the empty state, not twice
    expect(actions[0]).toHaveAttribute('href', '/incidents/new');
    expect(screen.queryByRole('search')).not.toBeInTheDocument();
  });
});
