// NOT_STARTED + retry (Task A), long snippets ("Show more"), citation highlighting, the wide-screen rail scroll and the
// narrow-screen bottom sheet (which replaced Task A's scroll-to-panel).
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import type { Investigation } from '../api/types';
import { INCIDENT_ID, completed, fakeApi } from '../test/fakeApi';
import { InvestigationPanel } from './InvestigationPanel';

const notStarted = { investigation: { incidentId: INCIDENT_ID, status: 'NOT_STARTED' as const } };

describe('NOT_STARTED', () => {
  afterEach(() => vi.useRealTimers());

  it('stops polling and shows "No investigation started" with a Retry button', async () => {
    vi.useFakeTimers();
    const getInvestigation = vi.fn().mockResolvedValue(notStarted);
    render(<InvestigationPanel api={fakeApi({ getInvestigation })} incidentId={INCIDENT_ID} canRetry />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText('No investigation started.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry investigation' })).toBeEnabled();
    expect(screen.queryByText(/waiting for the investigation/i)).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(getInvestigation).toHaveBeenCalledTimes(1); // final state: no more polling
  });

  it('Retry re-requests the investigation and polls again until it completes', async () => {
    const user = userEvent.setup();
    const getInvestigation = vi.fn().mockResolvedValueOnce(notStarted).mockResolvedValue({ investigation: completed });
    const retryInvestigation = vi.fn().mockResolvedValue({ investigation: { incidentId: INCIDENT_ID, status: 'PENDING' }, retryAfterSeconds: 2 });
    render(<InvestigationPanel api={fakeApi({ getInvestigation, retryInvestigation })} incidentId={INCIDENT_ID} canRetry />);

    await user.click(await screen.findByRole('button', { name: 'Retry investigation' }));

    expect(retryInvestigation).toHaveBeenCalledWith(INCIDENT_ID);
    expect(await screen.findByRole('heading', { name: 'Root cause' })).toBeInTheDocument();
    expect(screen.queryByText('No investigation started.')).not.toBeInTheDocument();
  });

  it('shows a refused retry (409) with its message, and viewers get no Retry button', async () => {
    const user = userEvent.setup();
    const retryInvestigation = vi.fn().mockRejectedValue(
      new ApiError(409, 'The investigation is RUNNING; only NOT_STARTED or FAILED investigations can be retried.', {
        requestId: 'req-409',
        problem: { title: 'Investigation cannot be retried', status: 409 },
      }),
    );
    const { unmount } = render(
      <InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue(notStarted), retryInvestigation })} incidentId={INCIDENT_ID} canRetry />,
    );
    await user.click(await screen.findByRole('button', { name: 'Retry investigation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Investigation cannot be retried');
    expect(screen.getByRole('alert')).toHaveTextContent('req-409');
    unmount();

    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue(notStarted) })} incidentId={INCIDENT_ID} />);
    expect(await screen.findByText('No investigation started.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry investigation' })).not.toBeInTheDocument();
  });
});

describe('evidence snippet', () => {
  const long =
    'Rebuilt and restored the index; writes resumed after the failover completed and replication caught up. ' +
    'The primary was promoted at 12:04 and the read replicas followed within two minutes, with no data loss reported.';
  const withLongSnippet: Investigation = {
    ...completed,
    citations: [{ label: 'C1', sourceType: 'runbook', sourceId: 'RB-db-failover', snippet: long }, ...(completed.citations ?? []).slice(1)],
  };

  it('previews at a word boundary with an ellipsis and expands with "Show more"', async () => {
    const user = userEvent.setup();
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: withLongSnippet }) })} incidentId={INCIDENT_ID} />);
    await screen.findByRole('heading', { name: 'Summary' });

    const evidence = document.getElementById('evidence-C1')!;
    const quote = evidence.querySelector('blockquote')!;
    expect(quote.textContent).toMatch(/…$/);
    expect(quote.textContent).not.toBe(long);
    expect(long.startsWith(quote.textContent!.slice(0, -1))).toBe(true); // a prefix of the real text...
    expect(long.charAt(quote.textContent!.length - 1)).toMatch(/[\s;,.]/); // ...ending at a word boundary

    const more = within(evidence).getByRole('button', { name: 'Show more' });
    expect(more).toHaveAttribute('aria-expanded', 'false');
    await user.click(more);
    expect(quote.textContent).toBe(long);
    expect(within(evidence).getByRole('button', { name: 'Show less' })).toHaveAttribute('aria-expanded', 'true');
  });
});

function stubMatchMedia(narrow: boolean, reducedMotion: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('max-width') ? narrow : query.includes('reduce') ? reducedMotion : false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

const twoSentences: Investigation = {
  ...completed,
  summary: 'The pool ran dry after the deploy [C1][C2]. Traffic was normal before noon.',
};

describe('citation highlight', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('highlights the cited sentence and its evidence, as separate numbered marks', async () => {
    stubMatchMedia(false, false);
    Element.prototype.scrollIntoView = vi.fn();
    const user = userEvent.setup();
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: twoSentences }) })} incidentId={INCIDENT_ID} />);

    // Adjacent markers stay separate marks: [1] [2], never run together like "C1C2".
    const c1 = (await screen.findAllByRole('button', { name: 'Evidence 1' }))[0];
    const c2 = screen.getAllByRole('button', { name: 'Evidence 2' })[0];
    expect(c1).toHaveTextContent('[1]');
    expect(c2).toHaveTextContent('[2]');
    expect(c1.nextElementSibling).toBe(c2);
    expect(document.querySelector('[data-highlighted]')).toBeNull();

    await user.click(c2);

    // Every sentence that cites C2 is highlighted: the summary's first sentence and the contributing factor.
    const marks = [...document.querySelectorAll('[data-highlighted]')];
    expect(marks.map((m) => m.textContent)).toEqual(['The pool ran dry after the deploy [1][2].', 'Traffic peak at 12:00 [2]']);
    expect(screen.getByText(/Traffic was normal before noon/).closest('[data-highlighted]')).toBeNull(); // the other sentence is not
    expect(document.getElementById('evidence-C2')).toHaveClass('evidenceActive');
    expect(document.getElementById('evidence-C1')).not.toHaveClass('evidenceActive');
    expect(screen.getByText('Evidence 2 highlighted.')).toBeInTheDocument(); // announced to screen readers
  });

  it.each([
    [false, 'smooth'],
    [true, 'auto'],
  ])('wide screen: scrolls the rail to the evidence (reduced motion %s -> %s), no sheet', async (reduced, behavior) => {
    stubMatchMedia(false, reduced);
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const user = userEvent.setup();
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: completed }) })} incidentId={INCIDENT_ID} />);

    await user.click(await screen.findByRole('button', { name: 'Evidence 2' }));

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior, block: 'nearest' });
    expect(scrollIntoView.mock.contexts.at(-1)).toBe(document.getElementById('evidence-C2'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('bottom sheet on a narrow screen', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('opens the evidence in a focus-trapped sheet; Esc closes it and returns focus to the mark', async () => {
    stubMatchMedia(true, false);
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const user = userEvent.setup();
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: completed }) })} incidentId={INCIDENT_ID} />);

    const c3 = await screen.findByRole('button', { name: 'Evidence 3' });
    await user.click(c3);

    const sheet = screen.getByRole('dialog', { name: 'Evidence 3' });
    expect(sheet).toHaveAttribute('aria-modal', 'true');
    expect(sheet).toHaveTextContent('RB-db-pool');
    expect(sheet).toHaveTextContent('Increase maximumPoolSize');
    const close = within(sheet).getByRole('button', { name: 'Close' });
    expect(close).toHaveFocus();
    expect(scrollIntoView).not.toHaveBeenCalled(); // the sheet replaces scrolling

    await user.tab(); // the only focusable element: focus stays inside the sheet
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(c3).toHaveFocus();
    expect(c3).toHaveAttribute('aria-pressed', 'true'); // the highlight stays after closing
  });

  it('makes the page behind the sheet inert while it is open, and restores it on close', async () => {
    stubMatchMedia(true, false);
    const user = userEvent.setup();
    const alreadyInert = document.createElement('div'); // something else on the page that was inert before
    alreadyInert.setAttribute('inert', '');
    document.body.appendChild(alreadyInert);
    const { container } = render(
      <InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: completed }) })} incidentId={INCIDENT_ID} />,
    );
    const c3 = await screen.findByRole('button', { name: 'Evidence 3' });
    expect(container).not.toHaveAttribute('inert');

    await user.click(c3);

    const sheet = screen.getByRole('dialog', { name: 'Evidence 3' });
    expect(container).toHaveAttribute('inert'); // the page (report, marks, rail) behind the sheet
    expect(container.contains(sheet)).toBe(false); // the sheet is rendered outside it (portal into <body>)
    expect(sheet.closest('[inert]')).toBeNull(); // ...so it stays usable

    await user.keyboard('{Escape}');
    expect(container).not.toHaveAttribute('inert');
    expect(alreadyInert).toHaveAttribute('inert'); // not ours to restore
    expect(c3).toHaveFocus(); // inert removed before focus went back
    alreadyInert.remove();
  });

  it('the Close button closes the sheet too', async () => {
    stubMatchMedia(true, true);
    const user = userEvent.setup();
    render(<InvestigationPanel api={fakeApi({ getInvestigation: vi.fn().mockResolvedValue({ investigation: completed }) })} incidentId={INCIDENT_ID} />);

    await user.click((await screen.findAllByRole('button', { name: 'Evidence 1' }))[0]); // summary and root cause
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
