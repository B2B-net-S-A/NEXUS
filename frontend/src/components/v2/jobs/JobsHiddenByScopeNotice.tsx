"use client";

/**
 * Filtr „Data otwarcia” działa w obrębie zakresu listy. Zakresy „Moje” i „Otwarte”
 * chowają zamknięte rekrutacje, więc wynik za miesiąc wyglądał na przypadkowy
 * (zgłoszenie Delivery Leada 09.11.2026: 8 z 11 procesów klienta).
 */
export function JobsHiddenByScopeNotice({
  hidden,
  scope,
  onShowAll,
}: {
  hidden: number;
  scope: "mine" | "open";
  onShowAll: () => void;
}) {
  if (hidden <= 0) return null;
  const what = scope === "mine" ? "Moje” pomija zamknięte i cudze" : "Otwarte” pomija zamknięte";
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-2 rounded-lg border border-border bg-card px-3 py-2 text-sm"
    >
      <span>
        Zakres „{what} rekrutacje: w tym okresie jest ich jeszcze <strong>{hidden}</strong>.
      </span>
      <button
        type="button"
        onClick={onShowAll}
        className="font-medium text-primary hover:underline"
      >
        Pokaż wszystkie
      </button>
    </div>
  );
}
