"use client";

import { useState } from "react";
import { Check, FileText } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadStaffDocument,
  useCardDocuments,
  useDocumentDecision,
  type SenderContract,
  type StaffDocument,
} from "@/lib/api/portal-staff";
import { monthYearPl, shiftMonth } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

import { ReasonDialog } from "./ReasonDialog";

const CHANNEL_LABELS: Record<StaffDocument["channel"], string> = {
  portal: "z portalu",
  mailbox: "z poczty rozliczeniowej",
};

/** Miesiące do wyboru przy „Przypisz”: dwa lata wstecz, najpóźniej bieżący (zakres
 *  serwera), oraz miesiąc, który dokument ma teraz, także spoza zakresu. */
function serviceMonths(current: string): string[] {
  const now = warsawToday().slice(0, 7);
  const months = Array.from({ length: 25 }, (_, back) => shiftMonth(now, -back));
  return months.includes(current) ? months : [current, ...months].sort().reverse();
}

/** „VeloBank · 469 · od 03.2025”; zakończony kontrakt także z miesiącem końca. */
function contractLabel(contract: SenderContract): string {
  const month = (iso: string) => `${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
  const period = [
    contract.start_date ? `od ${month(contract.start_date)}` : null,
    contract.end_date ? `do ${month(contract.end_date)}` : null,
  ]
    .filter(Boolean)
    .join(" ");
  return [contract.client ?? "Bez klienta", String(contract.id), period].filter(Boolean).join(" · ");
}

function DocumentRow({ document_ }: { document_: StaffDocument }) {
  const { showToast } = useToast();
  const decide = useDocumentDecision();
  const [asking, setAsking] = useState(false);
  const [contractId, setContractId] = useState("");
  const documentMonth = `${document_.period_year}-${String(document_.period_month).padStart(2, "0")}`;
  const [month, setMonth] = useState(documentMonth);
  const unmatched = document_.contract_id == null;
  const pending = document_.status === "received";

  const run = (action: "accept" | "reject" | "assign", body?: Record<string, unknown>) =>
    decide.mutate(
      { id: document_.id, action, body },
      {
        onSuccess: () => setAsking(false),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać decyzji."), "error"),
      },
    );

  const assign = () => {
    const [year, number] = month.split("-").map(Number);
    run("assign", {
      contract_id: Number(contractId),
      ...(month === documentMonth ? {} : { period_year: year, period_month: number }),
    });
  };

  return (
    <li className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="inline-flex min-w-0 items-center gap-1 text-primary underline-offset-2 hover:underline"
          onClick={() =>
            downloadStaffDocument(document_).catch((error) =>
              showToast(apiErrorMessage(error, "Nie udało się pobrać dokumentu."), "error"),
            )
          }
        >
          <FileText aria-hidden className="size-3.5 shrink-0" />
          <span className="truncate">{document_.file_name ?? `Dokument ${document_.id}`}</span>
        </button>
        <Badge variant="neutral" size="sm">
          {CHANNEL_LABELS[document_.channel]}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        Za {String(document_.period_month).padStart(2, "0")}.{document_.period_year}
        {document_.period_guessed ? " (okres nie z nazwy pliku: sprawdź)" : ""}
        {document_.sender_email ? ` · ${document_.sender_email}` : ""}
      </p>
      {unmatched ? (
        <div className="space-y-1">
          <label className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Miesiąc usługi</span>
            <select
              value={month}
              onChange={(event) => setMonth(event.target.value)}
              className="h-8 rounded-md border border-border bg-background px-2 text-sm pointer-coarse:h-10"
            >
              {serviceMonths(documentMonth).map((value) => (
                <option key={value} value={value}>
                  {monthYearPl(value)}
                </option>
              ))}
            </select>
          </label>
          <p className="text-xs text-muted-foreground">
            {document_.kind === "invoice"
              ? "Numer w nazwie faktury to często miesiąc wystawienia. Sprawdź w pliku, za który miesiąc jest."
              : "Rozliczenie policzy się za ten miesiąc. Sprawdź w pliku, za który miesiąc jest raport."}
          </p>
        </div>
      ) : null}
      {unmatched && document_.sender_person?.contracts.length ? (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">
            Nadawca{document_.sender_person.name ? `: ${document_.sender_person.name}` : ""} — kontrakty:
          </p>
          <div className="flex flex-wrap gap-2">
            {document_.sender_person.contracts.map((contract) => (
              <Button
                key={contract.id}
                size="sm"
                variant={String(contract.id) === contractId ? "primary" : "outline"}
                aria-pressed={String(contract.id) === contractId}
                onClick={() => setContractId(String(contract.id))}
              >
                {contractLabel(contract)}
              </Button>
            ))}
          </div>
        </div>
      ) : null}
      {unmatched ? (
        <div className="flex gap-2">
          <Input
            aria-label="Numer kontraktu"
            inputMode="numeric"
            placeholder="Numer kontraktu"
            value={contractId}
            onChange={(event) => setContractId(event.target.value.replace(/\D/g, ""))}
          />
          <Button size="sm" variant="outline" disabled={!contractId || decide.isPending} onClick={assign}>
            Przypisz
          </Button>
        </div>
      ) : null}
      {pending && !unmatched ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={decide.isPending} onClick={() => run("accept")}>
            <Check aria-hidden className="size-3.5" />
            {document_.kind === "report" ? "Akceptuj raport" : "Przyjmij fakturę"}
          </Button>
          <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => setAsking(true)}>
            Do poprawy
          </Button>
        </div>
      ) : null}
      {asking ? (
        <ReasonDialog
          title="Odesłać do poprawy?"
          label="Co trzeba poprawić (zobaczy to konsultant)"
          confirmLabel="Odeślij"
          busy={decide.isPending}
          onCancel={() => setAsking(false)}
          onConfirm={(reason) => run("reject", { reason })}
        />
      ) : null}
    </li>
  );
}

/** Dokumenty na karcie Finansów: raport i faktura z portalu albo z rozliczenia@. */
export function CardDocuments({ cardId }: { cardId: number }) {
  const documents = useCardDocuments(cardId);
  if (documents.isLoading) return <p className="text-sm text-muted-foreground">Wczytujemy dokumenty…</p>;
  if (documents.isError || !documents.data) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(documents.error, "Nie udało się wczytać dokumentów.")}
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {documents.data.items.map((row) => (
        <DocumentRow key={row.id} document_={row} />
      ))}
    </ul>
  );
}
