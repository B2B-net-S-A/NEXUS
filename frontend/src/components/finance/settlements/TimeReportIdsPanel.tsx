"use client";

// Kartoteka raportu klienta (plan Nordei N1.1): numery osób z faktur do klienta
// w KSeF, podpowiedzi po imieniu i nazwisku do zatwierdzenia, osoby z raportu
// bez numeru (ręczne przypisanie) i zakończone kontrakty z godzinami.
import { useState } from "react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useAddId, useDecideId, useFillIdsFromKsef, useTimeReportIds, type IdsContract } from "@/lib/api/client-time-reports";

import { hoursText } from "./time-report-format";

interface TimeReportIdsPanelProps {
  clientId: number;
  month: string;
  canWrite: boolean;
}

export function TimeReportIdsPanel({ clientId, month, canWrite }: TimeReportIdsPanelProps) {
  const query = useTimeReportIds(clientId, month);
  const fill = useFillIdsFromKsef();
  const decide = useDecideId();
  const { showSuccess, showError } = useToast();

  if (query.isError) {
    return <QueryStateNotice state="error" description={apiErrorMessage(query.error, "Nie udało się pobrać kartoteki.")} onRetry={() => query.refetch()} />;
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const data = query.data;

  async function runFill() {
    try {
      const r = await fill.mutateAsync(clientId);
      showSuccess(`Faktury z KSeF: ${r.invoices}, nowe pozycje kartoteki: ${r.added}, uzupełnione: ${r.updated}.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się uzupełnić kartoteki z KSeF."));
    }
  }

  async function runDecide(id: number, approve: boolean) {
    try {
      await decide.mutateAsync({ id, approve });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać decyzji."));
    }
  }

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border bg-card px-3 py-2 text-[13px]">
        <span>
          Osoby z numerem: <strong className="tabular-nums">{data.counts.confirmed}</strong>
        </span>
        <span>
          Do zatwierdzenia: <strong className="tabular-nums">{data.counts.suggested}</strong>
        </span>
        <span>
          Z raportu bez numeru: <strong className="tabular-nums">{data.counts.unmatched}</strong>
        </span>
        <span>
          Kontrakty bez numeru: <strong className="tabular-nums">{data.counts.without_number}</strong>
        </span>
        {canWrite ? (
          <Button size="sm" variant="outline" className="ml-auto" disabled={fill.isPending} onClick={() => void runFill()}>
            {fill.isPending ? "Uzupełniam…" : "Uzupełnij z faktur w KSeF"}
          </Button>
        ) : null}
      </div>

      <Section title="Do zatwierdzenia" empty="Nie ma podpowiedzi do zatwierdzenia." count={data.suggestions.length}>
        {data.suggestions.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[13px]">
            <span className="min-w-0 flex-1">
              <span className="font-medium">{s.name}</span>
              <span className="block text-[11px] text-muted-foreground">
                numer <span className="tabular-nums">{s.value}</span> · w raporcie „{s.report_name ?? "–"}” · kontrakt {s.contract_status ?? "–"}
              </span>
            </span>
            {canWrite ? (
              <span className="flex gap-1.5">
                <Button size="sm" disabled={decide.isPending} onClick={() => void runDecide(s.id, true)}>
                  Zatwierdź
                </Button>
                <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => void runDecide(s.id, false)}>
                  To nie ta osoba
                </Button>
              </span>
            ) : null}
          </li>
        ))}
      </Section>

      <Section title="Z raportu bez numeru w kartotece" empty="Każda osoba z ostatniej wersji raportu ma kontrakt." count={data.unmatched.length}>
        {data.unmatched.map((u) => (
          <UnmatchedRow key={u.person_no} clientId={clientId} canWrite={canWrite} contracts={data.without_number} item={u} />
        ))}
      </Section>

      <Section title="Zakończone kontrakty z godzinami w raporcie" empty="Brak." count={data.ended.length}>
        {data.ended.map((e) => (
          <li key={e.person_no} className="flex flex-wrap items-center gap-x-3 px-3 py-2 text-[13px]">
            <span className="min-w-0 flex-1 font-medium">{e.name}</span>
            <span className="tabular-nums text-muted-foreground">
              {e.person_no} · {hoursText(e.hours)} · koniec {e.end_date ?? "–"}
            </span>
          </li>
        ))}
      </Section>
    </div>
  );
}

function Section({ title, empty, count, children }: { title: string; empty: string; count: number; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border bg-card">
      <h3 className="flex items-center gap-2 border-b px-3 py-2 text-[13px] font-semibold">
        {title}
        <StatusDot tone={count ? "warning" : "success"}>{count}</StatusDot>
      </h3>
      {count ? <ul className="divide-y">{children}</ul> : <p className="px-3 py-3 text-xs text-muted-foreground">{empty}</p>}
    </section>
  );
}

function UnmatchedRow({
  clientId,
  canWrite,
  contracts,
  item,
}: {
  clientId: number;
  canWrite: boolean;
  contracts: IdsContract[];
  item: {
    person_no: string;
    report_name: string | null;
    hours: string;
    projects: string[];
  };
}) {
  const add = useAddId();
  const { showSuccess, showError } = useToast();
  const [contractId, setContractId] = useState("");

  async function assign() {
    try {
      await add.mutateAsync({
        client_id: clientId,
        contract_id: Number(contractId),
        kind: "client_person_no",
        value: item.person_no,
      });
      showSuccess(`Numer ${item.person_no} przypisany.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się przypisać numeru."));
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[13px]">
      <span className="min-w-0 flex-1">
        <span className="font-medium">{item.report_name ?? item.person_no}</span>
        <span className="block text-[11px] tabular-nums text-muted-foreground">
          {item.person_no} · {hoursText(item.hours)} · {item.projects.join(", ") || "bez NIDS"}
        </span>
      </span>
      {canWrite ? (
        <span className="flex flex-wrap items-center gap-1.5">
          <select
            aria-label={`Kontrakt dla ${item.person_no}`}
            value={contractId}
            onChange={(e) => setContractId(e.target.value)}
            className="h-8 max-w-64 rounded-md border border-border bg-background px-2 text-xs"
          >
            <option value="">Wybierz kontrakt…</option>
            {contracts.map((c) => (
              <option key={c.contract_id} value={c.contract_id}>
                {c.name} · {c.contract_status ?? "–"}
              </option>
            ))}
          </select>
          <Button size="sm" variant="outline" disabled={!contractId || add.isPending} onClick={() => void assign()}>
            Przypisz
          </Button>
        </span>
      ) : null}
    </li>
  );
}
