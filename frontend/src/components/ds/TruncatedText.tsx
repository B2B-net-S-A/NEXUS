"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Długa wartość tekstowa w komórce tabeli — przycięta, z pełną treścią w tooltipie.
 *
 * Powód istnienia: nazwa klienta bywa pełną nazwą rejestrową („CARDIF -
 * ASSURANCES RISQUES DIVERS SPÓŁKA AKCYJNA ODDZIAŁ W POLSCE"), a komórka
 * tabeli bez ograniczenia szerokości rozpycha kolumnę na pół ekranu i zsuwa
 * resztę wierszy poza widok. Problem nie dotyczy jednego klienta — dotyczy
 * każdej długiej wartości w każdej tabeli, więc reguła mieszka w JEDNYM
 * komponencie zamiast w kilkunastu kopiach `truncate max-w-[...]`.
 *
 * Dlaczego przycięcie, a nie zawijanie: kolumny sąsiadują z datami, stawkami
 * i statusami, których wiersz ma być czytelny jednym rzutem oka. Zawijanie
 * rozciąga wiersz w pionie i rozjeżdża wyrównanie sąsiednich komórek; ucięcie
 * zostawia stałą wysokość, a pełną treść oddaje `title` (i tekst dla czytnika
 * ekranu, bo `title` jest odczytywany).
 *
 * `max-w` jest DOMYŚLNE, nie sztywne — kolumna z krótkimi wartościami może je
 * zawęzić, a szeroka rozszerzyć, podając własne `className`.
 */
export interface TruncatedTextProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  /** Treść; `null`/`undefined`/pusty string renderują `fallback`. */
  children?: string | null;
  /** Co pokazać zamiast pustej wartości. Domyślnie „—”. */
  fallback?: string;
}

export function TruncatedText({
  children,
  fallback = "—",
  className,
  ...props
}: TruncatedTextProps) {
  const text = children?.trim() ? children : null;
  return (
    <span
      // `block`, bo `truncate` (overflow hidden + ellipsis) nie działa na
      // elemencie inline — bez tego cała reguła jest dekoracją bez skutku.
      className={cn("block max-w-[220px] truncate", className)}
      // Tooltip TYLKO dla realnej wartości: `title="—"` przy pustej komórce to
      // dymek, który nic nie mówi.
      title={text ?? undefined}
      {...props}
    >
      {text ?? fallback}
    </span>
  );
}
