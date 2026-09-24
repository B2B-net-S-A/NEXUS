/**
 * Prosta granica ładowania strony zgłoszenia. Bez niej zadziałałby szkielet
 * pulpitu z `app/loading.tsx` (karty i tabela aplikacji wewnętrznej).
 */
export default function ApplyLoading() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-[60svh] items-center justify-center px-4 text-sm text-muted-foreground"
    >
      Ładowanie…
    </div>
  );
}
