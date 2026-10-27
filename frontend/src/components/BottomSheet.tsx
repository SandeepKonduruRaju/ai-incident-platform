// A modal bottom sheet for narrow screens: focus moves into it and is trapped there, Esc or the backdrop closes it,
// and focus returns to whatever opened it. Rendered into <body> (a portal) so everything else on the page can be made
// `inert` while it is open: not focusable, not clickable, and hidden from screen readers' virtual cursor too (the
// Tab trap alone does not stop that). The slide-in is CSS and is skipped for prefers-reduced-motion.
import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import styles from './BottomSheet.module.css';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function BottomSheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const titleId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const restoreInert = makeOthersInert(rootRef.current);
    closeRef.current?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden'; // the page behind does not scroll while the sheet is open
    return () => {
      document.body.style.overflow = overflow;
      restoreInert(); // first: an inert element cannot take focus back
      opener?.focus();
    };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab' || !sheetRef.current) return;
    const focusable = [...sheetRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div ref={rootRef} className={styles.root}>
      <div className={styles.backdrop} onClick={onClose} aria-hidden="true" />
      <div ref={sheetRef} className={styles.sheet} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
        <div className={styles.header}>
          <h2 id={titleId}>{title}</h2>
          <button ref={closeRef} type="button" className={styles.close} onClick={onClose}>
            Close
          </button>
        </div>
        <div className={styles.body}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}

/** Sets `inert` on every other child of <body>; returns how to undo it (leaving any that were inert before). */
function makeOthersInert(keep: Element | null): () => void {
  const changed = [...document.body.children].filter((el) => el !== keep && !el.hasAttribute('inert'));
  changed.forEach((el) => el.setAttribute('inert', ''));
  return () => changed.forEach((el) => el.removeAttribute('inert'));
}
