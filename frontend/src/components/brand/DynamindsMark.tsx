/**
 * Dynaminds "stempel" — the short/compact brand mark (the peak glyph only).
 * Uses `fill="currentColor"` so it inherits the surrounding text color and works
 * on any background (dark sidebar, light/dark cards) and across all theme palettes.
 * Use the compact mark where space is tight (collapsed sidebar, favicons, avatars).
 */
export function DynamindsMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 103 70"
      fill="currentColor"
      role="img"
      aria-label="Dynaminds"
      className={className}
    >
      <path
        fillRule="evenodd"
        d="M89.16,54.85L62.61,8.87l-5.31,9.2,21.24,36.79h10.62ZM62.61,45.65h-21.24s-5.31,9.2-5.31,9.2h31.86s-5.31-9.2-5.31-9.2h0ZM41.37,27.26l5.31,9.2h10.62s-15.93-27.59-15.93-27.59L14.82,54.85h10.62s15.93-27.59,15.93-27.59h0Z"
      />
    </svg>
  );
}
