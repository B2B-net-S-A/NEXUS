"use client";

import { useCallback } from "react";
import { List } from "lucide-react";

import { cn } from "@/lib/utils";

export interface ProcedureHeading {
  id: string;
  text: string;
  level: 2 | 3;
}

/**
 * Spis treści procedury — nawigacja po długim dokumencie w module Pomoc.
 *
 * Powstał dla instrukcji obsługi zamówień, która ma osobną sekcję dla każdego
 * klienta: bez skoków czytelnik przewija kilkanaście ekranów, żeby znaleźć
 * „swojego" klienta, i w praktyce czyta nie tę sekcję, co trzeba.
 *
 * Nagłówki NIE są wyliczane z Markdownu, tylko odczytywane z wyrenderowanego
 * DOM-u (patrz `useProcedureHeadings`). Parser Markdownu po naszej stronie
 * musiałby powtórzyć zachowanie `react-markdown` co do joty — bloki kodu,
 * nagłówki setext (podkreślone `---`), encje HTML — a każdy rozjazd oznacza
 * link prowadzący w złe miejsce albo donikąd. DOM jest tym samym źródłem,
 * które widzi czytelnik, więc rozjazd jest niemożliwy z definicji.
 */
export function ProcedureTableOfContents({
  headings,
  className,
}: {
  headings: ProcedureHeading[];
  className?: string;
}) {
  const jumpTo = useCallback((id: string) => {
    const target = document.getElementById(id);
    if (!target) return;
    // BEZ `behavior: "smooth"` — i to jest wymóg, nie przeoczenie. Treść
    // procedury przewija się w zagnieżdżonym `<main class="overflow-y-auto">`,
    // którego przodkowie mają `overflow: hidden` (powłoka aplikacji). W takim
    // układzie Chrome CICHO POMIJA płynne przewijanie: zmierzone na produkcji
    // `scrollIntoView({behavior:"smooth"})` zostawiało `scrollTop` bez zmian,
    // a ta sama instrukcja bez `behavior` przewijała do 10353 px. To samo
    // dotyczy `scrollTo({behavior:"smooth"})` na kontenerze.
    //
    // Objaw był najgorszy z możliwych: klik w spis treści wyglądał na
    // działający (element dostawał fokus), ale czytelnik zostawał tam, gdzie
    // był. Lokalny harness tego nie łapał, bo przewijało się w nim OKNO —
    // dlatego `/preview/procedure-help` odtwarza dziś układ powłoki.
    target.scrollIntoView({ block: "start" });
    // Fokus dla czytników ekranu i klawiatury: samo przewinięcie przesuwa
    // obraz, ale zostawia karetkę na liście, więc następny Tab wraca na górę
    // dokumentu zamiast wejść w sekcję, do której użytkownik właśnie skoczył.
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  }, []);

  if (headings.length === 0) return null;

  return (
    <nav
      aria-label="Spis treści"
      className={cn(
        "not-prose mb-6 rounded-lg border border-border bg-muted/40 px-4 py-3",
        className,
      )}
    >
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        <List className="h-3.5 w-3.5" aria-hidden="true" /> Spis treści
      </p>
      <ul className="mt-2 space-y-1">
        {headings.map((heading) => (
          <li key={heading.id} className={heading.level === 3 ? "pl-4" : undefined}>
            <button
              type="button"
              onClick={() => jumpTo(heading.id)}
              className={cn(
                "text-left text-sm text-foreground/90 underline-offset-2 hover:text-primary hover:underline",
                heading.level === 3 && "text-xs text-muted-foreground",
              )}
            >
              {heading.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
