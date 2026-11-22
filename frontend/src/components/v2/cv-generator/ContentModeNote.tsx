"use client";

export interface ContentModeNoteProps {
  hasChampion: boolean;
  /** Sufit klienta „Przepisanie” — powstaje CV bez redakcji i bez dopasowania. */
  capBasic?: boolean;
  /**
   * Champion da się dodać obok (okno generatora). Karta „CV do klienta” tego
   * nie ma — Championa uzupełnia się w rekrutacji, więc podpowiedź o tym mówi.
   */
  canAddChampion?: boolean;
  /** Etykieta nad tekstem — wąska karta „CV do klienta” (kolumna 110 px się nie mieści). */
  compact?: boolean;
}

/**
 * Jedna linia zamiast kafli „Redakcja / Pod rekrutację” (zdjęte 22.11.2026,
 * decyzja Artura): każde CV powstaje pod rekrutację. Bez kompletnego Championa
 * serwer sam robi CV bez dopasowania i dopisuje uwagę (`central_policies.resolve_mode`).
 */
export function ContentModeNote({
  hasChampion,
  capBasic = false,
  canAddChampion = true,
  compact = false,
}: ContentModeNoteProps) {
  const label = capBasic ? "Przepisanie" : hasChampion ? "Pod rekrutację" : "Bez dopasowania";
  const hint = capBasic
    ? "Ten klient przyjmuje wyłącznie przepisanie faktów z CV — bez redakcji i bez dopasowania do rekrutacji."
    : hasChampion
      ? "Dopasujemy CV do wymagań tej rekrutacji: kolejność doświadczeń i pogrubione technologie MUST."
      : canAddChampion
        ? "Rekrutacja nie ma Profilu Championa, więc CV powstanie bez dopasowania do wymagań. Wgraj Championa wyżej, a CV dopasujemy."
        : "Rekrutacja nie ma Profilu Championa, więc CV powstanie bez dopasowania do wymagań. Po uzupełnieniu Championa w rekrutacji kliknij „Dopasuj pod rekrutację” w edytorze CV.";
  return (
    <div
      data-testid="cv-content-mode-note"
      className={compact ? "grid gap-1" : "grid gap-1 sm:grid-cols-[110px_minmax(0,1fr)] sm:items-start"}
    >
      <p className="text-sm font-semibold text-foreground">Treść</p>
      <div className="space-y-1">
        <p className="text-sm text-foreground">{label}</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
      </div>
    </div>
  );
}
