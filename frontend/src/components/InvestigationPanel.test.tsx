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
    expect(screen.getByText('Completed')).toBeInTheDocument();

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
  it('renders summary, confidence in words, root cause, factors, numbered remediation and the evidence rail', async () => {
    const user = userEvent.setup();
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: completed }) })} incidentId={INCIDENT_ID} />);

    expect(await screen.findByRole('heading', { name: 'Summary' })).toBeInTheDocument();
    expect(screen.getByText('Medium confidence')).toBeInTheDocument();
    expect(screen.getByText(/a likely cause, worth confirming/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Contributing factors' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Remediation' })).toBeInTheDocument();
    expect(screen.getByText(/HikariPool timeouts in payment-service/)).toBeInTheDocument();
    expect(screen.getByText(/Written by claude-haiku-5-5 with prompt v1/)).toBeInTheDocument();

    const rail = screen.getByRole('complementary', { name: 'Evidence' });
    expect(rail).toHaveTextContent('Runbook');
    expect(rail).toHaveTextContent('RB-db-pool');
    expect(rail).toHaveTextContent('Increase maximumPoolSize');

    const c3 = screen.getByRole('button', { name: 'Evidence 3' });
    expect(c3).toHaveTextContent('[3]');
    expect(c3).toHaveAttribute('aria-pressed', 'false');
    await user.click(c3);
    expect(c3).toHaveAttribute('aria-pressed', 'true');
    await user.click(c3); // a second click clears the selection
    expect(c3).toHaveAttribute('aria-pressed', 'false');
  });

  it('lists the evidence in number order, whatever order the API returns it in', async () => {
    const shuffled = { ...completed, citations: [...(completed.citations ?? [])].reverse() };
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: shuffled }) })} incidentId={INCIDENT_ID} />);
    await screen.findByRole('heading', { name: 'Summary' });
    const headings = screen.getAllByRole('heading', { level: 3, name: /^Evidence \d/ }).map((h) => h.textContent);
    expect(headings).toEqual(['Evidence 1 Log', 'Evidence 2 Metric', 'Evidence 3 Runbook']);
  });

  it('citation markers are keyboard operable', async () => {
    const user = userEvent.setup();
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: completed }) })} incidentId={INCIDENT_ID} />);
    const c2 = await screen.findByRole('button', { name: 'Evidence 2' });
    c2.focus();
    await user.keyboard('{Enter}');
    expect(c2).toHaveAttribute('aria-pressed', 'true');
    expect(c2).toHaveFocus(); // highlighting must not remount the mark and drop keyboard focus
    expect(document.getElementById('evidence-C2')).toHaveClass('evidenceActive');
    expect(document.getElementById('evidence-C2')).toHaveTextContent('MET-acme-rps');
  });
});
