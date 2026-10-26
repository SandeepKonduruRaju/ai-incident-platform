import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { INCIDENT_ID, completed, fakeApi, unavailable } from '../test/fakeApi';
import { InvestigationPanel } from './InvestigationPanel';

const pending = { investigation: { incidentId: INCIDENT_ID, status: 'PENDING' as const }, retryAfterSeconds: 2 };
const running = { investigation: { incidentId: INCIDENT_ID, status: 'RUNNING' as const }, retryAfterSeconds: 3 };

/** Lets pending promises resolve, then moves the fake clock. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('InvestigationPanel polling', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('polls honouring Retry-After until COMPLETED, then stops', async () => {
    const getInvestigation = vi
      .fn()
      .mockResolvedValueOnce(pending)
      .mockResolvedValueOnce(running)
      .mockResolvedValueOnce({ investigation: completed });
    render(<InvestigationPanel api={fakeApi({ getInvestigation })} incidentId={INCIDENT_ID} />);

    await advance(0);
    expect(getInvestigation).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/waiting for the investigation/i)).toBeInTheDocument();

    await advance(1999); // Retry-After: 2 -> not yet
    expect(getInvestigation).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(getInvestigation).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/investigating/i)).toBeInTheDocument();

    await advance(3000); // Retry-After: 3 from the RUNNING answer
    expect(getInvestigation).toHaveBeenCalledTimes(3);
    expect(screen.getByText('COMPLETED')).toBeInTheDocument();

    await advance(60_000);
    expect(getInvestigation).toHaveBeenCalledTimes(3); // finished: no more polling
  });

  it('shows "unavailable, retrying" on 503 and retries after its Retry-After', async () => {
    const getInvestigation = vi.fn().mockRejectedValueOnce(unavailable()).mockResolvedValueOnce({ investigation: completed });
    render(<InvestigationPanel api={fakeApi({ getInvestigation })} incidentId={INCIDENT_ID} />);

    await advance(0);
    expect(screen.getByText(/investigation service unavailable, retrying/i)).toBeInTheDocument();
    expect(screen.getByText(/req-503/)).toBeInTheDocument();

    await advance(5000);
    expect(getInvestigation).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/unavailable, retrying/i)).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Root cause' })).toBeInTheDocument();
  });

  it('stops on a non-retryable error and shows it with the request id', async () => {
    const getInvestigation = vi
      .fn()
      .mockRejectedValue(new ApiError(404, 'Incident not found', { requestId: 'req-404', problem: { title: 'Incident not found' } }));
    render(<InvestigationPanel api={fakeApi({ getInvestigation })} incidentId={INCIDENT_ID} />);

    await advance(0);
    expect(screen.getByRole('alert')).toHaveTextContent('Incident not found');
    expect(screen.getByRole('alert')).toHaveTextContent('req-404');
    await advance(60_000);
    expect(getInvestigation).toHaveBeenCalledTimes(1);
  });

  it('shows the failure reason of a FAILED investigation', async () => {
    const getInvestigation = vi.fn().mockResolvedValue({
      investigation: { incidentId: INCIDENT_ID, status: 'FAILED', failureReason: 'stale: still RUNNING more than 10 min' },
    });
    render(<InvestigationPanel api={fakeApi({ getInvestigation })} incidentId={INCIDENT_ID} />);

    await advance(0);
    expect(screen.getByRole('alert')).toHaveTextContent('The investigation failed.');
    expect(screen.getByRole('alert')).toHaveTextContent('stale: still RUNNING more than 10 min');
  });

  it('stops polling when unmounted', async () => {
    const getInvestigation = vi.fn().mockResolvedValue(pending);
    const { unmount } = render(<InvestigationPanel api={fakeApi({ getInvestigation })} incidentId={INCIDENT_ID} />);
    await advance(0);
    unmount();
    await advance(10_000);
    expect(getInvestigation).toHaveBeenCalledTimes(1);
  });
});

describe('InvestigationPanel result and citations', () => {
  it('renders summary, confidence, root cause, factors and remediation, and shows a citation on click', async () => {
    const user = userEvent.setup();
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: completed }) })} incidentId={INCIDENT_ID} />);

    expect(await screen.findByRole('heading', { name: 'Summary' })).toBeInTheDocument();
    expect(screen.getByText('medium')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Contributing factors' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Remediation' })).toBeInTheDocument();
    expect(screen.getByText(/HikariPool timeouts in payment-service/)).toBeInTheDocument();

    const c3 = screen.getByRole('button', { name: 'Evidence C3' });
    expect(c3).toHaveAttribute('aria-pressed', 'false');
    await user.click(c3);
    expect(c3).toHaveAttribute('aria-pressed', 'true');
    const detail = screen.getByRole('complementary');
    expect(detail).toHaveTextContent('Evidence C3');
    expect(detail).toHaveTextContent('runbook');
    expect(detail).toHaveTextContent('RB-db-pool');
    expect(detail).toHaveTextContent('Increase maximumPoolSize');
  });

  it('citation markers are keyboard operable', async () => {
    const user = userEvent.setup();
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: completed }) })} incidentId={INCIDENT_ID} />);
    const c2 = await screen.findByRole('button', { name: 'Evidence C2' });
    c2.focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('complementary')).toHaveTextContent('MET-acme-rps');
  });
});
