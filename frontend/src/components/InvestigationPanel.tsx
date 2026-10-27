import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { ApiClient } from '../api/client';
import type { Citation, Finding, Investigation } from '../api/types';
import { formatDateTime } from '../format';
import { useInvestigation } from '../hooks/useInvestigation';
import { NARROW_QUERY, REDUCED_MOTION_QUERY, useMediaQuery } from '../hooks/useMediaQuery';
import { StatusBadge } from './Badges';
import { BottomSheet } from './BottomSheet';
import { CitedText, EvidenceItem, citationNumber } from './CitedText';
import { ErrorMessage } from './ErrorMessage';
import styles from './Investigation.module.css';

const CONFIDENCE: Record<string, { label: string; meaning: string }> = {
  high: { label: 'High confidence', meaning: 'the evidence points clearly to this cause' },
  medium: { label: 'Medium confidence', meaning: 'a likely cause, worth confirming' },
  low: { label: 'Low confidence', meaning: 'not enough evidence to confirm a cause' },
};

/**
 * The incident's case file: `intro` (title and facts) and the AI report on the left, the evidence rail on the right.
 * Selecting a mark [n] highlights the evidence and the sentence that cites it. Wide screens scroll the rail to it;
 * narrow screens (rail below the report) open it in a bottom sheet instead.
 */
export function InvestigationPanel({
  api,
  incidentId,
  canRetry = false,
  intro,
}: {
  api: ApiClient;
  incidentId: string;
  canRetry?: boolean;
  intro?: ReactNode;
}) {
  const { investigation, unavailable, error, retry, retrying, retryError } = useInvestigation(api, incidentId);
  const [selected, setSelected] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const narrow = useMediaQuery(NARROW_QUERY);
  const reducedMotion = useMediaQuery(REDUCED_MOTION_QUERY);
  const railRef = useRef<HTMLElement>(null);

  // In number order ([1], [2], ...), whatever order the API lists them in: the rail reads top to bottom.
  const citations = useMemo(() => {
    const sorted = [...(investigation?.citations ?? [])].sort(
      (a, b) => Number(citationNumber(a.label)) - Number(citationNumber(b.label)) || a.label.localeCompare(b.label),
    );
    return new Map<string, Citation>(sorted.map((c) => [c.label, c]));
  }, [investigation]);

  function select(label: string) {
    if (narrow) {
      setSelected(label);
      setSheetOpen(true);
    } else {
      setSelected((current) => (current === label ? null : label));
    }
  }

  // Wide screens: bring the selected evidence into view inside the sticky rail (no animation for reduced motion).
  useEffect(() => {
    if (!selected || narrow) return;
    const item = railRef.current?.querySelector<HTMLElement>(`#evidence-${selected}`);
    item?.scrollIntoView?.({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'nearest' });
  }, [selected, narrow, reducedMotion]);

  const selectedCitation = selected ? citations.get(selected) : undefined;
  const completed = investigation?.status === 'COMPLETED' ? investigation : null;

  return (
    <div className={styles.layout}>
      <div className={styles.paper}>
        {intro}
        <section className={styles.report} aria-labelledby="investigation-heading" aria-busy={!error && !investigation}>
          <header className={styles.header}>
            <h2 id="investigation-heading">AI investigation</h2>
            {investigation && <StatusBadge status={investigation.status} />}
          </header>

          {unavailable && (
            <p role="status" className={styles.warning}>
              Investigation service unavailable, retrying…
              {unavailable.requestId && <span className={styles.requestId}> (request id {unavailable.requestId})</span>}
            </p>
          )}
          {error && <ErrorMessage error={error} />}

          {!error && (!investigation || investigation.status === 'PENDING' || investigation.status === 'RUNNING') && (
            <p role="status" className={styles.progress}>
              <span className={styles.spinner} aria-hidden="true" />
              {investigation?.status === 'RUNNING' ? 'Investigating: retrieving evidence and analysing…' : 'Waiting for the investigation to start…'}
            </p>
          )}

          {investigation?.status === 'FAILED' && (
            <div role="alert" className={styles.failed}>
              <strong>The investigation failed.</strong>
              <p>{investigation.failureReason ?? 'No reason was recorded.'}</p>
            </div>
          )}

          {investigation?.status === 'NOT_STARTED' && (
            <div role="status" className={styles.notStarted}>
              <strong>No investigation started.</strong>
              <p>No AI investigation was ever run for this incident{canRetry ? '. You can request one now.' : '.'}</p>
            </div>
          )}

          {canRetry && (investigation?.status === 'NOT_STARTED' || investigation?.status === 'FAILED') && (
            <>
              <button type="button" className={styles.retry} onClick={() => void retry()} disabled={retrying}>
                {retrying ? 'Requesting…' : 'Retry investigation'}
              </button>
              {retryError && <ErrorMessage error={retryError} />}
            </>
          )}

          {completed && <Report investigation={completed} citations={citations} selected={selected} onSelect={select} />}
        </section>
      </div>

      <aside ref={railRef} className={styles.rail} aria-labelledby="evidence-heading">
        <h2 id="evidence-heading" className={styles.railHeading}>
          Evidence
        </h2>
        {completed && citations.size > 0 ? (
          <>
            <p className={styles.railHint}>Select a mark such as [1] in the report to highlight its evidence.</p>
            <ol className={styles.evidenceList}>
              {[...citations.values()].map((citation) => (
                <li key={citation.label}>
                  <EvidenceItem id={`evidence-${citation.label}`} citation={citation} active={citation.label === selected} />
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p className={styles.railHint}>
            {completed ? 'This report cites no evidence.' : 'The evidence behind the report appears here when the investigation completes.'}
          </p>
        )}
        <p className="visually-hidden" aria-live="polite">
          {selectedCitation ? `Evidence ${citationNumber(selectedCitation.label)} highlighted.` : ''}
        </p>
      </aside>

      {narrow && sheetOpen && selectedCitation && (
        <BottomSheet title={`Evidence ${citationNumber(selectedCitation.label)}`} onClose={() => setSheetOpen(false)}>
          <EvidenceItem citation={selectedCitation} active />
        </BottomSheet>
      )}
    </div>
  );
}

function Report({
  investigation,
  citations,
  selected,
  onSelect,
}: {
  investigation: Investigation;
  citations: Map<string, Citation>;
  selected: string | null;
  onSelect: (label: string) => void;
}) {
  const cited = (text: string) => <CitedText text={text} citations={citations} selected={selected} onSelect={onSelect} />;
  const confidence = investigation.confidence ? CONFIDENCE[investigation.confidence.toLowerCase()] : undefined;
  return (
    <div className={styles.prose}>
      {investigation.confidence && (
        <p className={`${styles.confidence} ${styles[`confidence_${investigation.confidence.toLowerCase()}`] ?? ''}`}>
          <strong>{confidence?.label ?? `Confidence: ${investigation.confidence}`}</strong>
          {confidence && <> — {confidence.meaning}</>}
        </p>
      )}
      {investigation.summary && (
        <>
          <h3>Summary</h3>
          <p>{cited(investigation.summary)}</p>
        </>
      )}
      {investigation.rootCause && (
        <>
          <h3>Root cause</h3>
          <p>{cited(investigation.rootCause.text)}</p>
        </>
      )}
      <FindingList title="Contributing factors" findings={investigation.contributingFactors} render={cited} />
      <FindingList title="Remediation" findings={investigation.remediation} render={cited} ordered />
      {investigation.model && (
        <p className={styles.meta}>
          Written by {investigation.model} with prompt {investigation.promptVersion}
          {investigation.completedAt && (
            <>
              , completed <time dateTime={investigation.completedAt}>{formatDateTime(investigation.completedAt)}</time>
            </>
          )}
          .
        </p>
      )}
    </div>
  );
}

function FindingList({
  title,
  findings,
  render,
  ordered = false,
}: {
  title: string;
  findings?: Finding[];
  render: (text: string) => ReactNode;
  ordered?: boolean;
}) {
  if (!findings || findings.length === 0) return null;
  const items = findings.map((finding, i) => <li key={i}>{render(finding.text)}</li>);
  return (
    <>
      <h3>{title}</h3>
      {ordered ? <ol>{items}</ol> : <ul>{items}</ul>}
    </>
  );
}
