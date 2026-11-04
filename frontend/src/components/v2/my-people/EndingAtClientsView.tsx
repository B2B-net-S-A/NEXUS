"use client";

/**
 * Zakładka „Kończą u klientów” w „Moich ludziach” Delivery Leada
 * (decyzja Artura 25.10.2026): kto z konsultantów u moich klientów zaraz
 * zostanie bez projektu — od najbliższego końca, z „Dodaj do rekrutacji”.
 */

import Link from "next/link";
import { CalendarClock, UserPlus } from "lucide-react";

import {
  ENDING_WINDOW_DAYS,
  PROLONGATION_LABELS,
  type EndingConsultant,
} from "@/lib/api/endingConsultants";
import { plural } from "@/lib/my-people-summary";
import { Button } from "@/components/ui/button";

type AddFn = (row: { candidate_id: number; full_name: string }) => void;

export function formatEndDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${String(d).padStart(2, "0")}.${String(m).padStart(2, "0")}`;
}

export function EndingAtClientsView({
  rows,
  onAdd,
}: {
  rows: readonly EndingConsultant[];
  onAdd: AddFn;
}) {
  if (!rows.length) {
    return (
      <p className="px-2 py-6 text-center text-sm text-muted-foreground">
        U Twoich klientów nikomu nie kończy się umowa w ciągu {ENDING_WINDOW_DAYS} dni.
      </p>
    );
  }
  // Serwer sortuje po dacie końca; nie przestawiamy, żeby kolejność była jedna.
  return (
    <div className="space-y-3">
      <p className="rounded-md bg-primary/5 px-3 py-2 text-xs text-foreground">
        {rows.length} {plural(rows.length, "osobie", "osobom", "osobom")} u Twoich klientów kończy
        się umowa w ciągu {ENDING_WINDOW_DAYS} dni bez potwierdzonego przedłużenia. Przepnij, zanim
        odejdą.
      </p>
      <ul className="space-y-0.5">
        {rows.map((r) => {
          const name = r.candidate_name ?? `Kandydat ${r.candidate_id}`;
          return (
            <li
              key={r.contract_id}
              className="flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-muted/60"
            >
              <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
              <div className="min-w-0 flex-1">
                <Link
                  href={`/candidates/${r.candidate_id}`}
                  className="truncate text-sm font-medium text-foreground hover:underline"
                >
                  {name}
                </Link>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {[
                    r.client_name,
                    `koniec umowy ${formatEndDay(r.end_date)}`,
                    r.prolongation_status ? PROLONGATION_LABELS[r.prolongation_status] : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Dodaj do rekrutacji: ${name}`}
                title="Dodaj do rekrutacji"
                onClick={() => onAdd({ candidate_id: r.candidate_id, full_name: name })}
              >
                <UserPlus className="h-4 w-4" aria-hidden />
              </Button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
