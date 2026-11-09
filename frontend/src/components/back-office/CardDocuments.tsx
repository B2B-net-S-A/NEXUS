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
  type StaffDocument,
} from "@/lib/api/portal-staff";

import { ReasonDialog } from "./ReasonDialog";

const CHANNEL_LABELS: Record<StaffDocument["channel"], string> = {
  portal: "z portalu",
  mailbox: "z rozliczenia@",
};

function DocumentRow({ document_ }: { document_: StaffDocument }) {
  const { showToast } = useToast();
  const decide = useDocumentDecision();
  const [asking, setAsking] = useState(false);
  const [contractId, setContractId] = useState("");
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
        {document_.period_guessed ? " (okres zgadnięty z daty maila: sprawdź)" : ""}
        {document_.sender_email ? ` · ${document_.sender_email}` : ""}
      </p>
      {unmatched ? (
        <div className="flex gap-2">
          <Input
            aria-label="Numer kontraktu"
            inputMode="numeric"
            placeholder="Numer kontraktu"
            value={contractId}
            onChange={(event) => setContractId(event.target.value.replace(/\D/g, ""))}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={!contractId || decide.isPending}
            onClick={() => run("assign", { contract_id: Number(contractId) })}
          >
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
