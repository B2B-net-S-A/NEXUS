"use client";

/**
 * Filtry Tablicy. Od 22.09.2026 jeden pasek nad tablicą (`PipelineFilterBar`)
 * zastąpił dawną lewą kolumnę „PipelineFiltersRail" (krok 04, program
 * „flow w języku C2", PR 3/7; fala 3 „parytet z makietami").
 *
 * Czysto prezentacyjny (poza rozwinięciem grupy) — `KanbanBoardV2` liczy
 * grupy, liczniki i trzyma filtry, ten komponent tylko je pokazuje i emituje
 * zdarzenia. Dzięki temu jest łatwy do przetestowania w izolacji.
 *
 * Fala 3: piętnaście wierszy etapów zastąpione SZEŚCIOMA grupami
 * ({@link groupKanbanColumns}) — w „Default B2B" trzynaście kolumn jest
 * pustych, więc płaska lista była w praktyce listą zer. Wiersze etapów nie
 * zniknęły: rozwijają się pod grupą, klik wciąż fokusuje kolumnę
 * (`onFocusColumn`). Szablon, którego backend nie zmapował na legacy enumy,
 * daje jedną grupę — wtedy grupowanie nic nie wnosi i rail pokazuje płaską
 * listę jak wcześniej.
 *
 * Filtry „Utknęli > 7 d" / „Bez następnej akcji" / „Ostrzeżenia" /
 * „Rekruter" NIE usuwają kart z tablicy (usunięcie zepsułoby indeksy
 * `@hello-pangea/dnd` używane przez `onDragEnd` — patrz komentarz
 * w `KanbanBoardV2`) — przyciemniają niepasujące karty. Stąd liczniki obok
 * etykiet: ukrywanie nigdy nie jest ciche (kontrakt programu C2).
 */

import { LayoutGrid, Timer, Users } from "lucide-react";

import { cn } from "@/lib/utils";

function FilterPill({
  active,
  onClick,
  label,
  title,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-background text-foreground hover:bg-accent"
      )}
    >
      {label}
    </button>
  );
}

/**
 * Pasek filtrów Tablicy (makieta 22.09.2026) — jeden wiersz nad tablicą
 * zamiast kolumny 230 px. Te same filtry co dawna kolumna (przyciemniają,
 * nie usuwają kart), plus „Mój ruch" i szukanie po nazwisku. Lista etapów
 * zniknęła, bo fokus kolumny daje nawigator etapów nad tablicą.
 */
export function PipelineFilterBar({
  nameQuery,
  onNameQueryChange,
  myMoveFilter,
  onToggleMyMoveFilter,
  myMoveCount,
  stuckFilter,
  onToggleStuckFilter,
  stuckCount,
  noActionFilter,
  onToggleNoActionFilter,
  noActionCount,
  blockedFilter,
  onToggleBlockedFilter,
  blockedCount,
  offTemplateCount,
  onFocusOffTemplate,
  recruiters,
  recruiterFilter,
  onSetRecruiterFilter,
  hideEmptyColumns,
  onToggleHideEmptyColumns,
  slaDays,
  slaClientName,
  slaLoading,
}: {
  nameQuery: string;
  onNameQueryChange: (value: string) => void;
  myMoveFilter: boolean;
  onToggleMyMoveFilter: () => void;
  myMoveCount: number;
  stuckFilter: boolean;
  onToggleStuckFilter: () => void;
  stuckCount: number;
  noActionFilter: boolean;
  onToggleNoActionFilter: () => void;
  noActionCount: number;
  blockedFilter: boolean;
  onToggleBlockedFilter: () => void;
  blockedCount: number;
  offTemplateCount: number;
  onFocusOffTemplate: () => void;
  recruiters: string[];
  recruiterFilter: string | null;
  onSetRecruiterFilter: (name: string | null) => void;
  hideEmptyColumns: boolean;
  onToggleHideEmptyColumns: () => void;
  slaDays: number | null;
  slaClientName: string | null;
  slaLoading: boolean;
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-1.5 rounded-xl border border-border bg-card px-3 py-2"
      role="toolbar"
      aria-label="Filtry tablicy"
    >
      <input
        id="pipeline-name-filter"
        value={nameQuery}
        onChange={(e) => onNameQueryChange(e.target.value)}
        placeholder="Filtruj po nazwisku…"
        aria-label="Filtruj po nazwisku"
        className="h-7 w-48 rounded-md border border-border bg-background px-2 text-xs focus:outline-hidden focus:ring-2 focus:ring-ring"
      />
      <FilterPill
        active={myMoveFilter}
        onClick={onToggleMyMoveFilter}
        label={myMoveCount > 0 ? `Mój ruch · ${myMoveCount}` : "Mój ruch"}
        title="Podświetl karty, na których następny krok należy do rekrutera"
      />
      <FilterPill
        active={stuckFilter}
        onClick={onToggleStuckFilter}
        label={stuckCount > 0 ? `Utknęli > 7 d · ${stuckCount}` : "Utknęli > 7 d"}
        title="Podświetl kandydatów stojących na etapie dłużej niż 7 dni"
      />
      <FilterPill
        active={noActionFilter}
        onClick={onToggleNoActionFilter}
        label={
          noActionCount > 0 ? `Bez następnej akcji · ${noActionCount}` : "Bez następnej akcji"
        }
        title="Podświetl karty, dla których etap nie podpowiada już żadnego następnego kroku"
      />
      <FilterPill
        active={blockedFilter}
        onClick={onToggleBlockedFilter}
        label={blockedCount > 0 ? `Ostrzeżenia · ${blockedCount}` : "Ostrzeżenia"}
        title="Podświetl kandydatów z ostrzeżeniem (weto hiring managera) — ruch nie jest blokowany"
      />
      {offTemplateCount > 0 && (
        <FilterPill
          active={false}
          onClick={onFocusOffTemplate}
          label={`Poza szablonem · ${offTemplateCount}`}
          title="Przewiń do kolumny z kartami spoza szablonu"
        />
      )}
      {recruiters.length > 1 && (
        <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <Users className="h-3 w-3" aria-hidden="true" />
          <select
            aria-label="Rekruter"
            value={recruiterFilter ?? ""}
            onChange={(e) => onSetRecruiterFilter(e.target.value || null)}
            className="h-7 rounded-md border border-border bg-background px-1.5 text-xs text-foreground"
          >
            <option value="">Wszyscy rekruterzy</option>
            {recruiters.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      )}
      <button
        type="button"
        onClick={onToggleHideEmptyColumns}
        aria-pressed={hideEmptyColumns}
        className={cn(
          "inline-flex h-7 items-center gap-1 rounded-md border px-2 text-[11px] transition-colors",
          hideEmptyColumns
            ? "border-primary bg-primary/10 font-medium text-primary"
            : "border-border bg-background text-foreground hover:bg-accent",
        )}
      >
        <LayoutGrid className="h-3 w-3" />
        Kolumny: {hideEmptyColumns ? "pokaż puste" : "ukryj puste"}
      </button>
      {/* SLA klienta — z karty klienta; brak mówimy wprost, bo cisza
          czytałaby się jak „zdążamy". */}
      <span
        className="ml-auto inline-flex items-center gap-1 text-[11px] text-muted-foreground"
        title="SLA klienta z karty klienta — dni robocze na CV od wejścia w Screening"
      >
        <Timer className="h-3 w-3" aria-hidden="true" />
        {slaLoading
          ? "SLA: wczytywanie…"
          : slaDays != null
            ? `SLA ${slaClientName?.trim() || "klienta"}: ${slaDays} ${slaDays === 1 ? "dzień roboczy" : "dni roboczych"}`
            : "SLA: nie ustawiono w karcie klienta"}
      </span>
    </div>
  );
}
