"use client";

/**
 * PipelineFiltersRail — lewa kolumna zakładki „Pipeline" (krok 04, program
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
 * Filtry „Utknęli > 7 d" / „Bez następnej akcji" / „Zablokowani bramką" /
 * „Rekruter" NIE usuwają kart z tablicy (usunięcie zepsułoby indeksy
 * `@hello-pangea/dnd` używane przez `onDragEnd` — patrz komentarz
 * w `KanbanBoardV2`) — przyciemniają niepasujące karty. Stąd liczniki obok
 * etykiet: ukrywanie nigdy nie jest ciche (kontrakt programu C2).
 */

import { ChevronDown, ChevronRight, Filter, LayoutGrid, Timer, Users } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";
import { colId, columnLabel, type KanbanColumn } from "@/components/v2/pages/kanban-shared";
import type { PipelineColumnGroup, PipelineGroupKey } from "@/lib/pipeline-flow";

const STAGE_DOT_COLOR: Record<string, string> = {
  internal: "bg-primary",
  external: "bg-card border border-border",
  terminal: "bg-muted-foreground",
};

/**  Kropka grupy czyta się jak sygnalizator: zielona = świeże wejście,
 *   bursztynowa = tu biegnie SLA klienta, czerwona = zamknięci. Reszta jest
 *   neutralna — kolor bez znaczenia byłby szumem. */
const GROUP_DOT_COLOR: Record<PipelineGroupKey, string> = {
  intake: "bg-success",
  screening: "bg-warning",
  verification: "bg-muted-foreground/50",
  client: "bg-muted-foreground/50",
  contract: "bg-muted-foreground/50",
  closed: "bg-destructive",
};

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

/** Wiersz etapu — ten sam kształt dla listy płaskiej i rozwiniętej grupy. */
function StageRow({
  col,
  active,
  nested,
  onFocus,
}: {
  col: KanbanColumn;
  active: boolean;
  nested?: boolean;
  onFocus: (id: string) => void;
}) {
  const id = colId(col);
  return (
    <button
      type="button"
      role="listitem"
      onClick={() => onFocus(id)}
      aria-current={active ? "true" : undefined}
      className={cn(
        "flex w-full items-center gap-2 rounded-md py-1 text-left text-[11px] transition-colors",
        nested ? "pl-6 pr-2" : "px-2 py-1.5 text-xs",
        active ? "bg-primary/10 font-medium text-primary" : "text-foreground hover:bg-accent"
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          STAGE_DOT_COLOR[col.category ?? "internal"]
        )}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 truncate">{columnLabel(col)}</span>
      <span className="tabular-nums text-muted-foreground">{col.count}</span>
    </button>
  );
}

export interface PipelineFiltersRailProps {
  /** Kolumny SZABLONU (bez kubełka „Poza szablonem") — do listy etapów. */
  stageCols: KanbanColumn[];
  /** Grupy etapów policzone nad `stageCols` ({@link groupKanbanColumns}). */
  groups: PipelineColumnGroup[];
  /** Nazwa szablonu pipeline'u — z danych, które board i tak już pobiera. */
  templateName?: string | null;
  focusedColId: string | null;
  onFocusColumn: (id: string) => void;
  /** 0 = kubełek nie istnieje / jest pusty → pigułka się nie renderuje. */
  offTemplateCount: number;
  onFocusOffTemplate: () => void;
  stuckFilter: boolean;
  onToggleStuckFilter: () => void;
  stuckCount: number;
  noActionFilter: boolean;
  onToggleNoActionFilter: () => void;
  noActionCount: number;
  blockedFilter: boolean;
  onToggleBlockedFilter: () => void;
  blockedCount: number;
  recruiters: string[];
  recruiterFilter: string | null;
  onSetRecruiterFilter: (name: string | null) => void;
  hideEmptyColumns: boolean;
  onToggleHideEmptyColumns: () => void;
  /** SLA klienta w dniach roboczych — z karty klienta (`client_playbooks`). */
  slaDays?: number | null;
  slaClientName?: string | null;
  slaLoading?: boolean;
}

export function PipelineFiltersRail({
  stageCols,
  groups,
  templateName,
  focusedColId,
  onFocusColumn,
  offTemplateCount,
  onFocusOffTemplate,
  stuckFilter,
  onToggleStuckFilter,
  stuckCount,
  noActionFilter,
  onToggleNoActionFilter,
  noActionCount,
  blockedFilter,
  onToggleBlockedFilter,
  blockedCount,
  recruiters,
  recruiterFilter,
  onSetRecruiterFilter,
  hideEmptyColumns,
  onToggleHideEmptyColumns,
  slaDays,
  slaClientName,
  slaLoading,
}: PipelineFiltersRailProps) {
  const [expandedGroup, setExpandedGroup] = useState<PipelineGroupKey | null>(null);

  // Jedna grupa = grupowanie nic nie wnosi (szablon bez zmapowanych etapów) →
  // płaska lista jak przed falą 3, zamiast jednego wiersza-nagłówka nad całą
  // tablicą.
  const grouped = groups.length > 1;
  const activeTotal = groups
    .filter((g) => g.key !== "closed")
    .reduce((sum, g) => sum + g.count, 0);

  const focusGroup = (group: PipelineColumnGroup) => {
    setExpandedGroup((prev) => (prev === group.key ? null : group.key));
    const target = group.columns.find((c) => c.count > 0) ?? group.columns[0];
    if (target) onFocusColumn(colId(target));
  };

  const focusAllActive = () => {
    setExpandedGroup(null);
    const target =
      stageCols.find((c) => c.count > 0 && c.category !== "terminal") ?? stageCols[0];
    if (target) onFocusColumn(colId(target));
  };

  return (
    <aside className="space-y-4 self-start rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <LayoutGrid className="h-4 w-4 text-primary" />
        Etapy
        {templateName?.trim() && (
          <span
            className="ml-auto min-w-0 truncate text-[11px] font-medium text-primary"
            title={`Szablon pipeline'u: ${templateName.trim()}`}
          >
            {templateName.trim()}
          </span>
        )}
      </div>

      {grouped ? (
        <div className="space-y-0.5" role="list" aria-label="Grupy etapów pipeline">
          <button
            type="button"
            role="listitem"
            onClick={focusAllActive}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-accent"
          >
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate font-medium">Wszystkie aktywne</span>
            <span className="tabular-nums text-muted-foreground">{activeTotal}</span>
          </button>

          {groups.map((group) => {
            const expanded = expandedGroup === group.key;
            return (
              <div key={group.key} role="listitem">
                <button
                  type="button"
                  onClick={() => focusGroup(group)}
                  aria-expanded={expanded}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                    expanded
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-foreground hover:bg-accent"
                  )}
                >
                  <span
                    className={cn("h-1.5 w-1.5 shrink-0 rounded-full", GROUP_DOT_COLOR[group.key])}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate">{group.label}</span>
                  <span className="tabular-nums text-muted-foreground">{group.count}</span>
                  {expanded ? (
                    <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
                  ) : (
                    <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
                  )}
                </button>
                {expanded && (
                  <div
                    className="space-y-0.5 border-l border-border pb-1 pl-1"
                    role="list"
                    aria-label={`Etapy grupy ${group.label}`}
                  >
                    {group.columns.map((col) => (
                      <StageRow
                        key={colId(col)}
                        col={col}
                        nested
                        active={colId(col) === focusedColId}
                        onFocus={onFocusColumn}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        stageCols.length > 0 && (
          <div className="space-y-0.5" role="list" aria-label="Etapy pipeline">
            {stageCols.map((col) => (
              <StageRow
                key={colId(col)}
                col={col}
                active={colId(col) === focusedColId}
                onFocus={onFocusColumn}
              />
            ))}
          </div>
        )
      )}

      <div className="space-y-1.5 border-t border-border pt-3">
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
          <Filter className="h-3 w-3" />
          Pokaż
        </div>
        <div className="flex flex-wrap gap-1">
          <FilterPill
            active={stuckFilter}
            onClick={onToggleStuckFilter}
            label={
              stuckCount > 0 ? `Utknęli > 7 d · ${stuckCount}` : "Utknęli > 7 d"
            }
            title="Podświetl kandydatów stojących na etapie dłużej niż 7 dni"
          />
          <FilterPill
            active={noActionFilter}
            onClick={onToggleNoActionFilter}
            label={
              noActionCount > 0
                ? `Bez następnej akcji · ${noActionCount}`
                : "Bez następnej akcji"
            }
            title="Podświetl karty, dla których etap nie podpowiada już żadnego następnego kroku"
          />
          <FilterPill
            active={blockedFilter}
            onClick={onToggleBlockedFilter}
            label={
              blockedCount > 0
                ? `Zablokowani bramką · ${blockedCount}`
                : "Zablokowani bramką"
            }
            title="Podświetl kandydatów zablokowanych przez bramkę dopuszczalności lub weryfikację"
          />
          {offTemplateCount > 0 && (
            <FilterPill
              active={false}
              onClick={onFocusOffTemplate}
              label={`Poza szablonem · ${offTemplateCount}`}
              title="Przewiń do kolumny z kartami spoza szablonu"
            />
          )}
        </div>
      </div>

      {recruiters.length > 1 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
            <Users className="h-3 w-3" />
            Rekruter
          </div>
          <div className="flex flex-wrap gap-1">
            <FilterPill
              active={recruiterFilter == null}
              onClick={() => onSetRecruiterFilter(null)}
              label="Wszyscy"
            />
            {recruiters.map((name) => (
              <FilterPill
                key={name}
                active={recruiterFilter === name}
                onClick={() =>
                  onSetRecruiterFilter(recruiterFilter === name ? null : name)
                }
                label={name}
              />
            ))}
          </div>
        </div>
      )}

      {/* SLA klienta — z karty klienta (`client_playbooks.sla_business_days`),
          tej samej, którą czyta krok 06 „CV do klienta". Brak karty albo brak
          SLA mówimy WPROST: cisza w tym miejscu czytałaby się jak „zdążamy". */}
      <div className="space-y-1 border-t border-border pt-3">
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
          <Timer className="h-3 w-3" />
          SLA klienta
        </div>
        <p className="text-[11px] leading-snug text-muted-foreground">
          {slaLoading ? (
            "Wczytywanie karty klienta…"
          ) : slaDays != null ? (
            <>
              <span className="font-medium text-foreground">
                {slaClientName?.trim() || "Klient"}
              </span>
              : {slaDays} {slaDays === 1 ? "dzień roboczy" : "dni roboczych"} na CV od
              wejścia w Screening. Kolumny pokazują, ile zostało.
            </>
          ) : (
            "Nie ustawiono w karcie klienta."
          )}
        </p>
      </div>

      <div className="border-t border-border pt-3">
        <button
          type="button"
          onClick={onToggleHideEmptyColumns}
          aria-pressed={hideEmptyColumns}
          className={cn(
            "flex w-full items-center justify-center gap-1.5 rounded-lg border px-2 py-1.5 text-xs transition-colors",
            hideEmptyColumns
              ? "border-primary bg-primary/10 font-medium text-primary"
              : "border-border bg-background text-foreground hover:bg-accent"
          )}
        >
          <LayoutGrid className="h-3.5 w-3.5" />
          Kolumny: {hideEmptyColumns ? "pokaż puste" : "ukryj puste"}
        </button>
      </div>
    </aside>
  );
}
