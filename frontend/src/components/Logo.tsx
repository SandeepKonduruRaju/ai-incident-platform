// The logo mark: a case-file page with two lines of text, one of them highlighted. public/favicon.svg is the same
// drawing with fixed colours (a favicon cannot read CSS variables).
export function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="4" y="2.5" width="16" height="19" rx="2.5" fill="none" stroke="currentColor" strokeWidth="2" />
      <rect x="7" y="8" width="10" height="3.2" rx="1" fill="var(--marker)" />
      <path d="M7.5 9.6h9M7.5 15h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
