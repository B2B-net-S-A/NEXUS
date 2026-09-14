"use client";

import { useEffect, type ReactNode } from "react";
import { pinAnchor } from "@/lib/anchor-pin";
import { cn } from "@/lib/utils";

/**
 * Sub-nawigacja sekcji zakładki Insights.
 *
 * Powód istnienia: każda z trzech zakładek to kilkanaście sekcji na jednym
 * przewijaniu (Rekrutacja ma ich trzynaście). Bez spisu treści jedyną drogą do
 * „Ścieżki rozwoju" jest przewinięcie całej strony — a DynaReporter, do którego
 * zespół jest przyzwyczajony, ma tam pasek sekcji.
 *
 * Świadomie NA KOTWICACH (`<a href="#id">`), nie na `scrollIntoView`:
 * kotwica działa bez JS, wchodzi do historii przeglądarki (Wstecz wraca tam,
 * skąd się przyszło) i daje się skopiować jako link do konkretnej sekcji.
 * Odpowiednikiem po stronie sekcji jest `InsightsSection` niżej — to on
 * dokłada `scroll-mt`, bez którego nagłówek sekcji chowa się pod paskiem
 * aplikacji i wygląda, jakby kotwica trafiła w złe miejsce.
 *
 * Kotwica sama NIE wystarcza, odkąd sekcje montują się leniwie: treść nad
 * celem rośnie po skoku i cel odjeżdża (reaudyt 14.09.2026, R03). Dlatego
 * kliknięcie, bezpośredni `#hash` i Wstecz/Dalej dodatkowo przypinają cel
 * (`pinAnchor`) na czas doczytywania — do pierwszej akcji użytkownika.
 */

export interface InsightsSectionNavItem {
  /** Musi być identyczne z `id` odpowiadającego `InsightsSection`. */
  id: string;
  label: string;
}

export function InsightsSectionNav({
  items,
  ariaLabel = "Sekcje zakładki",
  className,
}: {
  items: InsightsSectionNavItem[];
  ariaLabel?: string;
  className?: string;
}) {
  const idsKey = items.map((item) => item.id).join("|");

  // Bezpośredni link z `#sekcja` i nawigacja Wstecz/Dalej też muszą trafić.
  useEffect(() => {
    const ids = new Set(idsKey.split("|"));
    const pinCurrentHash = () => {
      const id = decodeURIComponent(window.location.hash.slice(1));
      if (id && ids.has(id)) pinAnchor(id);
    };
    pinCurrentHash();
    window.addEventListener("hashchange", pinCurrentHash);
    return () => window.removeEventListener("hashchange", pinCurrentHash);
  }, [idsKey]);

  // Jedna pozycja to nie jest spis treści — pasek nad pojedynczą sekcją
  // dodaje szum i sugeruje, że gdzieś dalej jest coś jeszcze.
  if (items.length < 2) return null;

  return (
    <nav
      aria-label={ariaLabel}
      className={cn(
        "flex flex-wrap items-center gap-1 rounded-xl border border-border bg-card p-1.5 shadow-xs",
        className,
      )}
    >
      {items.map((item) => (
        <a
          key={item.id}
          href={`#${item.id}`}
          // Ponowne kliknięcie tej samej kotwicy nie wywołuje `hashchange`,
          // więc przypinamy także tutaj (po domyślnej nawigacji przeglądarki).
          onClick={() => window.setTimeout(() => pinAnchor(item.id), 0)}
          className="rounded-lg px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}

/**
 * Kotwica sekcji.
 *
 * `scroll-mt-20` jest tu load-bearing: bez marginesu przewijania kotwica
 * ustawia górną krawędź sekcji dokładnie pod przyklejonym paskiem aplikacji,
 * więc nagłówek znika i użytkownik ląduje w środku treści.
 */
export function InsightsSection({
  id,
  children,
  className,
}: {
  id: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div id={id} className={cn("scroll-mt-20", className)}>
      {children}
    </div>
  );
}
