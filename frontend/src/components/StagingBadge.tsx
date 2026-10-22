// Staging na laptopie (docs/staging-laptop-plan.md): pełna kopia produkcji,
// więc karta musi od pierwszego spojrzenia różnić się od prawdziwego NEXUSA.
// Wartość wklejana w build (`NEXT_PUBLIC_NEXUS_ENV`), jak adres API.
export const IS_STAGING = process.env.NEXT_PUBLIC_NEXUS_ENV === "staging";

export function StagingBadge() {
  if (!IS_STAGING) return null;
  return (
    <div
      role="status"
      aria-label="Staging — kopia produkcji, nic nie wychodzi na zewnątrz"
      className="pointer-events-none fixed bottom-3 left-1/2 z-[100] -translate-x-1/2 rounded-full bg-destructive px-3 py-1 text-xs font-semibold tracking-wide text-destructive-foreground shadow-lg"
    >
      STAGING
    </div>
  );
}
