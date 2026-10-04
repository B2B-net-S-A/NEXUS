"use client";

/**
 * Sekcja „Umowa” w panelu osoby (PR 6 ścieżki kandydata, 04.10.2026).
 *
 * Na „Umowie” i „Zatrudnionym” panel pokazuje trzy kroki do końca procesu:
 * umowa wygenerowana → podpisana obustronnie → zamówienie od klienta. Do tej
 * pory rekruter i DL widzieli to wyłącznie w szerokim warsztacie „Umowa”
 * albo w rejestrze Generatora. Podpis nadal potwierdza się w rejestrze
 * („Oznacz jako podpisaną” zakłada kontrakt i zamówienie) — panel prowadzi
 * tam z wyszukaną umową, nie powiela okna potwierdzenia.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2 } from "lucide-react";

import { b2bGeneratorApi, type B2BGeneratedContractRow } from "@/lib/api";
import { generatorPrefillHref, registerSearchHref } from "@/lib/b2b-generator-register";
import { cn } from "@/lib/utils";

/** Kody etapów kolumn „Umowa” i „Zatrudniony” (lustro `board-stages`). */
export const CONTRACT_PANEL_STAGES: ReadonlySet<string> = new Set([
  "acceptance",
  "negotiation",
  "hired",
  "onboarding",
]);

type StepState = "done" | "todo" | "loading";

function Step({
  state,
  title,
  detail,
  action,
}: {
  state: StepState;
  title: string;
  detail?: string | null;
  action?: React.ReactNode;
}) {
  return (
    <li className="flex items-start gap-2">
      {state === "loading" ? (
        <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden />
      ) : state === "done" ? (
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
      ) : (
        <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <span className={cn("text-foreground", state === "done" && "text-muted-foreground")}>
          {title}
          <span className="sr-only">{state === "done" ? " — zrobione" : " — do zrobienia"}</span>
        </span>
        {detail ? <span className="block text-[11px] text-muted-foreground">{detail}</span> : null}
        {action ? <div className="mt-1">{action}</div> : null}
      </div>
    </li>
  );
}

export function DockContractSteps({
  candidateId,
  jobId,
  clientId,
  orderStatus,
  readOnly,
}: {
  candidateId: number;
  jobId: number;
  clientId?: number | null;
  /** `order_status` karty „Zatrudniony” (`null` = przed zatrudnieniem). */
  orderStatus: "complete" | "missing" | null | undefined;
  readOnly: boolean;
}) {
  // Ten sam klucz co warsztat „Umowa” (`JobContractTab`) — jedno zapytanie.
  const contracts = useQuery<B2BGeneratedContractRow[]>({
    queryKey: ["b2b-generated", "job", jobId],
    queryFn: () => b2bGeneratorApi.generated(50, { jobId }),
    staleTime: 60_000,
  });
  // Tylko żywa umowa: anulowana, zakończona i „bez projektu” nie liczą się jako
  // „wygenerowana”, a serwer odmówi im potwierdzenia podpisu (409).
  const row =
    (contracts.data ?? []).find(
      (r) =>
        r.candidate_id === candidateId &&
        (r.contract_status === "in_progress" || r.contract_status === "active"),
    ) ?? null;
  const loading = contracts.isLoading;
  const signed = row?.signature_status === "signed_both";
  const linkClass = "text-xs font-medium text-primary hover:underline";

  return (
    <div className="space-y-2 rounded-lg border border-border p-3 text-xs" data-testid="dock-contract-steps">
      <div className="text-sm font-semibold text-foreground">Umowa</div>
      {contracts.isError ? (
        <p role="alert" className="text-destructive">
          Nie udało się sprawdzić umowy.{" "}
          <button type="button" className="font-medium underline" onClick={() => void contracts.refetch()}>
            Ponów
          </button>
        </p>
      ) : (
        <ul className="space-y-2">
          <Step
            state={loading ? "loading" : row ? "done" : "todo"}
            title="Umowa wygenerowana"
            detail={row ? `Nr ${row.contract_number}` : null}
            action={
              !loading && !row && !readOnly ? (
                <Link href={generatorPrefillHref(candidateId, jobId)} className={linkClass}>
                  Otwórz Generator umów
                </Link>
              ) : null
            }
          />
          <Step
            state={loading ? "loading" : signed ? "done" : "todo"}
            title="Podpisana obustronnie"
            detail={
              row && !signed
                ? "„Oznacz jako podpisaną” w rejestrze zakłada kontrakt i zamówienie i przesuwa na „Zatrudniony”."
                : null
            }
            action={
              row && !signed && row.contract_status === "in_progress" && !readOnly ? (
                <Link
                  href={registerSearchHref(row.contract_number, row.contract_status)}
                  className={linkClass}
                >
                  Oznacz jako podpisaną w rejestrze
                </Link>
              ) : null
            }
          />
          {orderStatus ? (
            <Step
              state={orderStatus === "complete" ? "done" : "todo"}
              title="Zamówienie od klienta"
              detail={
                orderStatus === "missing"
                  ? "Brak uzupełnionego zamówienia — Delivery Lead i Finanse mają jedną sprawę „uzupełnij zamówienie”."
                  : null
              }
              action={
                orderStatus === "missing" && clientId ? (
                  <Link href={`/clients/${clientId}?tab=zamowienia`} className={linkClass}>
                    Zamówienia klienta
                  </Link>
                ) : null
              }
            />
          ) : null}
        </ul>
      )}
    </div>
  );
}
