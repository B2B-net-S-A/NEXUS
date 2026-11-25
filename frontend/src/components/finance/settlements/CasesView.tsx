"use client";

// Lista spraw w Rozliczeniach (25.11.2026): rozliczenia, których automat nie
// przyjmuje, z tym, kto działa, bieżącym krokiem i zaległością. Filtry: kto
// działa, klient, miesiąc (z zakładki), zaległe. Wiersz prowadzi do karty
// rozliczenia z sekcją „Co dalej”.
import { useMemo, useState } from "react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api-error";
import { useSettlementCases, type CaseActor, type SettlementCaseRow } from "@/lib/api/settlement-cases";
import { cn } from "@/lib/utils";

import { ACTOR_FILTERS, nowText } from "./case-format";
import { STATUS, monthLabel } from "./format";

interface CasesViewProps {
  month: string;
  onOpen: (row: SettlementCaseRow) => void;
}

export function CasesView({ month, onOpen }: CasesViewProps) {
  const query = useSettlementCases(month, null);
  const [actor, setActor] = useState<"all" | CaseActor>("all");
  const [clientId, setClientId] = useState<number | null>(null);
  const [overdueOnly, setOverdueOnly] = useState(false);

  const byClient = useMemo(
    () => (query.data?.cases ?? []).filter((row) => clientId == null || row.client_id === clientId),
    [query.data, clientId],
  );
  const rows = useMemo(
    () => byClient.filter((row) => (actor === "all" || row.actor === actor) && (!overdueOnly || row.overdue_days > 0)),
    [byClient, actor, overdueOnly],
  );

  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać spraw rozliczeń.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const data = query.data;
  const count = (key: "all" | CaseActor) => byClient.filter((row) => key === "all" || row.actor === key).length;
  const overdue = byClient.filter((row) => row.overdue_days > 0).length;

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-1">
        <select
          aria-label="Klient spraw"
          value={clientId ?? ""}
          onChange={(e) => setClientId(e.target.value ? Number(e.target.value) : null)}
          className="mr-1 h-8 w-52 rounded-md border border-border bg-background px-2 text-xs font-medium pointer-coarse:h-10"
        >
          <option value="">Wszyscy klienci · {data.counts.all}</option>
          {data.clients.map((c) => (
            <option key={c.client_id} value={c.client_id}>
              {c.name} · {c.count}
            </option>
          ))}
        </select>
        {ACTOR_FILTERS.map((filter) => (
          <button
            key={filter.key}
            type="button"
            aria-pressed={actor === filter.key}
            onClick={() => setActor(filter.key)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs font-medium pointer-coarse:min-h-10",
              actor === filter.key ? "border-primary bg-primary/10 text-foreground" : "border-border bg-card text-muted-foreground",
            )}
          >
            {filter.label} <span className="tabular-nums">{count(filter.key)}</span>
          </button>
        ))}
        <label
          data-tour="settlements.cases.overdue"
          className="ml-1 inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground pointer-coarse:min-h-10"
        >
          <input type="checkbox" checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} className="size-3.5 accent-primary" />
          Tylko zaległe <span className="tabular-nums">{overdue}</span>
        </label>
      </div>
      {data.cases.length === 0 ? (
        <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
          Za {monthLabel(month)} nie ma spraw: każde rozliczenie jest bez uwag albo przyjęte.
        </p>
      ) : (
        <CasesTable rows={rows} onOpen={onOpen} />
      )}
    </div>
  );
}

function CasesTable({ rows, onOpen }: { rows: SettlementCaseRow[]; onOpen: (row: SettlementCaseRow) => void }) {
  return (
    <div className="overflow-x-auto rounded-xl border bg-card">
      <table className="w-full min-w-[980px] table-fixed text-[13px]">
        <colgroup>
          <col className="w-[17%]" />
          <col className="w-[12%]" />
          <col className="w-[12%]" />
          <col className="w-[25%]" />
          <col className="w-[20%]" />
          <col className="w-[14%]" />
        </colgroup>
        <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
          <tr>
            <th className="sticky left-0 bg-card px-3 py-1.5 font-medium">Osoba</th>
            <th className="px-2 py-1.5 font-medium">Klient</th>
            <th className="px-2 py-1.5 font-medium">Kto działa</th>
            <th className="px-2 py-1.5 font-medium">Powód</th>
            <th className="px-2 py-1.5 font-medium">Teraz</th>
            <th className="px-3 py-1.5 font-medium">Do kogo</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                Nic w tym filtrze.
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={row.key} className="hover:bg-muted/30">
                <td className="sticky left-0 truncate bg-card px-3 py-1.5">
                  <button
                    type="button"
                    onClick={() => onOpen(row)}
                    className="block max-w-full truncate text-left font-medium hover:underline"
                  >
                    {row.person}
                  </button>
                  <span className="block truncate text-[11px] text-muted-foreground">{STATUS[row.status]?.label ?? row.status}</span>
                </td>
                <td className="truncate px-2 py-1.5">{row.client_name}</td>
                <td className="px-2 py-1.5">{row.actor_label}</td>
                <td className="px-2 py-1.5">
                  <span className="line-clamp-2">
                    {row.reasons[0]?.title}
                    {row.reasons.length > 1 ? <span className="text-muted-foreground"> +{row.reasons.length - 1}</span> : null}
                  </span>
                </td>
                <td className="px-2 py-1.5">
                  <StatusDot
                    tone={
                      row.current?.state === "overdue"
                        ? "danger"
                        : row.current?.state === "today"
                          ? "warning"
                          : row.current
                            ? "info"
                            : "success"
                    }
                  >
                    <span className="whitespace-normal">{nowText(row.current, row.overdue_days)}</span>
                  </StatusDot>
                </td>
                <td className="truncate px-3 py-1.5">
                  {row.recipient && row.recipient.kind !== "none" ? (
                    <>
                      <span className="block truncate">{row.recipient.name ?? row.recipient.label}</span>
                      {row.recipient.name ? (
                        <span className="block truncate text-[11px] text-muted-foreground">{row.recipient.label}</span>
                      ) : null}
                    </>
                  ) : row.actor === "finance" ? (
                    <span className="text-muted-foreground">na karcie</span>
                  ) : (
                    <span className="font-medium text-warning-muted-foreground">brak adresata</span>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
