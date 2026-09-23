"use client";

// Kolejka „Aneks uzupełnienia danych do zrobienia” — umowy podpisane przed
// założeniem działalności (arkusz „Bez działalności” z Excela działu). Klik
// otwiera kreator aneksu „Uzupełnienie danych” z tą umową jako bazową;
// podpisanie aneksu zdejmuje umowę z kolejki (`business_data_annex_done_at`).

import { useQuery } from "@tanstack/react-query";
import { FilePen } from "lucide-react";

import { Button } from "@/components/ui/button";
import { b2bGeneratorApi, type B2BGeneratedContractRow } from "@/lib/api";

export const BUSINESS_DATA_ANNEX_QUEUE_KEY = [
  "b2b-generated",
  "business-data-annex-pending",
] as const;

export function useBusinessDataAnnexQueue(enabled: boolean) {
  return useQuery({
    queryKey: BUSINESS_DATA_ANNEX_QUEUE_KEY,
    queryFn: () =>
      b2bGeneratorApi.generated(100, { businessDataAnnexPending: true }),
    enabled,
    staleTime: 30_000,
  });
}

export function BusinessDataAnnexQueue({
  enabled,
  onStart,
}: {
  enabled: boolean;
  onStart: (row: B2BGeneratedContractRow) => void;
}) {
  const queue = useBusinessDataAnnexQueue(enabled);
  const rows = queue.data ?? [];
  // Awaria kolejki nie zasłania listy dokumentów — to podpowiedź, nie rejestr.
  if (!enabled || !queue.isSuccess || rows.length === 0) return null;
  return (
    <section
      aria-label="Aneks uzupełnienia danych do zrobienia"
      className="rounded-lg border border-warning/40 bg-warning/5 p-3"
    >
      <h3 className="text-sm font-semibold text-foreground">
        Aneks uzupełnienia danych do zrobienia ({rows.length})
      </h3>
      <p className="mb-2 text-xs text-muted-foreground">
        Umowy podpisane przed założeniem działalności — potrzebują aneksu
        z danymi firmy Partnera.
      </p>
      <ul className="divide-y divide-border">
        {rows.map((row) => (
          <li key={row.id} className="flex items-center justify-between gap-3 py-1.5">
            <span className="min-w-0 truncate text-sm">
              <span className="font-medium">{row.contract_number}</span>
              {" · "}
              {row.partner_name}
              {row.client_name ? (
                <span className="text-muted-foreground"> · {row.client_name}</span>
              ) : null}
            </span>
            <Button size="sm" variant="outline" onClick={() => onStart(row)}>
              <FilePen className="mr-1 h-4 w-4" aria-hidden="true" />
              Przygotuj aneks
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
