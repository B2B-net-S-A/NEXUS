"use client";

import { Users, DollarSign } from "lucide-react";
import { StatsCard } from "@/components/StatsCard";
import type { ClientProfileSummary } from "@/types/client-profile";
import { formatPLN } from "@/types/client-profile";

interface Props {
  summary: ClientProfileSummary;
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
 * Odłożone do osobnego PR-a, żeby ten był czysto frontendowy i odwracalny
 * jednym revertem.
 *
 * Grid zwężony z 3 do 2 kolumn — inaczej po usunięciu kafla zostałaby dziura.
 */
export function activeContractsWord(n: number): string {
  if (n === 1) return "aktywny kontrakt";
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return "aktywne kontrakty";
  return "aktywnych kontraktów";
}

export function SummaryBar({ summary }: Props) {
  const unpriced = summary.active_mrr_unpriced_contracts ?? 0;
  // Kontrakty bez stawki nie wchodzą do sumy — kafel mówi wprost, że kwota jest
  // niepełna, zamiast podawać zaniżoną liczbę jako pewną.
  // Podpis kafla idzie do natywnego tooltipa (StatsCard), więc samo „niepełne”
  // musi być widoczne w tytule — inaczej zaniżona kwota czyta się jak pełna.
  const mrrIncomplete = unpriced > 0 && summary.active_mrr !== null;
  // `null` przy niewycenionych kontraktach to „brak stawek”, nie brak
  // uprawnień — redakcja zeruje licznik, więc oba stany się nie mylą (N3).
  const mrrUnpriced = unpriced > 0 && summary.active_mrr === null;
  const mrrSubtitle = mrrIncomplete
    ? `miesięczna marża — suma niepełna: pominięto ${unpriced} ${activeContractsWord(unpriced)} bez stawki`
    : mrrUnpriced
      ? `miesięczna marża — żaden z ${unpriced} ${activeContractsWord(unpriced)} nie ma stawki`
      : "miesięczna marża";
  return (
    <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
      <StatsCard
        title="Aktywni konsultanci"
        value={summary.active_consultants}
        subtitle={`${summary.active_contracts} ${activeContractsWord(summary.active_contracts)}`}
        color="green"
        icon={<Users className="w-4 h-4" />}
      />
      <StatsCard
        title={mrrIncomplete ? "Aktywne MRR (niepełne)" : "Aktywne MRR"}
        value={mrrUnpriced ? "Brak stawek" : formatPLN(summary.active_mrr)}
        subtitle={mrrSubtitle}
        color="orange"
        icon={<DollarSign className="w-4 h-4" />}
      />
    </div>
  );
}
