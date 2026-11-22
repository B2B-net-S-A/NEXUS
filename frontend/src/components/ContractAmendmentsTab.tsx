"use client";

// Zakładka „Aneksy” kontraktu — wariant A (decyzja Artura 19.11.2026):
// karta „Obowiązuje teraz” z jedną akcją „Dodaj aneks ▾” zamiast pięciu
// kolorowych przycisków, pod nią oś zmian po dniu wejścia w życie, identyczne
// zapisy zwinięte z cichym ostrzeżeniem. Logika osi i karty to czyste funkcje
// w `components/contracts/amendments/`.
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Paperclip } from "lucide-react";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { AnnexChange, AnnexState } from "@/lib/api/b2bDocuments";
import {
  annexRegisterHref,
  annexStateLabel,
  annexTitle,
  documentsHref,
} from "@/lib/b2b-documents";
import { openContractDocument } from "@/lib/contract-documents";
import { B2B_EXTENSION_HINT } from "@/lib/contract-end-date";
import { canAmendContractRates } from "@/lib/contract-rate-amendment";
import { formatIsoDatePl as formatDate, formatMomentPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";
import { canViewClientFinance, useAuthStore } from "@/store/auth";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { NoticeWithdrawalDialog } from "@/components/contracts/NoticeWithdrawalDialog";
import {
  AddAnnexMenu,
  type ManualAmendmentType,
} from "@/components/contracts/amendments/AddAnnexMenu";
import {
  AmendmentFormDialog,
  type AmendmentFormValues,
} from "@/components/contracts/amendments/AmendmentFormDialog";
import { AmendmentsNowCard } from "@/components/contracts/amendments/AmendmentsNowCard";
import {
  amendmentsNow,
  type AmendmentsContract,
} from "@/components/contracts/amendments/amendments-now";
import {
  amendmentAuthor,
  amendmentChangeLine,
  amendmentTitle,
  annexDocumentChangeLine,
  buildTimeline,
  duplicateNote,
  groupAmendments,
  savedDay,
  timelineSummary,
  untilDay,
  type AmendmentGroup,
  type ChangeLineMoney,
  type TimelineNode,
} from "@/components/contracts/amendments/amendments-timeline";
import {
  ANNEX_PARAM,
  annexRefusalText,
  hrefWithoutAnnexParam,
  parseAnnexIntent,
  resolveAnnexIntent,
  type AnnexIntent,
  type AnnexIntentGates,
} from "@/components/contracts/amendments/annex-intent";

/** Podpowiedź zamiast pętli „Przedłuż” ↔ „Cofnij zakończenie” (17.11.2026). */
export const NOTICE_WITHDRAWAL_HINT =
  "Konsultant wycofał wypowiedzenie? Służy do tego „Wycofaj wypowiedzenie” przy aneksie „Wcześniejsze zakończenie” poniżej.";

interface Amendment {
  id: number;
  contract_id: number;
  amendment_type:
    | ManualAmendmentType
    | "early_termination"
    | "start_date_change"
    | "party_data_change"
    | "subcontractor_consent"
    | "mandate_change"
    | "custom_change";
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  effective_date: string;
  reason: string | null;
  document_id: number | null;
  created_by: number | null;
  created_by_email: string | null;
  created_at: string;
  // Pola dokładane addytywnie (13.10.2026). Opcjonalne: odpowiedź starszego
  // backendu ich nie ma, a aneks nadal ma się wyświetlić.
  created_by_name?: string | null;
  /** `generator` = podpisany w Generatorze aneksów, `manual` = dodany tutaj. */
  source?: "generator" | "manual";
  b2b_document_id?: number | null;
  state?: AnnexState;
  document?: AmendmentDocument | null;
  /** Wypowiedzenie wycofane wpisem „Wycofanie wypowiedzenia”. */
  withdrawn?: boolean;
  /** Wypowiedzenie, które da się wycofać teraz. */
  withdrawable?: boolean;
}

interface AmendmentDocument {
  id: number;
  filename: string;
  is_signed_scan: boolean;
}

/**
 * Aneks z Generatora aneksów bez wpisu w historii kontraktu: czeka na podpis,
 * anulowany albo podpisany bez zmiany w kontrakcie. Rzut dokumentu z generatora.
 */
interface AnnexDocumentRow {
  document_id: number;
  document_type: string;
  type_label: string;
  state: AnnexState;
  effective_date: string | null;
  change: AnnexChange | null;
  cancelled_reason: string | null;
  created_at: string | null;
  created_by_name: string | null;
}

/**
 * Pusty formularz aneksu — liczony przy KAŻDYM otwarciu, nie raz przy
 * załadowaniu modułu. Stała `TODAY` z czasu importu zamrażała datę: karta
 * otwarta wczoraj podpowiadała wczorajszą datę wejścia w życie, a wyliczenie
 * z `toISOString()` dawało datę UTC, czyli między północą w Warszawie
 * a północą UTC — wczoraj (audyt FE-07).
 */
export function emptyAmendmentForm(
  amendmentType: ManualAmendmentType = "extension",
  today: string = warsawToday(),
): AmendmentFormValues {
  return {
    amendment_type: amendmentType,
    effective_date: today,
    reason: "",
    new_end_date: "",
    new_rate_candidate: "",
    new_rate_client: "",
    new_project_name: "",
    new_team_name: "",
  };
}

export interface ContractAmendmentsTabProps {
  contractId: number;
  clientId: number;
  readOnly?: boolean;
  /** Osoba z kontraktu — fraza linku „Otwórz w rejestrze aneksów”. */
  personName?: string | null;
  /** Umowa B2B bez ręcznego zakończenia — aneks przedłużający jest odrzucany
   *  przez backend, więc menu go nie oferuje (`b2bExtensionLocked`). */
  extensionLocked?: boolean;
  /** „Zakończenie wcześniej” otwiera okno „Zakończ współpracę” (ticket 09.2026) —
   *  zakończenie kontraktu ma jedno wejście, które zapisuje powód, datę końca
   *  projektu i rozwiązanie umowy. Bez callbacku pozycji nie ma. */
  onRequestTermination?: () => void;
  /** „Wycofaj wypowiedzenie” — ta sama bramka co „Cofnij zakończenie”
   *  (Admin, Finanse, TCM), niezależna od edycji kontraktu. */
  canWithdrawNotice?: boolean;
  /** Kontrakt (`GET /api/contracts/{id}`) do karty „Obowiązuje teraz”. Bez
   *  propsa zakładka bierze go z pamięci podręcznej strony (`["contract", id]`);
   *  bez obu pokazuje samą oś i menu „Dodaj aneks”. */
  contract?: AmendmentsContract | null;
}

export function ContractAmendmentsTab({
  contractId,
  clientId,
  readOnly = false,
  extensionLocked = false,
  onRequestTermination,
  personName = null,
  canWithdrawNotice = false,
  contract = null,
}: ContractAmendmentsTabProps) {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  // „Zmiana stawki” = to samo, co przepuszcza backend aneksów: trasa wymaga
  // edycji kontraktów (to niesie `readOnly` z góry), a aneks `rate_change`
  // dodatkowo uprawnienia „Stawki i kwoty: zmiana” u tego klienta.
  const canAmendRates = canAmendContractRates(user, clientId);
  const canViewFinance = canViewClientFinance(user, clientId);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<AmendmentFormValues>(() => emptyAmendmentForm());
  const [error, setError] = useState("");
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [refusedIntent, setRefusedIntent] = useState<AnnexIntent | null>(null);
  const timelineHeadingId = useId();
  const formId = `contract-amendment-form-${contractId}`;

  const amendmentsQuery = useQuery<Amendment[]>({
    queryKey: ["contract-amendments", contractId],
    queryFn: () =>
      api.get(`/api/contracts/${contractId}/amendments`).then((r) => r.data),
  });

  const annexDocumentsQuery = useQuery<AnnexDocumentRow[]>({
    queryKey: ["contract-annex-documents", contractId],
    queryFn: () =>
      api.get(`/api/contracts/${contractId}/annex-documents`).then((r) => r.data),
  });

  // Kontrakt do karty „Obowiązuje teraz”: z propsa albo z pamięci podręcznej
  // strony kontraktu (ten sam klucz). `enabled: false` — zakładka sama nie
  // pyta, więc harness i ekran bez wczytanego kontraktu po prostu nie mają
  // karty, a odświeżenie kontraktu po aneksie widać od razu.
  const cachedContract = useQuery<AmendmentsContract>({
    queryKey: ["contract", contractId],
    queryFn: () => api.get(`/api/contracts/${contractId}`).then((r) => r.data),
    enabled: false,
  }).data;
  const currentContract = contract ?? cachedContract ?? null;

  // „Dołącz skan” przy aneksie z generatora: plik trafia do Dokumentów
  // kontraktu i zastępuje wygenerowany DOCX jako plik aneksu.
  const scanInput = useRef<HTMLInputElement>(null);
  const [scanTarget, setScanTarget] = useState<number | null>(null);
  const [scanError, setScanError] = useState<{ id: number; message: string } | null>(
    null,
  );
  const scanMutation = useMutation({
    mutationFn: ({ amendmentId, file }: { amendmentId: number; file: File }) => {
      const body = new FormData();
      body.append("file", file);
      return api.post(
        `/api/contracts/${contractId}/amendments/${amendmentId}/document`,
        body,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
    },
    onSuccess: () => {
      setScanError(null);
      queryClient.invalidateQueries({ queryKey: ["contract-amendments", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contract-documents", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
    },
    onError: (err: unknown, variables) => {
      setScanError({
        id: variables.amendmentId,
        message: apiErrorMessage(err, "Nie udało się zapisać skanu."),
      });
    },
  });

  const openForm = (type: ManualAmendmentType) => {
    setForm(emptyAmendmentForm(type));
    setError("");
    setRefusedIntent(null);
    setShowForm(true);
  };
  const closeForm = () => {
    setShowForm(false);
    setForm(emptyAmendmentForm());
    setError("");
  };

  const createMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post(`/api/contracts/${contractId}/amendments`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract-amendments", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      // Aneks zmienia status, datę końca i stawki — lista kontraktów, lista
      // „kończących się" i historia stawek muszą to zobaczyć bez przeładowania
      // strony (audyt FE-02). Klucze: `ContractsListV2`, `contracts/[id]`.
      queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
      queryClient.invalidateQueries({ queryKey: ["contracts-quick-counts"] });
      queryClient.invalidateQueries({ queryKey: ["contract-rate-history", contractId] });
      closeForm();
    },
    onError: (err: unknown) => {
      setError(apiErrorMessage(err, err instanceof Error ? err.message : "Błąd"));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (form.amendment_type === "rate_change" && !canAmendRates) {
      closeForm();
      return;
    }
    const payload: Record<string, unknown> = {
      amendment_type: form.amendment_type,
      effective_date: form.effective_date,
      reason: form.reason || null,
    };
    if (form.amendment_type === "extension" && form.new_end_date) {
      payload.new_end_date = form.new_end_date;
    }
    if (form.amendment_type === "rate_change" && canAmendRates) {
      if (form.new_rate_candidate) payload.new_rate_candidate = Number(form.new_rate_candidate);
      if (form.new_rate_client) payload.new_rate_client = Number(form.new_rate_client);
    }
    if (form.amendment_type === "scope_change") {
      if (form.new_project_name) payload.new_project_name = form.new_project_name;
      if (form.new_team_name) payload.new_team_name = form.new_team_name;
    }
    createMutation.mutate(payload);
  };

  const amendments = useMemo(
    () =>
      (amendmentsQuery.data ?? []).filter(
        (amendment) => canViewFinance || amendment.amendment_type !== "rate_change",
      ),
    [amendmentsQuery.data, canViewFinance],
  );
  // Aneksy z Generatora aneksów widać od wygenerowania („czeka na podpis”),
  // nie dopiero po podpisie. Wiersze bez `document_id` odrzucamy: to nie jest
  // odpowiedź tej trasy (starszy backend, pomyłka w zaślepce testu).
  const annexDocuments = useMemo(
    () =>
      (Array.isArray(annexDocumentsQuery.data) ? annexDocumentsQuery.data : []).filter(
        (row) =>
          typeof row?.document_id === "number" &&
          (canViewFinance || row.document_type !== "annex_rate_change"),
      ),
    [annexDocumentsQuery.data, canViewFinance],
  );
  const waiting = annexDocuments.filter((row) => row.state === "waiting");
  const waitingRateAnnex = waiting.some(
    (row) => row.document_type === "annex_rate_change",
  );

  const today = warsawToday();
  const groups = useMemo(() => groupAmendments(amendments), [amendments]);
  const nodes = useMemo(
    () => buildTimeline(groups, annexDocuments, today),
    [groups, annexDocuments, today],
  );
  const money: ChangeLineMoney = {
    clientCurrency: currentContract?.rate_client_currency ?? currentContract?.currency ?? null,
    candidateCurrency:
      currentContract?.rate_candidate_currency ?? currentContract?.currency ?? null,
    rateUnit: currentContract?.rate_unit ?? null,
  };
  const now = currentContract
    ? amendmentsNow(currentContract, { today, canSeeRates: canViewFinance })
    : null;

  const hasRows = amendments.length > 0 || annexDocuments.length > 0;
  const noticeToWithdraw = canWithdrawNotice && amendments.some((a) => a.withdrawable);
  const extensionHint = noticeToWithdraw ? NOTICE_WITHDRAWAL_HINT : B2B_EXTENSION_HINT;
  const historyState = resolveViewState({
    isLoading: amendmentsQuery.isLoading || annexDocumentsQuery.isLoading,
    error: amendmentsQuery.error,
    isSuccess: amendmentsQuery.isSuccess,
    isEmpty: !hasRows,
  });
  // „Brak aneksów” dopiero, gdy OBA odczyty się udały i oba są puste: awaria
  // listy czekających aneksów przy pustej historii to nie pustka.
  const viewState =
    historyState === "empty" && !annexDocumentsQuery.isSuccess
      ? "ready"
      : historyState;

  // `?aneks=rate_change` itd. — przycisk „Dodaj aneks” w nagłówku kontraktu
  // otwiera zakładkę od razu z właściwym oknem. Parametr znika natywną
  // historią (stan `null`, jak `useUrlWriter`: Next przenosi adres do
  // `useSearchParams` bez przewijania), żeby odświeżenie nie otwierało okna
  // drugi raz, a kolejne kliknięcie w nagłówku znów było zmianą adresu.
  const searchParams = useSearchParams();
  const annexParam = searchParams?.get(ANNEX_PARAM) ?? null;
  const handledParam = useRef<string | null>(null);
  const gates: AnnexIntentGates = {
    readOnly,
    canAmendRates,
    extensionLocked,
    canTerminate: Boolean(onRequestTermination),
  };
  useEffect(() => {
    if (annexParam === null) {
      handledParam.current = null;
      return;
    }
    if (handledParam.current === annexParam) return;
    handledParam.current = annexParam;
    const { pathname, search, hash } = window.location;
    window.history.replaceState(null, "", hrefWithoutAnnexParam(`${pathname}${search}${hash}`));
    const intent = parseAnnexIntent(annexParam);
    if (!intent) return;
    const action = resolveAnnexIntent(intent, {
      readOnly,
      canAmendRates,
      extensionLocked,
      canTerminate: Boolean(onRequestTermination),
    });
    if (action.kind === "form") {
      setForm(emptyAmendmentForm(action.type));
      setError("");
      setRefusedIntent(null);
      setShowForm(true);
    } else if (action.kind === "terminate") {
      onRequestTermination?.();
    } else if (action.kind === "document") {
      // Inna strona (Generator aneksów). W historii stoi już adres bez
      // `aneks=`, więc „Wstecz” z generatora wraca na zakładkę i nie
      // przekierowuje drugi raz.
      window.location.assign(documentsHref({ newType: "annex_rate_change", contractId }));
    } else {
      setRefusedIntent(intent);
    }
  }, [annexParam, readOnly, canAmendRates, extensionLocked, onRequestTermination, contractId]);

  const scan: ScanControls = {
    readOnly,
    pending: scanMutation.isPending,
    error: scanError,
    onAttach: (amendmentId) => {
      setScanTarget(amendmentId);
      scanInput.current?.click();
    },
  };

  const footnote = (
    <p className="text-[12px] text-muted-foreground">
      Aneks z Generatora aneksów zmienia kontrakt dopiero po podpisie; aneks dodany
      tutaj działa od razu.
    </p>
  );

  return (
    <div className="space-y-4">
      {/* Bramka zapisu jest jedna i przychodzi z góry (`readOnly`) — bez
          zagnieżdżonej bramki po roli, która chowała akcje posiadaczom
          uprawnienia spoza ról admin/Delivery Lead. */}
      <AmendmentsNowCard
        now={now}
        actions={
          readOnly ? null : (
            <AddAnnexMenu
              canAmendRates={canAmendRates}
              extensionLocked={extensionLocked}
              extensionHint={extensionHint}
              onPick={openForm}
              onRequestTermination={onRequestTermination}
              documentHref={documentsHref({ newType: "annex_rate_change", contractId })}
            />
          )
        }
      />

      {refusedIntent ? (
        <p
          role="status"
          className="flex items-start gap-2 rounded-lg bg-muted px-3 py-2 text-[12.5px] leading-5 text-muted-foreground"
        >
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">
            {annexRefusalText(refusedIntent, gates, extensionHint)}
          </span>
          <button
            type="button"
            onClick={() => setRefusedIntent(null)}
            className="shrink-0 font-medium text-primary hover:underline"
          >
            Zamknij
          </button>
        </p>
      ) : null}

      {viewState === "loading" ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Ładowanie aneksów…
        </div>
      ) : viewState === "forbidden" ||
        viewState === "not_found" ||
        viewState === "error" ? (
        <QueryStateNotice
          state={viewState}
          onRetry={() => void amendmentsQuery.refetch()}
        />
      ) : viewState === "empty" ? (
        <>
          <p className="rounded-xl border border-border bg-card px-4 py-5 text-[13px] text-muted-foreground shadow-xs">
            Brak aneksów — kontrakt nie był zmieniany aneksem.
            {readOnly ? "" : " Zmianę zapisuje się przyciskiem „Dodaj aneks”."}
          </p>
          {footnote}
        </>
      ) : (
        <>
          {annexDocumentsQuery.isError ? (
            <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
              Nie udało się wczytać aneksów czekających na podpis — oś pokazuje
              tylko zmiany już zapisane w kontrakcie.{" "}
              <button
                type="button"
                className="font-medium underline"
                onClick={() => void annexDocumentsQuery.refetch()}
              >
                Ponów
              </button>
            </p>
          ) : null}
          {nodes.length > 0 ? (
            <section
              aria-labelledby={timelineHeadingId}
              className="rounded-xl border border-border bg-card px-4 pb-4 pt-3 shadow-xs"
            >
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <h2 id={timelineHeadingId} className="text-[13.5px] font-semibold text-foreground">
                  Zmiany według daty wejścia w życie
                </h2>
                <span className="text-[12px] text-muted-foreground">
                  {timelineSummary(groups.length, waiting.length, amendments.length - groups.length)}
                </span>
              </div>
              <ol aria-labelledby={timelineHeadingId}>
                {nodes.map((node, index) => (
                  <TimelineDay
                    key={node.date ?? "bez-daty"}
                    node={node}
                    last={index === nodes.length - 1}
                    today={today}
                  >
                    {node.waiting.map((row) => (
                      <AnnexDocumentEntry
                        key={`d-${row.document_id}`}
                        row={row}
                        personName={personName}
                      />
                    ))}
                    {node.groups.map((group) => (
                      <AmendmentEntry
                        key={group.key}
                        group={group}
                        contractId={contractId}
                        money={money}
                        today={today}
                        scan={scan}
                        canWithdrawNotice={canWithdrawNotice}
                        onWithdraw={() => setWithdrawOpen(true)}
                      />
                    ))}
                    {node.documents.map((row) => (
                      <AnnexDocumentEntry
                        key={`d-${row.document_id}`}
                        row={row}
                        personName={personName}
                      />
                    ))}
                  </TimelineDay>
                ))}
              </ol>
            </section>
          ) : null}
          {footnote}
        </>
      )}

      <AmendmentFormDialog
        open={showForm && !readOnly}
        formId={formId}
        form={form}
        onChange={setForm}
        onSubmit={handleSubmit}
        onClose={closeForm}
        error={error}
        pending={createMutation.isPending}
        contractId={contractId}
        canAmendRates={canAmendRates}
        canViewFinance={canViewFinance}
        waitingRateAnnex={waitingRateAnnex}
      />

      {withdrawOpen && (
        <NoticeWithdrawalDialog
          contractId={contractId}
          onClose={() => setWithdrawOpen(false)}
        />
      )}

      <input
        ref={scanInput}
        type="file"
        accept=".pdf,.jpg,.jpeg,.png"
        className="hidden"
        aria-label="Skan podpisanego aneksu"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file && scanTarget !== null) {
            scanMutation.mutate({ amendmentId: scanTarget, file });
          }
        }}
      />
    </div>
  );
}

/** Separator drobnego druku: kropka trzyma się poprzedniego słowa (twarda
 *  spacja), a czytnik ekranu dostaje zwykłą spację zamiast „kropki”. */
const Dot = () => (
  <>
    <span aria-hidden className="px-0.5">{"\u00a0·"}</span>{" "}
  </>
);

/** Dzień na osi: data po lewej, kropka i kreska, wpisy po prawej. */
function TimelineDay({
  node,
  last,
  today,
  children,
}: {
  node: TimelineNode<Amendment, AnnexDocumentRow>;
  last: boolean;
  today: string;
  children: ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <div className="w-[92px] shrink-0 pt-px text-right">
        <p
          className={cn(
            "text-[13px] font-semibold tabular-nums",
            node.current ? "text-foreground" : "text-muted-foreground",
          )}
        >
          {node.date ? formatDate(node.date) : "bez daty"}
        </p>
        {node.future && node.date ? (
          <p className="text-[11.5px] text-info-muted-foreground">{untilDay(node.date, today)}</p>
        ) : null}
        {node.current ? <p className="text-[11.5px] text-muted-foreground">obowiązuje</p> : null}
      </div>
      <div className="relative flex w-3 shrink-0 justify-center">
        <span
          aria-hidden
          className={cn(
            "relative z-10 mt-1 size-2.5 rounded-full border-2 bg-card",
            node.current
              ? "border-primary"
              : node.future
                ? "border-info"
                : "border-muted-foreground/40",
          )}
        />
        {!last ? <span aria-hidden className="absolute bottom-0 top-4 w-px bg-border" /> : null}
      </div>
      <ul className={cn("min-w-0 flex-1 space-y-3", !last && "pb-5")}>{children}</ul>
    </li>
  );
}

interface ScanControls {
  readOnly: boolean;
  pending: boolean;
  error: { id: number; message: string } | null;
  onAttach: (amendmentId: number) => void;
}

/** Plik aneksu: otwarcie z Dokumentów kontraktu, stan podpisu, „Dołącz skan”. */
function EntryFiles({
  amendment: a,
  contractId,
  scan,
}: {
  amendment: Amendment;
  contractId: number;
  scan: ScanControls;
}) {
  const generator = a.source === "generator";
  const doc = a.document;
  return (
    <>
      {doc ? (
        <button
          type="button"
          title={doc.filename}
          className="inline-flex min-w-0 max-w-full items-center gap-1 align-bottom font-medium text-primary hover:underline"
          onClick={() => void openContractDocument(contractId, doc)}
        >
          <Paperclip className="size-3 shrink-0" aria-hidden />
          <span className="max-w-[22rem] truncate">{doc.filename}</span>
        </button>
      ) : (
        <span>bez dokumentu</span>
      )}
      {generator && doc ? (
        <>
          <Dot />
          <span>{doc.is_signed_scan ? "skan podpisany" : "bez podpisów"}</span>
        </>
      ) : null}
      {/* Skan dołącza się tylko do aneksu z generatora. */}
      {generator && !scan.readOnly && !doc?.is_signed_scan ? (
        <>
          <Dot />
          <button
            type="button"
            className="font-medium text-primary hover:underline disabled:opacity-60"
            disabled={scan.pending}
            onClick={() => scan.onAttach(a.id)}
          >
            Dołącz skan
          </button>
        </>
      ) : null}
    </>
  );
}

/** Zmiana zapisana w kontrakcie (ewentualnie kilka identycznych zapisów). */
function AmendmentEntry({
  group,
  contractId,
  money,
  today,
  scan,
  canWithdrawNotice,
  onWithdraw,
}: {
  group: AmendmentGroup<Amendment>;
  contractId: number;
  money: ChangeLineMoney;
  today: string;
  scan: ScanControls;
  canWithdrawNotice: boolean;
  onWithdraw: () => void;
}) {
  const [open, setOpen] = useState(false);
  const a = group.main;
  const change = amendmentChangeLine(a, money);
  const author = amendmentAuthor(a);
  const repeated = group.entries.length > 1;
  return (
    <li className="space-y-1">
      <p
        className={cn(
          "flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13.5px] font-semibold leading-5",
          a.withdrawn ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {amendmentTitle(a)}
        {a.withdrawn ? <StatusDot tone="neutral">Wycofany</StatusDot> : null}
        {!a.withdrawn && a.state === "signed_pending" ? (
          <StatusDot tone="info">
            Podpisany · wejdzie w życie {untilDay(a.effective_date, today)}
          </StatusDot>
        ) : null}
      </p>
      {change ? (
        <p
          className={cn(
            "text-[13px] leading-5 tabular-nums",
            a.withdrawn ? "text-muted-foreground line-through" : "text-foreground",
          )}
        >
          {change}
        </p>
      ) : null}
      <p className="text-[12px] leading-5 text-muted-foreground">
        <span>{a.source === "generator" ? "z Generatora aneksów" : "ręcznie"}</span>
        <Dot />
        <EntryFiles amendment={a} contractId={contractId} scan={scan} />
        <Dot />
        <span>
          {author ? `${author}, ` : ""}
          {savedDay(a.created_at)}
        </span>
      </p>
      {scan.error && group.entries.some((e) => e.id === scan.error?.id) ? (
        <p role="alert" className="text-xs text-destructive">
          {scan.error.message}
        </p>
      ) : null}
      {group.reason ? (
        <blockquote className="border-l-2 border-border pl-3 text-[12.5px] leading-5 text-muted-foreground">
          „{group.reason}”
        </blockquote>
      ) : null}
      {canWithdrawNotice && group.entries.some((e) => e.withdrawable) ? (
        <Button type="button" variant="outline" size="sm" className="mt-1 h-7" onClick={onWithdraw}>
          Wycofaj wypowiedzenie
        </Button>
      ) : null}
      {repeated ? (
        <div className="text-[12px] leading-5 text-muted-foreground">
          <p>
            <AlertTriangle className="mr-1 inline size-3.5 -translate-y-px text-warning" aria-hidden />
            <span>{duplicateNote(group.entries)}</span>
            <Dot />
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpen((value) => !value)}
              className="font-medium text-primary hover:underline"
            >
              {open ? "Ukryj wpisy" : "Pokaż wpisy"}
            </button>
          </p>
          {open ? (
            <ul className="mt-1 space-y-0.5 border-l border-border pl-3">
              {group.entries.map((entry) => (
                <li key={entry.id} className="tabular-nums">
                  <span>{formatMomentPl(entry.created_at)}</span>
                  <Dot />
                  <span>{amendmentAuthor(entry) ?? "autor nieznany"}</span>
                  <Dot />
                  <span>{entry.reason?.trim() ? "z uzasadnieniem" : "bez uzasadnienia"}</span>
                  {entry.id === a.id ? (
                    <>
                      <Dot />
                      <span>pierwszy zapis</span>
                    </>
                  ) : entry.document || entry.source === "generator" ? (
                    <>
                      <Dot />
                      <EntryFiles amendment={entry} contractId={contractId} scan={scan} />
                    </>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/** Aneks z Generatora aneksów bez wpisu w historii kontraktu. */
function AnnexDocumentEntry({
  row,
  personName,
}: {
  row: AnnexDocumentRow;
  personName: string | null;
}) {
  const state = annexStateLabel(row.state);
  const change = annexDocumentChangeLine(row.change);
  const waiting = row.state === "waiting";
  const cancelled = row.state === "cancelled";
  const who = [row.created_by_name, row.created_at ? savedDay(row.created_at) : null]
    .filter(Boolean)
    .join(", ");
  return (
    <li className="space-y-1">
      <p
        className={cn(
          "flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13.5px] font-semibold leading-5",
          cancelled ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {annexTitle(row.document_type)}
        <StatusDot tone={state.tone}>{state.label}</StatusDot>
      </p>
      {change ? (
        <p
          className={cn(
            "text-[13px] leading-5 tabular-nums",
            cancelled ? "text-muted-foreground line-through" : "text-foreground",
          )}
        >
          {change}
        </p>
      ) : null}
      <p className="text-[12px] leading-5 text-muted-foreground">
        <span>z Generatora aneksów</span>
        {waiting ? (
          <>
            <Dot />
            <span>zmieni kontrakt po oznaczeniu jako podpisany</span>
          </>
        ) : null}
        {cancelled ? (
          <>
            <Dot />
            <span>
              zmiana nie weszła w życie
              {row.cancelled_reason ? ` — ${row.cancelled_reason}` : ""}
            </span>
          </>
        ) : null}
        {who ? (
          <>
            <Dot />
            <span>{who}</span>
          </>
        ) : null}
        {waiting ? (
          <>
            <Dot />
            <Link
              href={annexRegisterHref(personName)}
              className="font-medium text-primary hover:underline"
            >
              Otwórz w rejestrze aneksów
            </Link>
          </>
        ) : null}
      </p>
    </li>
  );
}
