"use client";

import {
  CreditCard,
  Headphones,
  Laptop,
  Monitor,
  Package,
  Smartphone,
  type LucideIcon,
} from "lucide-react";

import { useMyEquipment, type EquipmentCategory } from "@/lib/api/equipment";
import { formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

import { CATEGORY_LABELS, assignmentLabel } from "../../../equipment/equipment-format";
import { Loading, OverviewCard, PartError, stateOf } from "./OverviewCard";

const CATEGORY_ICON: Record<EquipmentCategory, LucideIcon> = {
  laptop: Laptop,
  telefon: Smartphone,
  monitor: Monitor,
  karta_sim: CreditCard,
  karta_dostepu: CreditCard,
  akcesorium: Headphones,
  inne: Package,
};

/**
 * „Mój sprzęt” w „Przeglądzie”: ikona rodzaju, model, numer i data wydania;
 * protokoły czekające na podpis jako jedno zdanie. Wyłączony moduł (404) albo
 * brak dostępu (403) chowa kartę — jak panel sprzętu w kartotece.
 */
export function EquipmentCard() {
  const query = useMyEquipment();
  const state = stateOf(query);
  if (state === "not_found" || state === "forbidden") return null;
  const data = query.data;
  const waiting = (data?.protocols ?? []).filter((p) => p.status === "oczekuje").length;
  return (
    <OverviewCard title="Mój sprzęt">
      {state === "loading" ? (
        <Loading />
      ) : state !== "ready" || !data ? (
        <PartError label="Nie udało się wczytać sprzętu." onRetry={() => query.refetch()} />
      ) : data.active.length === 0 ? (
        <p className="text-sm text-muted-foreground">Brak wydanego sprzętu w ewidencji.</p>
      ) : (
        <ul className="space-y-2">
          {data.active.map((row) => {
            const Icon = CATEGORY_ICON[row.category] ?? Package;
            return (
              <li key={row.assignment_id} className="flex items-center gap-2.5">
                <span
                  className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground"
                  title={CATEGORY_LABELS[row.category]}
                >
                  <Icon className="size-4" aria-hidden />
                </span>
                <div className="min-w-0 text-sm">
                  <p className="truncate font-medium text-foreground" title={assignmentLabel(row)}>
                    {assignmentLabel(row)}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    od {formatIsoDatePl(row.issued_at)}
                    {row.issue_protocol ? ` · ${row.issue_protocol}` : ""}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {waiting > 0 ? (
        <p className="rounded-md bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground">
          {countPl(waiting, "protokół czeka", "protokoły czekają", "protokołów czeka")} na Twój podpis
        </p>
      ) : null}
    </OverviewCard>
  );
}
