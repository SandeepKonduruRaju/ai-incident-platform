import { useMemo, useState, type ReactNode } from 'react';
import type { ApiClient } from '../api/client';
import type { Citation, Finding } from '../api/types';
import { useInvestigation } from '../hooks/useInvestigation';
import { CitationDetail, CitedText } from './CitedText';
import { ErrorMessage } from './ErrorMessage';
import { StatusBadge } from './Badges';
import styles from './Investigation.module.css';

export function InvestigationPanel({ api, incidentId }: { api: ApiClient; incidentId: string }) {
  const { investigation, unavailable, error } = useInvestigation(api, incidentId);
  const [selected, setSelected] = useState<string | null>(null);
  const citations = useMemo(
    () => new Map<string, Citation>((investigation?.citations ?? []).map((c) => [c.label, c])),
    [investigation],
  );

  const cited = (finding: Finding) => (
    <CitedText text={finding.text} citations={citations} selected={selected} onSelect={setSelected} />
  );

  return (
    <section className={styles.panel} aria-labelledby="investigation-heading" aria-busy={!error && !investigation}>
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

      {investigation?.status === 'COMPLETED' && (
        <div className={styles.result}>
          <div className={styles.content}>
            {investigation.summary && (
              <>
                <h3>Summary</h3>
                <p>
                  <CitedText text={investigation.summary} citations={citations} selected={selected} onSelect={setSelected} />
                </p>
              </>
            )}
            {investigation.confidence && (
              <p>
                <span className={styles.label}>Confidence:</span>{' '}
                <span className={`${styles.confidence} ${styles[`confidence_${investigation.confidence}`] ?? ''}`}>
                  {investigation.confidence}
                </span>
              </p>
            )}
            {investigation.rootCause && (
              <>
                <h3>Root cause</h3>
                <p>{cited(investigation.rootCause)}</p>
              </>
            )}
            <FindingList title="Contributing factors" findings={investigation.contributingFactors} render={cited} />
            <FindingList title="Remediation" findings={investigation.remediation} render={cited} ordered />
            {investigation.model && (
              <p className={styles.meta}>
                Model {investigation.model} · prompt {investigation.promptVersion}
                {investigation.completedAt && <> · completed {new Date(investigation.completedAt).toLocaleString()}</>}
              </p>
            )}
          </div>
          <CitationDetail citation={selected ? citations.get(selected) : undefined} />
        </div>
      )}
    </section>
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
  render: (finding: Finding) => ReactNode;
  ordered?: boolean;
}) {
  if (!findings || findings.length === 0) return null;
  const items = findings.map((finding, i) => <li key={i}>{render(finding)}</li>);
  return (
    <>
      <h3>{title}</h3>
      {ordered ? <ol>{items}</ol> : <ul>{items}</ul>}
    </>
  );
}
