"use client";

import Link from "next/link";
import { CompetenceCategoryName } from "@/components/v2/CompetenceCategoryBadge";
import type { ExecutiveContractBrief } from "@/lib/api/executiveContracts";
import { projectPartLabel } from "@/lib/ezdrowie";
import { cn } from "@/lib/utils";
import type {
  ActiveConsultantItem,
  HistoricalPlacementItem,
} from "@/types/client-profile";
import { daysToEndBadgeColor, formatDate, formatPLN } from "@/types/client-profile";

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

export function ConsultantsTable({ rows, showEndDate, renderActions }: Props) {
  return (
    // `min-w` + przyklejona kolumna „Konsultant": na telefonie tabela
    // przewija się w bok zamiast ściskać nagłówki do trzech linii, a po
    // przewinięciu nadal widać, czyj to wiersz. Tło komórki = tło karty profilu.
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="sticky left-0 z-10 bg-card py-2 pr-4 font-medium dark:bg-muted">Konsultant</th>
            <th className="py-2 pr-4 font-medium">Start date</th>
            <th className="py-2 pr-4 font-medium">Stawka kosztowa [godz.]</th>
            <th className="py-2 pr-4 font-medium">Stawka przychodowa [godz.]</th>
            {/* Marża zostaje miesięczna — kafel „Aktywne MRR" jest jej sumą. */}
            <th className="py-2 pr-4 font-medium">Marża [mc]</th>
            {showEndDate ? (
              <th className="py-2 pr-4 font-medium">End date</th>
            ) : null}
            {renderActions ? (
              <th className="py-2 text-right font-medium">Akcje</th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.contract_id} className="border-b border-border">
              <td className="sticky left-0 z-10 bg-card py-3 pr-4 dark:bg-muted">
                <div className="flex items-start gap-3">
                  {r.candidate.avatar_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={r.candidate.avatar_url}
                      alt={r.candidate.name}
                      className="h-9 w-9 shrink-0 rounded-full object-cover"
                    />
                  ) : (
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-900/30">
                      <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                        {initialsOf(r.candidate.name)}
                      </span>
                    </div>
                  )}
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/candidates/${r.candidate.id}`}
                        className="truncate font-semibold text-foreground hover:text-purple-600"
                      >
                        {r.candidate.name}
                      </Link>
                      {/* e-Zdrowie: NUMER umowy wykonawczej, część w tooltipie.
                          Fallback na samą część = wiersz sprzed wdrożenia
                          struktury (do przeglądu w sekcji „Struktura umów") —
                          ukrycie go czytałoby się jak brak przypisania w ogóle. */}
                      {r.executive_contract ? (
                        <span
                          className="rounded bg-sky-50 px-1.5 py-0.5 text-xs font-medium text-sky-700 dark:bg-sky-900/30 dark:text-sky-300"
                          title={
                            projectPartLabel(r.executive_contract.project_part) ??
                            "Umowa wykonawcza"
                          }
                        >
                          {r.executive_contract.number}
                        </span>
                      ) : r.project_part ? (
                        <span
                          className="rounded bg-sky-50 px-1.5 py-0.5 text-xs font-medium text-sky-700 dark:bg-sky-900/30 dark:text-sky-300"
                          title="Bez umowy wykonawczej — do przypisania w sekcji „Struktura umów”"
                        >
                          {projectPartLabel(r.project_part)}
                        </span>
                      ) : null}
                      {r.days_to_end != null ? (
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 text-xs font-semibold",
                            daysToEndBadgeColor(r.days_to_end),
                          )}
                        >
                          {r.days_to_end < 0
                            ? "po terminie"
                            : `kończy się za ${r.days_to_end}d`}
                        </span>
                      ) : null}
                    </div>
                    {r.candidate.competence_category ? (
                      <p className="text-xs text-muted-foreground">
                        <CompetenceCategoryName slug={r.candidate.competence_category} />
                      </p>
                    ) : null}
                    {/* Rekrutacja pod nazwiskiem. Brak powiązania = PUSTY
                        wiersz (wymóg ticketu), nie „brak powiązanej
                        rekrutacji" — komunikat zastępczy w kolumnie danych
                        czyta się jak wartość, a nie jak jej brak. */}
                    <p
                      className="text-xs text-muted-foreground"
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
                            className="hover:text-purple-600"
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
              <td className="py-3 pr-4 tabular-nums whitespace-nowrap">
                {formatDate(r.start_date)}
              </td>
              {/* `formatPLN(null)` → „—". Kwoty MUSZĄ renderować się także jako
                  puste: backend zeruje je dla ról bez VIEW_FINANCE, a znikająca
                  komórka zostawiłaby trzy puste kolumny bez wyjaśnienia.
                  Stawki są GODZINOWE (backend przelicza z jednostki zamówienia:
                  godzinowa bez zmian, MD ÷ 8); zamówienia i kontrakty zostają
                  w swojej jednostce. */}
              <td className="py-3 pr-4 tabular-nums whitespace-nowrap">
                {formatPLN(r.hourly_rate_candidate)}
              </td>
              <td className="py-3 pr-4 tabular-nums whitespace-nowrap">
                {formatPLN(r.hourly_rate_client)}
              </td>
              <td
                className={cn(
                  "py-3 pr-4 font-medium tabular-nums whitespace-nowrap",
                  r.monthly_margin != null && "text-emerald-600 dark:text-emerald-400",
                )}
              >
                {formatPLN(r.monthly_margin)}
              </td>
              {showEndDate ? (
                <td className="py-3 pr-4 tabular-nums whitespace-nowrap">
                  {formatDate(r.end_date)}
                </td>
              ) : null}
              {renderActions ? (
                <td className="py-3 text-right">
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
