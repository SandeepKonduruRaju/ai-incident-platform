// Renders investigation text with its evidence markers ("Pool exhausted [C1] after deploy [C2]."): every [Cn] is a
// button that shows that citation's source type, source id and snippet. Unknown labels stay plain text.
import { Fragment } from 'react';
import type { Citation } from '../api/types';
import styles from './Investigation.module.css';

const MARKER = /\[(C\d+)\]/g;

interface Props {
  text: string;
  citations: Map<string, Citation>;
  selected: string | null;
  onSelect: (label: string | null) => void;
}

export function CitedText({ text, citations, selected, onSelect }: Props) {
  const parts: (string | { label: string })[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(text.slice(last, index));
    parts.push({ label: match[1] });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));

  return (
    <>
      {parts.map((part, i) => {
        if (typeof part === 'string') return <Fragment key={i}>{part}</Fragment>;
        if (!citations.has(part.label)) return <Fragment key={i}>[{part.label}]</Fragment>;
        const active = selected === part.label;
        return (
          <button
            key={i}
            type="button"
            className={`${styles.marker} ${active ? styles.markerActive : ''}`}
            aria-pressed={active}
            aria-controls="citation-detail"
            aria-label={`Evidence ${part.label}`}
            onClick={() => onSelect(active ? null : part.label)}
          >
            {part.label}
          </button>
        );
      })}
    </>
  );
}

export function CitationDetail({ citation }: { citation: Citation | undefined }) {
  return (
    <aside id="citation-detail" className={styles.citation} aria-live="polite">
      {citation ? (
        <>
          <h4>
            Evidence {citation.label}
          </h4>
          <dl>
            <dt>Source type</dt>
            <dd>{citation.sourceType ?? '—'}</dd>
            <dt>Source id</dt>
            <dd>
              <code>{citation.sourceId ?? '—'}</code>
            </dd>
          </dl>
          {citation.snippet && <blockquote>{citation.snippet}</blockquote>}
        </>
      ) : (
        <p className={styles.hint}>Select an evidence marker such as C1 to see its source.</p>
      )}
    </aside>
  );
}
