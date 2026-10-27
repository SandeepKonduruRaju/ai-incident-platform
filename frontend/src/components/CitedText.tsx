// Renders investigation text with its evidence markers ("Pool exhausted [C1] after deploy [C2]."): every [Cn] becomes a
// numbered mark [n], a button that selects that evidence. The sentence that cites the selected evidence is highlighted
// like the evidence itself (a highlighter pen across report and rail). Unknown labels stay plain text.
import { Fragment, useId, useState } from 'react';
import type { Citation } from '../api/types';
import { sourceTypeLabel } from '../labels';
import { truncateAtWord } from '../text';
import styles from './Investigation.module.css';

const MARKER = /\[(C\d+)\]/g;
const LEADING_MARKERS = /^(?:\[C\d+\]\s*)+/;
export const SNIPPET_PREVIEW_CHARS = 200;

/** "C3" -> "3": the number shown in marks and in the evidence rail. */
export function citationNumber(label: string): string {
  return /^C\d+$/.test(label) ? label.slice(1) : label;
}

/**
 * Sentences, each keeping the markers that cite it. A marker placed after the full stop ("... deploy. [C2] Then ...")
 * belongs to the sentence before it.
 */
export function splitSentences(text: string): string[] {
  const sentences: string[] = [];
  for (const part of text.split(/(?<=[.!?])\s+/)) {
    const leading = LEADING_MARKERS.exec(part)?.[0];
    if (leading && sentences.length > 0) {
      sentences[sentences.length - 1] += ` ${leading.trim()}`;
      const rest = part.slice(leading.length);
      if (rest) sentences.push(rest);
    } else if (part) {
      sentences.push(part);
    }
  }
  return sentences;
}

interface Props {
  text: string;
  citations: Map<string, Citation>;
  selected: string | null;
  onSelect: (label: string) => void;
}

export function CitedText({ text, citations, selected, onSelect }: Props) {
  return (
    <>
      {splitSentences(text).map((sentence, i) => {
        // Always the same element, only the class changes: swapping in a <mark> would remount the marks inside and
        // take keyboard focus off the mark that was just pressed. The selection is announced by the rail instead.
        const highlighted = selected !== null && sentence.includes(`[${selected}]`);
        return (
          <Fragment key={i}>
            {i > 0 && ' '}
            <span className={highlighted ? styles.highlight : undefined} data-highlighted={highlighted || undefined}>
              <SentenceParts sentence={sentence} citations={citations} selected={selected} onSelect={onSelect} />
            </span>
          </Fragment>
        );
      })}
    </>
  );
}

function SentenceParts({ sentence, citations, selected, onSelect }: Omit<Props, 'text'> & { sentence: string }) {
  const parts: (string | { label: string })[] = [];
  let last = 0;
  for (const match of sentence.matchAll(MARKER)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(sentence.slice(last, index));
    parts.push({ label: match[1] });
    last = index + match[0].length;
  }
  if (last < sentence.length) parts.push(sentence.slice(last));

  return (
    <>
      {parts.map((part, i) => {
        if (typeof part === 'string') return <Fragment key={i}>{part}</Fragment>;
        if (!citations.has(part.label)) return <Fragment key={i}>[{part.label}]</Fragment>;
        const active = selected === part.label;
        const number = citationNumber(part.label);
        return (
          <button
            key={i}
            type="button"
            className={`${styles.mark} ${active ? styles.markActive : ''}`}
            aria-pressed={active}
            aria-controls={`evidence-${part.label}`}
            aria-label={`Evidence ${number}`}
            onClick={() => onSelect(part.label)}
          >
            [{number}]
          </button>
        );
      })}
    </>
  );
}

/** One piece of evidence: number, source type, source id and the snippet (word-boundary preview, expandable). */
export function EvidenceItem({ citation, active = false, id }: { citation: Citation; active?: boolean; id?: string }) {
  const headingId = useId();
  return (
    <article
      id={id}
      className={`${styles.evidence} ${active ? styles.evidenceActive : ''}`}
      aria-labelledby={headingId}
      aria-current={active || undefined}
    >
      <h3 id={headingId} className={styles.evidenceHeading}>
        <span>Evidence {citationNumber(citation.label)}</span>{' '}
        <span className={styles.sourceType}>{sourceTypeLabel(citation.sourceType)}</span>
      </h3>
      {citation.sourceId && <p className={styles.sourceId}>{citation.sourceId}</p>}
      {/* key: a different citation starts collapsed again */}
      {citation.snippet && <Snippet key={citation.label} text={citation.snippet} />}
    </article>
  );
}

/** The evidence text: a word-boundary preview with "…", expandable to the full text. */
function Snippet({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const preview = truncateAtWord(text, SNIPPET_PREVIEW_CHARS);
  return (
    <>
      <blockquote id={id} className={styles.snippet}>
        {expanded || !preview.truncated ? text : preview.text}
      </blockquote>
      {preview.truncated && (
        <button type="button" className={styles.more} aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </>
  );
}
