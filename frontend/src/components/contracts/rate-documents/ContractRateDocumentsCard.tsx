"use client";

// Stawka z umów i aneksów kontraktu (0739, decyzja Artura 18.11.2026 — wariant B).
// Nad zakładkami kontraktu: karta „Dokument zmienia stawkę” do zatwierdzenia
// albo pasek „NEXUS wpisał stawkę… · Cofnij” po wpisie automatycznym.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileText, Sparkles, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { openAuthenticatedFile } from "@/lib/authenticated-files";
import {
  decideContractRateDocument,
  fetchContractRateDocuments,
  type RateDocumentAction,
  type RateDocumentItem,
} from "@/lib/api/contractRateDocuments";
import { cn } from "@/lib/utils";
import { dayPl, monthPl, ratePl } from "./format";

interface Props {
  contractId: number;
  /** Edycja kontraktu — „To nie stawka Partnera”. „Wprowadź” i „Cofnij” rozstrzyga serwer (`can_apply`). */
  canDismiss: boolean;
}

const KIND: Record<string, string> = { annex: "Aneks", contract: "Umowa" };

function kindLabel(item: RateDocumentItem): string {
  return KIND[item.kind ?? ""] ?? "Dokument";
}

function FileLine({
  item,
  onOpen,
}: {
  item: RateDocumentItem;
  onOpen: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted-foreground">
      <FileText className="h-3.5 w-3.5" aria-hidden="true" />
      <button
        type="button"
        onClick={onOpen}
        className="font-medium text-foreground underline-offset-2 hover:text-primary hover:underline"
      >
        {item.filename ?? "plik"}
      </button>
      {item.document_date ? (
        <>
          <span aria-hidden="true">·</span>
          <span>
            {kindLabel(item)} z {dayPl(item.document_date)}
          </span>
        </>
      ) : null}
    </div>
  );
}

function StepsTable({ item }: { item: RateDocumentItem }) {
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground">
          <th className="py-1 pr-3 font-medium">Okres</th>
          <th className="py-1 pr-3 font-medium">W kontrakcie</th>
          <th className="py-1 font-medium">W dokumencie</th>
        </tr>
      </thead>
      <tbody>
        {item.steps.map((step, index) => (
          <tr
            key={`${step.from}-${index}`}
            className="border-t border-border/60"
          >
            <td className="py-1.5 pr-3 tabular-nums">
              {step.from
                ? `od ${dayPl(step.from)}`
                : (step.condition ?? "bez daty")}
              {step.to ? ` do ${dayPl(step.to)}` : ""}
            </td>
            <td className="py-1.5 pr-3 tabular-nums text-muted-foreground">
              {ratePl(step.nexus_rate)}
            </td>
            <td className="py-1.5 font-semibold tabular-nums">
              {ratePl(step.rate)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Quote({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <blockquote className="rounded-md border-l-2 border-primary/40 bg-muted/50 px-3 py-2 text-[12px] leading-relaxed text-muted-foreground">
      „{text}”
    </blockquote>
  );
}

function firstChange(item: RateDocumentItem): string {
  const dated = item.steps.filter((s) => s.from);
  return dated.length ? monthPl(dated[0].from) : "—";
}

export function ContractRateDocumentsCard({ contractId, canDismiss }: Props) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [quoteOpen, setQuoteOpen] = useState<number | null>(null);
  const query = useQuery({
    queryKey: ["contract-rate-documents", contractId],
    queryFn: () => fetchContractRateDocuments(contractId),
    staleTime: 60_000,
  });
  const decide = useMutation({
    mutationFn: ({
      readId,
      action,
    }: {
      readId: number;
      action: RateDocumentAction;
    }) => decideContractRateDocument(contractId, readId, action),
    onSuccess: (_data, { action }) => {
      for (const key of [
        ["contract-rate-documents", contractId],
        ["contract", contractId],
        ["contract-rate-history", contractId],
        ["contract-activities", contractId],
        ["contracts-v2"],
      ]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
      showSuccess(
        action === "apply"
          ? "Stawka z dokumentu wpisana do harmonogramu."
          : action === "undo"
            ? "Cofnięto wpis — różnica wróciła na kartę."
            : "Oznaczono: to nie stawka Partnera.",
      );
    },
    onError: (error) =>
      showError(
        apiErrorMessage(error, "Nie udało się zapisać decyzji o stawce."),
      ),
  });

  if (query.isError) {
    return (
      <p role="status" className="text-[12px] text-muted-foreground">
        Nie udało się sprawdzić stawek z umów i aneksów — odśwież stronę.
      </p>
    );
  }
  if (!query.isSuccess || query.data.items.length === 0) return null;
  const amounts = query.data.amounts_visible;
  const canApply = query.data.can_apply;

  const openFile = (item: RateDocumentItem) =>
    openAuthenticatedFile(
      `/api/contracts/${contractId}/documents/${item.document_id}/download`,
      null,
      item.filename ?? "dokument",
    ).catch((error) =>
      showError(apiErrorMessage(error, "Nie udało się otworzyć pliku.")),
    );

  const run = async (item: RateDocumentItem, action: RateDocumentAction) => {
    if (action === "apply" && item.category === "review") {
      const ok = await askConfirm({
        title: "Wpisać stawkę z dokumentu mimo uwag?",
        description: item.reasons.join(" "),
        confirmLabel: "Wpisz do harmonogramu",
      });
      if (!ok) return;
    }
    if (action === "undo") {
      const ok = await askConfirm({
        title: "Cofnąć stawkę wpisaną przez NEXUS?",
        description:
          "Kroki z tego dokumentu znikną z harmonogramu, a koszt trwających zamówień wróci do poprzedniej stawki. Różnica wróci na kartę.",
        confirmLabel: "Cofnij wpis",
        variant: "destructive",
      });
      if (!ok) return;
    }
    decide.mutate({ readId: item.id, action });
  };

  return (
    <div className="space-y-3">
      {confirmDialog}
      {query.data.items.map((item) =>
        item.decision === "auto_applied" ? (
          <section
            key={item.id}
            aria-label="Stawka wpisana z dokumentu"
            className="rounded-lg border border-success/30 bg-success-muted/60 px-4 py-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Sparkles
                className="h-4 w-4 text-success-muted-foreground"
                aria-hidden="true"
              />
              <p className="text-sm text-success-muted-foreground">
                <span className="font-semibold">
                  NEXUS wpisał stawkę z dokumentu:
                </span>{" "}
                {amounts
                  ? item.steps
                      .map(
                        (s) =>
                          `${ratePl(s.nexus_rate)} → ${ratePl(s.rate)} od ${dayPl(s.from)}`,
                      )
                      .join(", ")
                  : `zmiana od ${firstChange(item)}`}
              </p>
              <span className="text-[11px] text-muted-foreground">
                {item.decided_at ? dayPl(item.decided_at) : ""} ·{" "}
                {item.filename}
              </span>
              <div className="ml-auto flex gap-2">
                {amounts && item.quote ? (
                  <Button
                    size="sm"
                    variant="outline"
                    aria-expanded={quoteOpen === item.id}
                    onClick={() =>
                      setQuoteOpen(quoteOpen === item.id ? null : item.id)
                    }
                  >
                    {quoteOpen === item.id ? "Ukryj cytat" : "Pokaż cytat"}
                  </Button>
                ) : null}
                {canApply ? (
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1"
                    disabled={decide.isPending}
                    onClick={() => run(item, "undo")}
                  >
                    <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                    Cofnij
                  </Button>
                ) : null}
              </div>
            </div>
            {quoteOpen === item.id ? (
              <div className="mt-2">
                <Quote text={item.quote} />
              </div>
            ) : null}
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              „Cofnij” działa do {dayPl(item.undo_until)}. Wpis jest na osi
              czasu kontraktu.
            </p>
          </section>
        ) : (
          <section
            key={item.id}
            aria-label="Dokument zmienia stawkę Partnera"
            className={cn(
              "rounded-lg border bg-card",
              item.category === "review"
                ? "border-border"
                : "border-warning/40",
            )}
          >
            <header className="flex flex-wrap items-center gap-2 border-b border-border/60 bg-warning-muted/60 px-4 py-2">
              <AlertTriangle
                className="h-4 w-4 text-warning-muted-foreground"
                aria-hidden="true"
              />
              <h2 className="text-sm font-semibold text-warning-muted-foreground">
                {item.category === "review"
                  ? `${kindLabel(item)} podaje inną stawkę niż kontrakt — do sprawdzenia`
                  : `${kindLabel(item)} zmienia stawkę Partnera od ${firstChange(item)} — w kontrakcie jej nie ma`}
              </h2>
              {item.read_at ? (
                <span className="ml-auto text-[11px] text-muted-foreground">
                  odczyt AI {dayPl(item.read_at)}
                </span>
              ) : null}
            </header>
            <div className="grid gap-4 px-4 py-3 lg:grid-cols-2">
              <div className="min-w-0 space-y-2">
                <FileLine item={item} onOpen={() => openFile(item)} />
                {amounts ? (
                  <StepsTable item={item} />
                ) : (
                  <p className="text-[13px] text-muted-foreground">
                    Kwoty widzi osoba z podglądem stawek kontraktu.
                  </p>
                )}
                {item.reasons.length ? (
                  <ul className="list-disc space-y-0.5 pl-5 text-[12px] text-muted-foreground">
                    {item.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <div className="min-w-0 space-y-2">
                {amounts ? <Quote text={item.quote} /> : null}
                <div className="flex flex-wrap gap-2 pt-1">
                  {canApply &&
                  amounts &&
                  item.steps.some((s) => s.from && !s.condition) ? (
                    <Button
                      size="sm"
                      disabled={decide.isPending}
                      onClick={() => run(item, "apply")}
                    >
                      Wprowadź do harmonogramu
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => openFile(item)}
                  >
                    Otwórz plik
                  </Button>
                  {canDismiss ? (
                    <Button
                      size="sm"
                      variant="quiet"
                      disabled={decide.isPending}
                      onClick={() => run(item, "dismiss")}
                    >
                      To nie stawka Partnera
                    </Button>
                  ) : null}
                </div>
                {canApply && amounts ? (
                  <p className="text-[11px] text-muted-foreground">
                    „Wprowadź” zapisuje aneks „Zmiana stawki” z datą i tym
                    plikiem, jak ręcznie: harmonogram, zamówienia, oś czasu.
                  </p>
                ) : null}
              </div>
            </div>
          </section>
        ),
      )}
    </div>
  );
}
