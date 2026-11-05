"use client";

// Premia 200% w miesiącu programu (decyzje Artura 05.11.2026): kto zrobił cel.
// W trakcie miesiąca to postęp; po ostatnim dniu automat zapisuje decyzję
// i podwaja premie za placementy podpisane w miesiącu. Lustro
// `backend/app/services/hr/double_bonus.py`.

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDoubleBonusMonth,
  useSettleDoubleBonus,
  type DoubleBonusDl,
  type DoubleBonusMonth,
  type DoubleBonusRecruiter,
} from "@/lib/api/hr-payroll";
import { monthYearPl } from "@/lib/date-pl";

import { doubleBonusConditions, doubleBonusState } from "./double-bonus-format";

interface DoubleBonusCardProps {
  year: number;
  month: number;
  /** Miesiąc otwarty: po jego końcu Płace mogą przeliczyć decyzję. */
  open: boolean;
}

export function DoubleBonusCard({ year, month, open }: DoubleBonusCardProps) {
  const query = useDoubleBonusMonth(year, month);
  const settle = useSettleDoubleBonus(year, month);
  const { showToast } = useToast();
  const data = query.data;
  if (query.isError) {
    return (
      <Card className="p-4 text-sm text-muted-foreground">
        {apiErrorMessage(query.error, "Nie udało się wczytać premii 200%.")}
      </Card>
    );
  }
  if (!query.isSuccess || !data?.in_program) return null;
  const people = [...data.recruiters, ...data.dls].filter((row) => !row.excluded);

  const recompute = () =>
    settle.mutate(undefined, {
      onSuccess: (result) =>
        showToast(
          `Premia 200% przeliczona: ${result.stored?.recruiters.length ?? 0} rekruterów, ${result.stored?.dls.length ?? 0} DL`,
          "success",
        ),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przeliczyć premii 200%."), "error"),
    });

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-foreground">
            Premia 200% · {monthYearPl({ year, month })}
          </h2>
          <p className="text-xs text-muted-foreground">{headline(data)}</p>
        </div>
        {data.final && open ? (
          <Button size="sm" variant="outline" onClick={recompute} disabled={settle.isPending}>
            {settle.isPending ? "Przeliczanie…" : "Przelicz wynik"}
          </Button>
        ) : null}
      </div>
      {people.length === 0 ? (
        <p className="text-sm text-muted-foreground">W tym miesiącu nikt nie ma jeszcze placementu ani celu.</p>
      ) : (
        <ul className="divide-y divide-border">
          {people.map((row) => (
            <PersonLine key={`${row.kind}-${row.user_id}`} row={row} final={data.final} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function headline(data: DoubleBonusMonth): string {
  if (!data.final) {
    return "Postęp w trakcie miesiąca. Wynik i premie ×2 po ostatnim dniu miesiąca.";
  }
  if (!data.stored) return "Miesiąc się skończył, wynik policzy nocny przebieg automatu.";
  return `Wynik zapisany: ${data.stored.recruiters.length + data.stored.dls.length} os. z premią ×2 za placementy podpisane w tym miesiącu.`;
}

function PersonLine({ row, final }: { row: DoubleBonusRecruiter | DoubleBonusDl; final: boolean }) {
  const state = doubleBonusState(row, final);
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <div className="min-w-0">
        <span className="font-medium text-foreground">{row.name ?? `Osoba ${row.user_id}`}</span>
        <span className="text-muted-foreground"> · {row.kind === "dl" ? "Delivery Lead" : "rekruter"}</span>
        <div className="text-xs text-muted-foreground">{doubleBonusConditions(row)}</div>
      </div>
      <span
        className={
          state.tone === "success"
            ? "rounded-full bg-success-muted px-2 py-0.5 text-xs font-semibold text-success-muted-foreground"
            : "rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground"
        }
      >
        {state.label}
      </span>
    </li>
  );
}
