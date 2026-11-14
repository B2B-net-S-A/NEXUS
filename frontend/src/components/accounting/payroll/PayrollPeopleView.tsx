"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { Checkbox } from "@/components/ui/checkbox";
import { usePayrollPeople, type PayrollPersonRow, type PersonSubject } from "@/lib/api/payroll-lists";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "../AccountingShell";
import { PersonDataDialog } from "./PersonDataDialog";
import { plural } from "./payroll-model";

const KIND_LABEL: Record<string, string> = { uop: "Umowa o pracę", zlecenie: "Zlecenie", dzielo: "Dzieło" };

function subjectOf(row: PayrollPersonRow): PersonSubject | null {
  if (row.candidate_id != null) return { candidateId: row.candidate_id };
  if (row.user_id != null) return { userId: row.user_id };
  return null;
}

/** „Dane osób”: kto z UoP i zleceń ma komplet danych płacowych, a komu czego brakuje. */
export function PayrollPeopleView() {
  const people = usePayrollPeople();
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [open, setOpen] = useState<PayrollPersonRow | null>(null);

  if (people.isError) return <QueryStateNotice state="error" onRetry={() => people.refetch()} />;
  if (!people.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie osób…</p>;
  const rows = people.data;
  const missing = rows.filter((row) => row.missing.length > 0);
  const shown = onlyMissing ? missing : rows;
  const subject = open ? subjectOf(open) : null;

  return (
    <SectionCard
      title="Dane płacowe osób"
      aside={`${plural(rows.length, "osoba", "osoby", "osób")} · bez kompletu: ${missing.length}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 px-3.5 py-2 text-[12.5px] text-muted-foreground">
        <span>Zespół na UoP i zleceniu oraz kontraktorzy na zleceniu u klientów. Kliknij osobę, żeby uzupełnić dane.</span>
        <label className="inline-flex items-center gap-2 text-foreground">
          <Checkbox
            aria-label="Tylko z brakami"
            checked={onlyMissing}
            onCheckedChange={(value) => setOnlyMissing(value === true)}
          />
          Tylko z brakami
        </label>
      </div>
      {shown.length ? (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[720px] table-fixed text-sm">
            <thead>
              <tr className="border-b border-border/70">
                <th className={cn(CALM_HEAD, "sticky left-0 z-10 w-[30%] bg-card px-3.5 py-2 text-left")}>Osoba</th>
                <th className={cn(CALM_HEAD, "w-[16%] px-2 py-2 text-left")}>Forma</th>
                <th className={cn(CALM_HEAD, "w-[16%] px-2 py-2 text-left")}>PESEL</th>
                <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Braki</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr
                  key={row.subject}
                  onClick={() => setOpen(row)}
                  className={cn(CALM_ROW, "group cursor-pointer align-top last:border-0 hover:bg-accent/60")}
                >
                  <td className="sticky left-0 z-10 min-w-0 bg-card px-3.5 py-2 group-hover:bg-accent">
                    <button
                      type="button"
                      className="block max-w-full truncate text-left font-medium hover:text-primary hover:underline"
                      title={row.name}
                      onClick={(event) => {
                        event.stopPropagation();
                        setOpen(row);
                      }}
                    >
                      {row.name}
                    </button>
                    <span className={CALM_SUBLINE}>
                      {row.candidate_id != null ? "kontraktor u klienta" : "zespół"}
                      {row.own ? " · Twoje dane (tylko podgląd)" : ""}
                    </span>
                  </td>
                  <td className="px-2 py-2">{KIND_LABEL[row.kind] ?? row.kind}</td>
                  <td className="px-2 py-2 tabular-nums text-muted-foreground">{row.pesel_masked ?? "—"}</td>
                  <td className="min-w-0 px-3.5 py-2 text-[13px]">
                    {row.missing.length ? (
                      <span className="flex items-start gap-1.5">
                        <span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-warning" />
                        <span className="min-w-0 break-words">
                          {row.exists ? row.missing_labels.join(", ") : "brak danych płacowych"}
                        </span>
                      </span>
                    ) : (
                      <span className="text-success">komplet</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-3.5 py-6 text-center text-[13px] text-muted-foreground">
          {rows.length ? "Wszyscy mają komplet danych płacowych." : "Nie ma osób na UoP ani zleceniu."}
        </p>
      )}
      <PersonDataDialog
        subject={subject}
        kind={open?.kind}
        open={open != null}
        onOpenChange={(value) => {
          if (!value) setOpen(null);
        }}
      />
    </SectionCard>
  );
}
