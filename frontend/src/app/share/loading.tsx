/**
 * Prosta granica ładowania udostępnionych widoków. Bez niej zadziałałby
 * szkielet pulpitu z `app/loading.tsx` (karty i tabela aplikacji wewnętrznej).
 */
export default function ShareLoading() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-svh items-center justify-center bg-background px-4 text-sm text-muted-foreground"
    >
      Ładowanie…
    </div>
  );
}
