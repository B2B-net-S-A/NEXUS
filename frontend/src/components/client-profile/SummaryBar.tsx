"use client";

import { InlineStats, type InlineStat } from "@/components/ds/InlineStats";
import type { ClientProfileSummary } from "@/types/client-profile";
import { formatPLN } from "@/types/client-profile";

import { useClientProfile } from "./useClientProfile";

interface Props {
  summary: ClientProfileSummary;
  className?: string;
}

/**
 * Kafelek „Otwarte rekrutacje" zdjęty: był dosłownym duplikatem licznika przy
 * przełączniku „Aktywne projekty" w zakładce Projekty, tylko liczonym z innego
 * źródła (`summary.open_jobs` = wyłącznie `published`, tam `open_only` =
 * `draft` + `published`) — więc dwie liczby o tej samej nazwie mogły się
 * rozjeżdżać i nie było sposobu odgadnąć, która jest prawdziwa.
 *
 * Pole `summary.open_jobs` ZOSTAJE w typie i w API. Nie jest to zaszłość:
 * usunięcie go z payloadu to zmiana kontraktu, a testy backendu je asertują.
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
 * Dwie liczby klienta: aktywni konsultanci i aktywne MRR. JEDNO miejsce reguł
 * „Brak stawek” / „Brak kursu” / „(niepełne)” — czyta je nagłówek strony
 * klienta (widoczny na każdej zakładce).
 */
export function clientSummaryStats(summary: ClientProfileSummary): InlineStat[] {
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
  const consultantsSubtitle = `${summary.active_contracts} ${activeContractsWord(summary.active_contracts)}`;
  return [
    {
      id: "active-consultants",
      label: statLabel("Aktywni konsultanci", consultantsSubtitle),
      value: summary.active_consultants,
      title: consultantsSubtitle,
    },
    {
      id: "active-mrr",
      label: statLabel(
        mrrIncomplete ? "Aktywne MRR (niepełne)" : "Aktywne MRR",
        mrrSubtitle,
      ),
      value: mrrFxMissing
        ? "Brak kursu"
        : mrrUnpriced
          ? "Brak stawek"
          : formatPLN(summary.active_mrr),
      title: mrrSubtitle,
    },
  ];
}

/** Zwarte liczby klienta (dawniej dwa kafle nad tabelą konsultantów). */
export function SummaryBar({ summary, className }: Props) {
  return <InlineStats stats={clientSummaryStats(summary)} className={className} />;
}

/**
 * Liczby w nagłówku strony klienta. Dzieli zapytanie z zakładką „Profil”
 * (`useClientProfile`). W trakcie ładowania, przy odmowie i przy awarii nie
 * renderuje nic — nagłówek to skrót, komunikat o błędzie pokazuje zakładka.
 */
export function ClientHeaderStats({
  clientId,
  className,
}: {
  clientId: number;
  className?: string;
}) {
  const { data } = useClientProfile(clientId);
  if (!data?.summary) return null;
  return <SummaryBar summary={data.summary} className={className} />;
}
