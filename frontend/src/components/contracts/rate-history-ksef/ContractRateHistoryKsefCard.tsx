"use client";

// Historia stawek z faktur KSeF (0781, decyzje Artura 25.11.2026).
// Nad zakładkami kontraktu: karta „Faktury pokazują inną stawkę” do decyzji
// albo pasek „NEXUS uzupełnił historię stawek… · Cofnij” po wpisie automatycznym.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Receipt, Sparkles, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  decideContractRateHistoryKsef,
  fetchContractRateHistoryKsef,
  type RateHistoryAction,
  type RateHistoryItem,
  type RateHistoryStep,
} from "@/lib/api/contractRateHistoryKsef";
import { cn } from "@/lib/utils";
import { dayPl, monthPl, ratePl } from "../rate-documents/format";

interface Props {
  contractId: number;
  /** Edycja kontraktu — „Odrzuć”. „Wprowadź” i „Cofnij” rozstrzyga serwer (`can_apply`). */
  canDismiss: boolean;
}

const LEG: Record<string, string> = { client: "Klient", cost: "Koszt" };

const HEADLINE: Record<string, string> = {
  brak_historii:
    "Faktury KSeF pokazują wcześniejsze stawki — kontrakt ma tylko bieżącą",
  rozjazd_biezacy: "Faktury KSeF pokazują inną bieżącą stawkę niż kontrakt",
  rozjazd_w_przeszlosci:
    "Faktury KSeF pokazują inną stawkę w części miesięcy niż kontrakt",
};

function monthsLabel(months: string[]): string {
  if (!months.length) return "—";
  const first = monthPl(`${months[0]}-01`);
  const last = monthPl(`${months[months.length - 1]}-01`);
  return first === last ? first : `${first}–${last}`;
}

function zl(value: number | undefined): string {
  if (value === undefined) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toLocaleString("pl-PL", { maximumFractionDigits: 0 })} zł`;
}

function realSteps(item: RateHistoryItem): RateHistoryStep[] {
  return item.steps.filter((s) => !s.baseline);
}

function StepsTable({ item }: { item: RateHistoryItem }) {
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground">
          <th className="py-1 pr-3 font-medium">Stawka</th>
          <th className="py-1 pr-3 font-medium">Od</th>
          <th className="py-1 pr-3 font-medium">Miesiące z faktur</th>
          <th className="py-1 pr-3 font-medium">W kontrakcie</th>
          <th className="py-1 pr-3 font-medium">Z faktur</th>
          <th className="py-1 font-medium">Skutek</th>
        </tr>
      </thead>
      <tbody>
        {realSteps(item).map((step) => (
          <tr
            key={`${step.leg}-${step.from}`}
            className="border-t border-border/60"
          >
            <td className="py-1.5 pr-3">{LEG[step.leg] ?? step.leg}</td>
            <td className="py-1.5 pr-3 tabular-nums">{dayPl(step.from)}</td>
            <td className="py-1.5 pr-3 tabular-nums">
              {monthsLabel(step.months)}
            </td>
            <td className="py-1.5 pr-3 tabular-nums text-muted-foreground">
              {ratePl(step.nexus_rate)}
            </td>
            <td className="py-1.5 pr-3 font-semibold tabular-nums">
              {ratePl(step.rate)}
            </td>
            <td className="py-1.5 tabular-nums text-muted-foreground">
              {step.rate !== undefined && step.rate === step.nexus_rate
                ? "zamyka krok wyżej"
                : zl(step.impact)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Evidence({ item }: { item: RateHistoryItem }) {
  const numbers = Array.from(
    new Set(realSteps(item).flatMap((s) => s.evidence)),
  );
  if (!numbers.length) return null;
  return (
    <p className="flex flex-wrap items-start gap-1.5 text-[12px] text-muted-foreground">
      <Receipt className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>
        Faktury: {numbers.slice(0, 6).join(", ")}
        {numbers.length > 6 ? ` i ${numbers.length - 6} innych` : ""}
      </span>
    </p>
  );
}

function firstChange(item: RateHistoryItem): string {
  const steps = realSteps(item);
  return steps.length ? monthPl(steps[0].from) : "—";
}

export function ContractRateHistoryKsefCard({ contractId, canDismiss }: Props) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useQuery({
    queryKey: ["contract-rate-history-ksef", contractId],
    queryFn: () => fetchContractRateHistoryKsef(contractId),
    staleTime: 60_000,
  });
  const decide = useMutation({
    mutationFn: (action: RateHistoryAction) =>
      decideContractRateHistoryKsef(contractId, action),
    onSuccess: (_data, action) => {
      for (const key of [
        ["contract-rate-history-ksef", contractId],
        ["contract", contractId],
        ["contract-rate-history", contractId],
        ["contract-activities", contractId],
        ["contracts-v2"],
      ]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
      showSuccess(
        action === "apply"
          ? "Stawki z faktur wpisane do harmonogramu."
          : action === "undo"
            ? "Cofnięto wpis — podpowiedź wróciła na kartę."
            : "Odrzucono podpowiedź stawek z faktur.",
      );
    },
    onError: (error) =>
      showError(
        apiErrorMessage(error, "Nie udało się zapisać decyzji o stawkach z faktur."),
      ),
  });

  if (query.isError) {
    return (
      <p role="status" className="text-[12px] text-muted-foreground">
        Nie udało się sprawdzić stawek z faktur KSeF — odśwież stronę.
      </p>
    );
  }
  if (!query.isSuccess || !query.data.item) return null;
  const item = query.data.item;
  const amounts = query.data.amounts_visible;
  const canApply = query.data.can_apply;

  const run = async (action: RateHistoryAction) => {
    if (action === "apply" && item.reasons.length) {
      const ok = await askConfirm({
        title: "Wpisać stawki z faktur mimo uwag?",
        description: item.reasons.join(" "),
        confirmLabel: "Wpisz do harmonogramu",
      });
      if (!ok) return;
    }
    if (action === "undo") {
      const ok = await askConfirm({
        title: "Cofnąć historię stawek wpisaną przez NEXUS?",
        description:
          "Kroki z faktur znikną z harmonogramu kontraktu, a podpowiedź wróci na kartę. Dzisiejsza stawka się nie zmienia.",
        confirmLabel: "Cofnij wpis",
        variant: "destructive",
      });
      if (!ok) return;
    }
    decide.mutate(action);
  };

  if (item.status === "auto_applied") {
    return (
      <section
        aria-label="Historia stawek wpisana z faktur"
        className="rounded-lg border border-success/30 bg-success-muted/60 px-4 py-3"
      >
        {confirmDialog}
        <div className="flex flex-wrap items-center gap-2">
          <Sparkles
            className="h-4 w-4 text-success-muted-foreground"
            aria-hidden="true"
          />
          <p className="text-sm text-success-muted-foreground">
            <span className="font-semibold">
              NEXUS uzupełnił historię stawek z faktur KSeF:
            </span>{" "}
            {amounts
              ? realSteps(item)
                  .map(
                    (s) =>
                      `${LEG[s.leg].toLowerCase()} ${ratePl(s.rate)} od ${dayPl(s.from)}`,
                  )
                  .join(", ")
              : `zmiana od ${firstChange(item)}`}
          </p>
          {canApply ? (
            <Button
              size="sm"
              variant="outline"
              className="ml-auto gap-1"
              disabled={decide.isPending}
              onClick={() => run("undo")}
            >
              <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
              Cofnij
            </Button>
          ) : null}
        </div>
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          Dzisiejsza stawka bez zmian. „Cofnij” działa do{" "}
          {dayPl(item.undo_until)}. Wpis jest na osi czasu kontraktu.
        </p>
      </section>
    );
  }

  const review = item.reasons.length > 0;
  return (
    <section
      aria-label="Faktury KSeF pokazują inną stawkę"
      className={cn(
        "rounded-lg border bg-card",
        review ? "border-border" : "border-warning/40",
      )}
    >
      {confirmDialog}
      <header className="flex flex-wrap items-center gap-2 border-b border-border/60 bg-warning-muted/60 px-4 py-2">
        <AlertTriangle
          className="h-4 w-4 text-warning-muted-foreground"
          aria-hidden="true"
        />
        <h2 className="text-sm font-semibold text-warning-muted-foreground">
          {HEADLINE[item.category] ?? "Faktury KSeF pokazują inną stawkę"}
          {review ? " — do sprawdzenia" : ""}
        </h2>
        {item.status === "undone" ? (
          <span className="ml-auto text-[11px] text-muted-foreground">
            wpis automatyczny cofnięty
          </span>
        ) : null}
      </header>
      <div className="space-y-2 px-4 py-3">
        {amounts ? (
          <StepsTable item={item} />
        ) : (
          <p className="text-[13px] text-muted-foreground">
            Faktury pokazują inną stawkę od {firstChange(item)}. Kwoty widzi
            osoba z podglądem stawek kontraktu.
          </p>
        )}
        <Evidence item={item} />
        {review ? (
          <ul className="list-disc space-y-0.5 pl-5 text-[12px] text-muted-foreground">
            {item.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
        <div className="flex flex-wrap gap-2 pt-1">
          {canApply && amounts ? (
            <Button
              size="sm"
              disabled={decide.isPending}
              onClick={() => run("apply")}
            >
              Wprowadź do harmonogramu
            </Button>
          ) : null}
          {canDismiss ? (
            <Button
              size="sm"
              variant="quiet"
              disabled={decide.isPending}
              onClick={() => run("dismiss")}
            >
              Odrzuć
            </Button>
          ) : null}
        </div>
        {canApply && amounts ? (
          <p className="text-[11px] text-muted-foreground">
            „Wprowadź” dopisuje kroki do harmonogramu stawek kontraktu (bez
            aneksu) i wpis na osi czasu. Faktury za te miesiące są już
            wystawione, zamówienia się nie zmieniają.
          </p>
        ) : null}
      </div>
    </section>
  );
}
