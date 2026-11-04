"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useMyEquipment, usePersonEquipment, type HolderEquipment } from "@/lib/api/equipment";
import { resolveViewState } from "@/lib/view-state";
import { formatIsoDatePl } from "@/lib/date-pl";

import {
  PROTOCOL_STATUS_LABELS,
  assignmentLabel,
} from "./equipment-format";

interface PersonEquipmentPanelProps {
  /** Kartoteka osoby (Kadry, recepcja) albo „mine” — własny sprzęt. */
  userId: number | "mine";
}

/**
 * Zakładka „Sprzęt” w kartotece osoby: co ma teraz i z jakiego protokołu.
 * Kadry widzą ją tylko do odczytu; każdy widzi własny sprzęt. Wyłączony
 * moduł (404) albo brak dostępu (403) chowa panel bez komunikatu awarii.
 */
export function PersonEquipmentPanel({ userId }: PersonEquipmentPanelProps) {
  const mine = useMyEquipment(userId === "mine");
  const person = usePersonEquipment(userId === "mine" ? 0 : userId, userId !== "mine");
  const query = userId === "mine" ? mine : person;
  const data: HolderEquipment | undefined = query.data;
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: (data?.active.length ?? 0) === 0,
  });

  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">Wczytywanie sprzętu…</p>;
  }
  if (state === "not_found" || state === "forbidden") return null;
  if (state === "error") {
    return <QueryStateNotice state="error" onRetry={() => query.refetch()} />;
  }
  const waiting = (data?.protocols ?? []).filter((p) => p.status !== "potwierdzony");

  return (
    <section aria-label="Sprzęt" className="space-y-2 text-sm">
      {/* W kartotece osoby panel stoi między sekcjami z nagłówkami; „Mój
          sprzęt” ma tytuł z karty, w której siedzi. */}
      {userId !== "mine" ? (
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Sprzęt
        </h2>
      ) : null}
      {state === "empty" ? (
        <p className="text-muted-foreground">Brak wydanego sprzętu w ewidencji.</p>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {data?.active.map((row) => (
            <li key={row.assignment_id} className="flex flex-wrap items-baseline gap-x-3 px-3 py-2">
              <span className="font-medium">{assignmentLabel(row)}</span>
              <span className="text-xs text-muted-foreground">
                od {formatIsoDatePl(row.issued_at)}
                {row.issue_protocol ? ` · ${row.issue_protocol}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
      {waiting.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          Protokoły w toku:{" "}
          {waiting.map((p) => `${p.number} (${PROTOCOL_STATUS_LABELS[p.status].toLowerCase()})`).join(", ")}
        </p>
      ) : null}
    </section>
  );
}
