"use client";

// Wiersz „Umów bieżących”: etykieta najnowszego aneksu do umowy i data startu
// z aneksu (13.10.2026). Aneks zmienia firmę, NIP i datę rozpoczęcia w wierszu
// już przy wygenerowaniu — do tej pory po cichu, więc data z niepodpisanego
// aneksu wyglądała jak fakt. Etykieta prowadzi do rejestru aneksów.

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import type { B2BGeneratedContractRow } from "@/lib/api";
import {
  annexRegisterHref,
  annexShortLabel,
  annexStateLabel,
} from "@/lib/b2b-documents";
import { annexRatesSummary } from "@/lib/b2b-generator-register";
import { formatIsoDatePl } from "@/lib/date-pl";

type AnnexRow = Pick<
  B2BGeneratedContractRow,
  "contract_number" | "latest_annex" | "annex_count" | "annex_rates"
>;

function moreAnnexes(count: number): string {
  if (count === 1) return "+1 aneks";
  const lastTwo = count % 100;
  const last = count % 10;
  const few = last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14);
  return `+${count} ${few ? "aneksy" : "aneksów"}`;
}

/** „Aneks: data startu · czeka na podpis” + „+2 aneksy” pod nazwą Partnera. */
export function RegisterAnnexLabel({ row }: { row: AnnexRow }) {
  const annex = row.latest_annex;
  if (!annex) return null;
  const state = annexStateLabel(annex.state);
  // Kwotę niesie `annex_rates` pod własną bramką widoczności stawek.
  const rates =
    annex.document_type === "annex_rate_change"
      ? annexRatesSummary(row.annex_rates)
      : null;
  const others = (row.annex_count ?? 1) - 1;
  const href = annexRegisterHref(row.contract_number);
  return (
    <span className="flex flex-col gap-0.5">
      <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <Link href={href} className="rounded-full hover:opacity-80">
          <Badge
            variant={state.tone}
            className="h-auto max-w-56 whitespace-normal rounded-md text-left leading-snug"
          >
            Aneks: {annexShortLabel(annex.document_type)}
            {rates ? ` ${rates}` : ""} · {state.label.toLocaleLowerCase("pl")}
          </Badge>
        </Link>
        {others > 0 ? (
          <Link
            href={href}
            className="text-xs font-medium text-primary hover:underline"
          >
            {moreAnnexes(others)}
          </Link>
        ) : null}
      </span>
      {annex.effective_date ? (
        <span className="text-xs text-muted-foreground">
          od {formatIsoDatePl(annex.effective_date)}
        </span>
      ) : null}
    </span>
  );
}

/**
 * Data rozpoczęcia z aneksem zmiany daty startu: przed podpisem obie daty
 * („stara → nowa, po podpisie aneksu”), po podpisie stara przekreślona.
 */
export function RegisterStartDate({
  row,
}: {
  row: Pick<
    B2BGeneratedContractRow,
    "start_date" | "start_date_before" | "start_date_annex_state"
  >;
}) {
  const current = formatIsoDatePl(row.start_date);
  if (!row.start_date_before) return <>{current}</>;
  const before = formatIsoDatePl(row.start_date_before);
  if (row.start_date_annex_state === "waiting") {
    return (
      <span className="flex flex-col">
        <span>{before}</span>
        <span className="text-xs font-medium text-warning-muted-foreground">
          → {current}
        </span>
        <span className="text-xs text-muted-foreground">po podpisie aneksu</span>
      </span>
    );
  }
  return (
    <span className="flex flex-col">
      <span className="text-muted-foreground line-through">{before}</span>
      <span>{current}</span>
    </span>
  );
}
