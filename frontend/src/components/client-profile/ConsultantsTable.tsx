"use client";

import Link from "next/link";
import { CompetenceCategoryName } from "@/components/v2/CompetenceCategoryBadge";
import type { ExecutiveContractBrief } from "@/lib/api/executiveContracts";
import { projectPartLabel } from "@/lib/ezdrowie";
import { Badge } from "@/components/ui/badge";
import {
  CALM_AMOUNT,
  CALM_EMPTY,
  CALM_HEAD,
  CALM_ROW,
  CALM_SUBLINE,
} from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import type {
  ActiveConsultantItem,
  HistoricalPlacementItem,
} from "@/types/client-profile";
import { formatDate, formatPLN } from "@/types/client-profile";

/**
 * Wspólny wiersz obu zakładek. Archiwum niesie te same pola co „Obecni",
 * więc jeden typ pokrywa oba — różni je wyłącznie obecność daty zakończenia.
 */
export interface ConsultantTableRow {
  contract_id: number;
  candidate: ActiveConsultantItem["candidate"];
  job_id: number | null;
  job_title: string | null;
  job_from_order: boolean;
  start_date: string | null;
  end_date: string | null;
  hourly_rate_candidate: number | null;
  hourly_rate_client: number | null;
  monthly_margin: number | null;
  days_to_end?: number | null;
  project_part?: string | null;
  /** e-Zdrowie: umowa wykonawcza z bieżącego zamówienia (null = nieprzypisany). */
  executive_contract?: ExecutiveContractBrief | null;
}

export function toConsultantRow(
  c: ActiveConsultantItem | HistoricalPlacementItem,
): ConsultantTableRow {
  return {
    contract_id: c.contract_id,
    candidate: c.candidate,
    job_id: c.job_id,
    job_title: c.job_title,
    job_from_order: c.job_from_order,
    start_date: c.start_date ?? null,
    end_date: c.end_date ?? null,
    hourly_rate_candidate: c.hourly_rate_candidate ?? null,
    hourly_rate_client: c.hourly_rate_client ?? null,
    monthly_margin: c.monthly_margin,
    days_to_end: "days_to_end" in c ? c.days_to_end : null,
    project_part: "project_part" in c ? c.project_part : null,
    executive_contract: "executive_contract" in c ? c.executive_contract : null,
  };
}

interface Props {
  rows: ConsultantTableRow[];
  /** Archiwum dokłada kolumnę „End date" — jedyna różnica między zakładkami. */
  showEndDate?: boolean;
  /** Zawartość kolumny „Akcje" dla danego wiersza. Brak = kolumny nie ma. */
  renderActions?: (row: ConsultantTableRow) => React.ReactNode;
}

function initialsOf(name: string): string {
  return name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

/** Kwota albo przygaszone „—” (backend zeruje kwoty rolom bez podglądu). */
function amount(value: number | null) {
  return value == null ? (
    <span className={CALM_EMPTY}>—</span>
  ) : (
    formatPLN(value)
  );
}

const HEAD_CELL = cn(CALM_HEAD, "py-2 pr-4");
const HEAD_AMOUNT = cn(CALM_HEAD, "py-2 pr-4 text-right");
const AMOUNT_CELL = cn(CALM_AMOUNT, "py-2 pr-4");

export function ConsultantsTable({ rows, showEndDate, renderActions }: Props) {
  return (
    // `min-w` + przyklejona kolumna „Konsultant": na telefonie tabela
    // przewija się w bok zamiast ściskać nagłówki do trzech linii, a po
    // przewinięciu nadal widać, czyj to wiersz. Tło komórki = tło karty profilu.
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <th className={cn(HEAD_CELL, "sticky left-0 z-10 bg-card dark:bg-muted")}>Konsultant</th>
            <th className={HEAD_CELL}>Start date</th>
            <th className={HEAD_AMOUNT}>Stawka kosztowa [godz.]</th>
            <th className={HEAD_AMOUNT}>Stawka przychodowa [godz.]</th>
            {/* Marża zostaje miesięczna — „Aktywne MRR" w nagłówku jest jej sumą. */}
            <th className={HEAD_AMOUNT}>Marża [mc]</th>
            {showEndDate ? (
              <th className={HEAD_CELL}>End date</th>
            ) : null}
            {renderActions ? (
              <th className={cn(CALM_HEAD, "py-2 text-right")}>Akcje</th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.contract_id} className={cn(CALM_ROW, "h-[52px] last:border-b-0")}>
              <td className="sticky left-0 z-10 bg-card py-2 pr-4 dark:bg-muted">
                <div className="flex items-center gap-2.5">
                  {r.candidate.avatar_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={r.candidate.avatar_url}
                      alt={r.candidate.name}
                      className="h-7 w-7 shrink-0 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted">
                      <span className="text-[10.5px] font-semibold text-muted-foreground">
                        {initialsOf(r.candidate.name)}
                      </span>
                    </div>
                  )}
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      {r.candidate.id != null ? (
                        <Link
                          href={`/candidates/${r.candidate.id}`}
                          className="truncate font-semibold text-foreground hover:text-primary"
                        >
                          {r.candidate.name}
                        </Link>
                      ) : (
                        // Kandydat usunięty (RODO) — kontrakt został, profilu
                        // nie ma (audyt S6). Wiersz zostaje, bo jego marża
                        // wchodzi do „Aktywnego MRR” w nagłówku.
                        <span className="truncate font-semibold text-muted-foreground">
                          {r.candidate.name}
                        </span>
                      )}
                      {r.candidate.competence_category ? (
                        <span className="rounded-md bg-muted px-1.5 text-[11px] leading-[18px] text-muted-foreground">
                          <CompetenceCategoryName slug={r.candidate.competence_category} />
                        </span>
                      ) : null}
                      {/* e-Zdrowie: NUMER umowy wykonawczej, część w tooltipie.
                          Fallback na samą część = wiersz sprzed wdrożenia
                          struktury (do przeglądu w sekcji „Struktura umów") —
                          ukrycie go czytałoby się jak brak przypisania w ogóle. */}
                      {r.executive_contract ? (
                        <span
                          className="rounded-md bg-info-muted px-1.5 text-[11px] font-medium leading-[18px] text-info-muted-foreground"
                          title={
                            projectPartLabel(r.executive_contract.project_part) ??
                            "Umowa wykonawcza"
                          }
                        >
                          {r.executive_contract.number}
                        </span>
                      ) : r.project_part ? (
                        <span
                          className="rounded-md bg-info-muted px-1.5 text-[11px] font-medium leading-[18px] text-info-muted-foreground"
                          title="Bez umowy wykonawczej — do przypisania w sekcji „Struktura umów”"
                        >
                          {projectPartLabel(r.project_part)}
                        </span>
                      ) : null}
                      {/* Koniec za mniej niż 30 dni wymaga uwagi — plakietka;
                          dalszy termin to zwykła informacja. */}
                      {r.days_to_end != null ? (
                        r.days_to_end < 30 ? (
                          <Badge size="sm" variant={r.days_to_end < 7 ? "danger" : "warning"}>
                            {r.days_to_end < 0
                              ? "po terminie"
                              : `kończy się za ${r.days_to_end}d`}
                          </Badge>
                        ) : (
                          <span className="text-[11px] text-muted-foreground">
                            kończy się za {r.days_to_end}d
                          </span>
                        )
                      ) : null}
                    </div>
                    {/* Rekrutacja pod nazwiskiem. Brak powiązania = PUSTY
                        wiersz (wymóg ticketu), nie „brak powiązanej
                        rekrutacji" — komunikat zastępczy w kolumnie danych
                        czyta się jak wartość, a nie jak jej brak. */}
                    <p
                      className={cn(CALM_SUBLINE, "mt-0 max-w-[380px] truncate")}
                      title={
                        r.job_from_order
                          ? "Rekrutacja z bieżącego zamówienia — kontrakt nie ma własnego powiązania"
                          : undefined
                      }
                    >
                      {r.job_title ? (
                        r.job_id ? (
                          <Link
                            href={`/jobs/${r.job_id}`}
                            className="hover:text-primary"
                          >
                            {r.job_title}
                          </Link>
                        ) : (
                          r.job_title
                        )
                      ) : (
                        " "
                      )}
                      {/* Tekst rekrutacji jest ten sam, ale PROWENIENCJA inna:
                          `Contract.job_id` mówi „z tej rekrutacji wziął się ten
                          placement", a fallback — „z tej rekrutacji wzięło się
                          bieżące zamówienie". Przy kontrakcie przedłużanym to
                          bywa inna rekrutacja, więc milczące zlanie obu znaczeń
                          w jednej kolumnie byłoby przemilczeniem. */}
                      {r.job_from_order ? (
                        <span className="ml-1 opacity-60">· z zamówienia</span>
                      ) : null}
                    </p>
                  </div>
                </div>
              </td>
              <td className="py-2 pr-4 tabular-nums whitespace-nowrap">
                {r.start_date ? (
                  formatDate(r.start_date)
                ) : (
                  <span className={CALM_EMPTY}>—</span>
                )}
              </td>
              {/* Brak kwoty → „—". Kwoty MUSZĄ renderować się także jako
                  puste: backend zeruje je dla ról bez VIEW_FINANCE, a znikająca
                  komórka zostawiłaby trzy puste kolumny bez wyjaśnienia.
                  Stawki są GODZINOWE (backend przelicza z jednostki zamówienia:
                  godzinowa bez zmian, MD ÷ 8); zamówienia i kontrakty zostają
                  w swojej jednostce. */}
              <td className={AMOUNT_CELL}>{amount(r.hourly_rate_candidate)}</td>
              <td className={AMOUNT_CELL}>{amount(r.hourly_rate_client)}</td>
              <td
                className={cn(
                  AMOUNT_CELL,
                  "font-medium",
                  r.monthly_margin != null &&
                    (r.monthly_margin < 0
                      ? "text-warning-muted-foreground"
                      : "text-success-muted-foreground"),
                )}
              >
                {amount(r.monthly_margin)}
              </td>
              {showEndDate ? (
                <td className="py-2 pr-4 tabular-nums whitespace-nowrap">
                  {r.end_date ? (
                    formatDate(r.end_date)
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </td>
              ) : null}
              {renderActions ? (
                <td className="py-2 text-right">
                  <div className="flex items-center justify-end gap-1">
                    {renderActions(r)}
                  </div>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
