"use client";

/**
 * Filtr „Obecnych konsultantów" Centrum e-Zdrowia po UMOWIE WYKONAWCZEJ
 * (struktura umów, ticket 09.2026). Zastępuje dawny filtr po części:
 * pigułki są pogrupowane pod nagłówkami części, a część BEZ umowy
 * wykonawczej nadal jest widoczna (kursywa, nieklikalna) — ukrycie jej
 * czytałoby się jak brak części, a nie brak umowy.
 */

import {
  frameworkPartHeader,
  useContractStructure,
  type FrameworkPartRead,
} from "@/lib/api/executiveContracts";
import {
  filterConsultantsByExecutiveContract,
  isSameAssignmentFilter,
  type ConsultantAssignmentFilter,
} from "@/lib/ezdrowie";
import { cn } from "@/lib/utils";

interface Props {
  clientId: number;
  consultants: { executive_contract?: { id: number } | null }[];
  value: ConsultantAssignmentFilter;
  onChange: (next: ConsultantAssignmentFilter) => void;
}

export function ExecutiveContractFilter({
  clientId,
  consultants,
  value,
  onChange,
}: Props) {
  // Ten sam klucz zapytania co sekcja „Struktura umów" nad tabelą — react-query
  // scala oba wywołania w jedno żądanie.
  const structure = useContractStructure(clientId);
  const unassignedCount = filterConsultantsByExecutiveContract(
    consultants,
    "unassigned",
  ).length;
  const frameworks: FrameworkPartRead[] = structure.data?.framework_contracts ?? [];

  return (
    <div
      className="flex flex-col gap-2"
      role="group"
      aria-label="Filtr umów wykonawczych"
    >
      <div className="flex flex-wrap gap-2">
        <FilterPill
          active={value === "all"}
          onClick={() => onChange("all")}
        >
          Wszystkie
        </FilterPill>
        {/* Pigułka „Nieprzypisani" tylko gdy jest kogo przypisać — pusta
            pigułka sugerowałaby zaległość, której nie ma. */}
        {unassignedCount > 0 ? (
          <FilterPill
            active={value === "unassigned"}
            onClick={() => onChange("unassigned")}
          >
            Nieprzypisani ({unassignedCount})
          </FilterPill>
        ) : null}
      </div>
      {structure.isError ? (
        <p className="text-xs text-destructive" role="alert">
          Nie udało się wczytać struktury umów — filtr po umowie wykonawczej
          jest niedostępny.
        </p>
      ) : null}
      {frameworks.map((fc) => (
        <div key={fc.id} className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {frameworkPartHeader(fc)}
          </span>
          {fc.executive_contracts.length === 0 ? (
            <span
              className="text-xs italic text-muted-foreground"
              aria-disabled="true"
            >
              brak umowy wykonawczej
            </span>
          ) : (
            fc.executive_contracts.map((ec) => (
              <FilterPill
                key={ec.id}
                active={isSameAssignmentFilter(value, {
                  executiveContractId: ec.id,
                })}
                onClick={() => onChange({ executiveContractId: ec.id })}
              >
                {ec.number}
                {ec.status === "ended" ? (
                  <span className="ml-1 opacity-60">(zakończona)</span>
                ) : null}
              </FilterPill>
            ))
          )}
        </div>
      ))}
    </div>
  );
}

/** Pigułka filtra — przeniesiona z `ProfileTab` (dawny `PartFilterPill`). */
export function FilterPill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "px-3 py-1 text-xs font-medium rounded-full border transition-colors",
        active
          ? "bg-primary/10 border-primary/40 text-primary"
          : "border-border text-muted-foreground hover:text-foreground hover:border-primary/30",
      )}
    >
      {children}
    </button>
  );
}
