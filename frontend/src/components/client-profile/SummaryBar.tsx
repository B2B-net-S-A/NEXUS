"use client";

import { InlineStats, type InlineStat } from "@/components/ds/InlineStats";
import type { ClientProfileSummary } from "@/types/client-profile";
import { formatPLN } from "@/types/client-profile";

import { useClientProfile } from "./useClientProfile";

interface Props {
  summary: ClientProfileSummary;
  className?: string;
  planned?: number;
  attention?: number;
}

/**
 * Liczby w nagłówku klienta (makieta 19.11.2026): nasi ludzie, otwarte
 * rekrutacje, marża miesięczna i sprawy z „Wymaga uwagi” Przeglądu.
 *
 * „Otwarte rekrutacje” wróciły 19.11.2026 (decyzja Artura, wariant A). Zdjęte
 * 02.10.2026 jako duplikat licznika „Aktywne projekty” w zakładce Projekty,
 * liczonego z innego źródła (tam szkice + opublikowane). Tu liczą się tylko
 * opublikowane (`summary.open_jobs`) — tak samo jak kolumna „Rekrutacje” na
 * liście klientów — i etykieta mówi „otwarte”, nie „aktywne projekty”.
 */
export function activeContractsWord(n: number): string {
  if (n === 1) return "aktywny kontrakt";
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return "aktywne kontrakty";
  return "aktywnych kontraktów";
}

/**
 * Podpis liczby: w dymku (`title`) przy myszy, a na dotyku — gdzie dymka nie
 * ma — drobnym drukiem pod etykietą. Bywa jedynym wyjaśnieniem liczby („suma
 * niepełna: pominięto N…”), więc czytnik ekranu dostaje go zawsze.
 */
function statLabel(label: string, subtitle: string) {
  return (
    <>
      {label}
      <span className="block pointer-fine:sr-only">{subtitle}</span>
    </>
  );
}

/**
 * Liczby klienta w nagłówku strony (widocznym na każdej zakładce). JEDNO
 * miejsce reguł „Brak stawek” / „Brak kursu” / „(niepełna)” marży.
 * `planned` = umowy ze startem w przyszłości, `attention` = sprawy
 * z „Wymaga uwagi” Przeglądu (0 = bez liczby).
 */
export function clientSummaryStats(
  summary: ClientProfileSummary,
  extra: { planned?: number; attention?: number } = {},
): InlineStat[] {
  const unpriced = summary.active_mrr_unpriced_contracts ?? 0;
  // Runda 10 (R10-N9-4): brak kursu NBP to inny stan niż brak stawek — kwoty
  // nie da się policzyć, choć kontrakty są wycenione.
  const fxMissing = summary.active_mrr_fx_missing_contracts ?? 0;
  const mrrFxMissing = fxMissing > 0 && summary.active_mrr === null;
  // Kontrakty bez stawki nie wchodzą do sumy — etykieta mówi wprost, że kwota
  // jest niepełna, zamiast podawać zaniżoną liczbę jako pewną.
  const mrrIncomplete = unpriced > 0 && summary.active_mrr !== null;
  // `null` przy niewycenionych kontraktach to „brak stawek”, nie brak
  // uprawnień — redakcja zeruje licznik, więc oba stany się nie mylą (N3).
  const mrrUnpriced = !mrrFxMissing && unpriced > 0 && summary.active_mrr === null;
  const mrrSubtitle = mrrFxMissing
    ? `miesięczna marża — brak kursu NBP dla ${fxMissing} ${activeContractsWord(fxMissing)}, kwoty nie da się policzyć`
    : mrrIncomplete
      ? `miesięczna marża — suma niepełna: pominięto ${unpriced} ${activeContractsWord(unpriced)} bez stawki`
      : mrrUnpriced
        ? `miesięczna marża — żaden z ${unpriced} ${activeContractsWord(unpriced)} nie ma stawki`
        : "miesięczna marża";
  const planned = extra.planned ?? 0;
  const consultantsSubtitle = `${summary.active_contracts} ${activeContractsWord(summary.active_contracts)}${
    planned > 0 ? `, +${planned} zaczyna` : ""
  }`;
  const attention = extra.attention ?? 0;
  return [
    {
      id: "active-consultants",
      label: statLabel("Nasi ludzie", consultantsSubtitle),
      value: summary.active_consultants,
      title: consultantsSubtitle,
    },
    {
      id: "open-jobs",
      label: statLabel("Otwarte rekrutacje", "opublikowane rekrutacje klienta, bez szkiców"),
      value: summary.open_jobs,
      title: "opublikowane rekrutacje klienta, bez szkiców",
    },
    {
      id: "active-mrr",
      label: statLabel(
        mrrIncomplete ? "Marża / mc (niepełna)" : "Marża / mc",
        mrrSubtitle,
      ),
      value: mrrFxMissing
        ? "Brak kursu"
        : mrrUnpriced
          ? "Brak stawek"
          : formatPLN(summary.active_mrr),
      title: mrrSubtitle,
    },
    ...(attention > 0
      ? [
          {
            id: "attention",
            label: statLabel("Wymaga uwagi", "sprawy z listy „Wymaga uwagi” w Przeglądzie"),
            value: attention,
            title: "sprawy z listy „Wymaga uwagi” w Przeglądzie",
          },
        ]
      : []),
  ];
}

/** Zwarte liczby klienta (dawniej dwa kafle nad tabelą konsultantów). */
export function SummaryBar({ summary, className, planned, attention }: Props) {
  return <InlineStats stats={clientSummaryStats(summary, { planned, attention })} className={className} />;
}

/**
 * Liczby w nagłówku strony klienta. Dzieli zapytanie z zakładką „Profil”
 * (`useClientProfile`). W trakcie ładowania, przy odmowie i przy awarii nie
 * renderuje nic — nagłówek to skrót, komunikat o błędzie pokazuje zakładka.
 */
export function ClientHeaderStats({
  clientId,
  className,
  attention = 0,
}: {
  clientId: number;
  className?: string;
  /** Liczba spraw z „Wymaga uwagi” Przeglądu (`useClientOverviewAttention`). */
  attention?: number;
}) {
  const { data } = useClientProfile(clientId);
  if (!data?.summary) return null;
  return (
    <SummaryBar
      summary={data.summary}
      className={className}
      planned={data.planned_consultants?.length ?? 0}
      attention={attention}
    />
  );
}
