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
export function SummaryBar({ summary }: Props) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <StatsCard
        title="Aktywni konsultanci"
        value={summary.active_consultants}
        subtitle={`${summary.active_contracts} aktywnych kontraktów`}
        color="green"
        icon={<Users className="w-4 h-4" />}
      />
      <StatsCard
        title="Aktywne MRR"
        value={formatPLN(summary.active_mrr)}
        subtitle="miesięczna marża"
        color="orange"
        icon={<DollarSign className="w-4 h-4" />}
      />
    </div>
  );
}
