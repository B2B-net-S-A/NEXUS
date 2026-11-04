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
 *
 * 04.10.2026 (rekruter generuje umowę w rekrutacji): „Wygeneruj umowę”
 * rozwija panel na zakładce „Umowa” z formularzem Generatora, a podpis
 * potwierdza się tu — oknem z rejestru („Podpis B2B”) albo prośbą do
 * Delivery Leada (`AgreementSignatureAction`). Sekcja stoi w każdej kolumnie,
 * w której para ma umowę, nie tylko na „Umowie” i „Zatrudnionym”.
 *
 * 20.10.2026 (pytania zespołu „czy zatrudnia tylko DL” i „czy bez zamówienia
 * się da”): przed zatrudnieniem sekcja nazywa się „Do „Zatrudnionego””, mówi,
 * że przesuwa każdy z zespołu, i ma drugą drogę — umowę spoza Generatora
 * (`onMarkHired`). Zamówienie stoi osobno, „Po zatrudnieniu — nie blokuje
 * ruchu”, z przerywanym kółkiem zamiast pustego „do zrobienia”. Makiety:
 * https://claude.ai/artifact/2m4b7dEXVnogXkcQymPiAA
 *
 * 21.10.2026 (podpis w NEXUSIE, etap 1b): umowa wysłana do podpisu w NEXUSIE
 * mówi, u kogo jest, a ręczny ruch na „Zatrudniony” czeka — ustawi się sam po
 * podpisie obu stron (serwer też odmawia: `ESIGN_IN_PROGRESS`).
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, FileSignature, Loader2 } from "lucide-react";

import { AgreementSignatureAction } from "@/components/v2/b2b-generator/AgreementSignatureAction";
import { Button } from "@/components/ui/button";
import { b2bGeneratorApi, type B2BGeneratedContractRow } from "@/lib/api";
import { daysSince, type CardAgreement } from "@/lib/b2b-agreement";
import { generatorPrefillHref, registerSearchHref } from "@/lib/b2b-generator-register";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";

/** Kody etapów kolumn „Umowa” i „Zatrudniony” (lustro `board-stages`). */
export const CONTRACT_PANEL_STAGES: ReadonlySet<string> = new Set([
  "acceptance",
  "negotiation",
  "hired",
  "onboarding",
]);

/** `later` — krok po zatrudnieniu, cudzy (przerywane kółko, nie „do zrobienia”). */
type StepState = "done" | "todo" | "loading" | "later";

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
      ) : state === "later" ? (
        <Circle
          className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70"
          strokeDasharray="3 3"
          aria-hidden
        />
      ) : (
        <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <span className={cn("text-foreground", state === "done" && "text-muted-foreground")}>
          {title}
          <span className="sr-only">
            {state === "done" ? " — zrobione" : state === "later" ? " — po zatrudnieniu" : " — do zrobienia"}
          </span>
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
  agreement = null,
  onGenerate,
  onMarkHired,
}: {
  candidateId: number;
  jobId: number;
  clientId?: number | null;
  /** `order_status` karty „Zatrudniony” (`null` = przed zatrudnieniem). */
  orderStatus: "complete" | "missing" | null | undefined;
  readOnly: boolean;
  /** Umowa pary z karty Tablicy (`item.agreement`) — data prośby o podpis. */
  agreement?: CardAgreement | null;
  /** Rozwija panel na zakładce „Umowa” z formularzem Generatora. */
  onGenerate?: () => void;
  /** Ruch na „Zatrudniony” (okno „Jak podpisano umowę?”) — umowa spoza
   *  Generatora. Brak = kolumna „Zatrudniony” niedostępna dla tej pary. */
  onMarkHired?: () => void;
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

  const waitingDays = row && !signed ? daysSince(row.created_at, new Date()) : null;
  const esign = !signed ? row?.esign ?? null : null;
  const inEsign = esign?.status === "sent" || esign?.status === "contractor_signed";

  // `orderStatus` niesie tylko karta „Zatrudniony” — po nim poznajemy etap.
  const hired = orderStatus != null;
  // Zatrudnienie bez Generatora (umowa o pracę, B2B poza Generatorem) nie ma
  // umowy w rejestrze — „Wygeneruj umowę” po fakcie tylko by myliło.
  const showGeneratorSteps = !hired || loading || row != null;

  return (
    <div
      className="space-y-2 rounded-lg border border-border p-3 text-xs"
      data-testid="dock-contract-steps"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">
          {hired ? "Umowa" : "Do „Zatrudnionego”"}
        </span>
        {row ? (
          <Link
            href={registerSearchHref(row.contract_number, row.contract_status)}
            className="text-[11px] text-muted-foreground hover:text-foreground hover:underline"
          >
            W rejestrze ↗
          </Link>
        ) : null}
      </div>
      {hired ? null : (
        <p className="text-[11px] text-muted-foreground" data-testid="dock-hire-who">
          Przesuwa każdy z zespołu rekrutacji. Zamówienie od klienta nie jest potrzebne.
        </p>
      )}
      {contracts.isError ? (
        <p role="alert" className="text-destructive">
          Nie udało się sprawdzić umowy.{" "}
          <button type="button" className="font-medium underline" onClick={() => void contracts.refetch()}>
            Ponów
          </button>
        </p>
      ) : (
        <ul className="space-y-2">
          {showGeneratorSteps ? (
            <>
              <Step
                state={loading ? "loading" : row ? "done" : "todo"}
                title="Umowa B2B z Generatora"
                detail={row ? `Nr ${row.contract_number}` : null}
                action={
                  !loading && !row && !readOnly ? (
                    onGenerate ? (
                      <Button size="sm" variant="outline" onClick={onGenerate}>
                        <FileSignature className="h-3.5 w-3.5" aria-hidden />
                        Wygeneruj umowę
                      </Button>
                    ) : (
                      <Link href={generatorPrefillHref(candidateId, jobId)} className={linkClass}>
                        Otwórz Generator umów
                      </Link>
                    )
                  ) : null
                }
              />
              <Step
                state={loading ? "loading" : signed ? "done" : "todo"}
                title="Podpisana obustronnie"
                detail={
                  // W podpisie w NEXUSIE kroki i opis daje `AgreementSignatureAction`.
                  inEsign
                    ? null
                    : row && !signed && row.contract_status === "in_progress"
                    ? `Czeka na podpis${
                        waitingDays ? ` od ${countPl(waitingDays, "dnia", "dni", "dni")}` : ""
                      }. Potwierdzenie podpisu przesuwa na „Zatrudniony” i zakłada kontrakt.`
                    : null
                }
                action={
                  row && !signed ? (
                    <AgreementSignatureAction
                      row={row}
                      jobId={jobId}
                      requestedAt={agreement?.signature_requested_at ?? null}
                      readOnly={readOnly}
                    />
                  ) : null
                }
              />
            </>
          ) : null}
          {!hired && inEsign ? (
            <li
              className="rounded-md border border-warning/40 bg-warning-muted px-2 py-1.5 text-warning-muted-foreground"
              data-testid="dock-hire-esign-lock"
            >
              Ręcznie na „Zatrudniony” przesuniesz dopiero po „Przejdź na zwykłą drogę”.
            </li>
          ) : !hired && onMarkHired && !readOnly ? (
            <li className="space-y-1 rounded-md bg-muted/40 px-2 py-1.5" data-testid="dock-hire-offline">
              <span className="block text-foreground">
                Umowa podpisana poza Generatorem? (B2B, umowa o pracę, zlecenie)
              </span>
              <Button size="sm" variant="outline" onClick={onMarkHired}>
                Przesuń na „Zatrudniony”…
              </Button>
            </li>
          ) : null}
        </ul>
      )}
      <div className="space-y-1.5 border-t border-border pt-2" data-testid="dock-after-hire">
        <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Po zatrudnieniu — nie blokuje ruchu
        </span>
        <ul className="space-y-2">
          <Step
            state={orderStatus === "complete" ? "done" : "later"}
            title="Zamówienie od klienta"
            detail={
              orderStatus === "complete"
                ? null
                : orderStatus === "missing"
                  ? "Szkic jest — uzupełnia Delivery Lead i Finanse (mają jedną sprawę „uzupełnij zamówienie”)."
                  : "Szkic powstanie sam przy zatrudnieniu; uzupełnia go Delivery Lead i Finanse."
            }
            action={
              orderStatus === "missing" && clientId ? (
                <Link href={`/clients/${clientId}?tab=zamowienia`} className={linkClass}>
                  Zamówienia klienta
                </Link>
              ) : null
            }
          />
        </ul>
      </div>
    </div>
  );
}
