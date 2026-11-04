"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { apiErrorMessage } from "@/lib/api-error";
import type { AnnexChange, AnnexState } from "@/lib/api/b2bDocuments";
import {
  annexChangeText,
  annexRegisterHref,
  annexStateLabel,
  annexTitle,
  documentsHref,
} from "@/lib/b2b-documents";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { openContractDocument } from "@/lib/contract-documents";
import { StatusDot } from "@/components/ds/StatusDot";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import {
  contractDetailLabel,
  contractDetailValue,
} from "@/components/contracts/contract-timeline-labels";
import { B2B_EXTENSION_HINT } from "@/lib/contract-end-date";
import { canAmendContractRates } from "@/lib/contract-rate-amendment";
import { warsawToday } from "@/lib/warsaw-date";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { resolveViewState } from "@/lib/view-state";
import { canViewClientFinance, useAuthStore } from "@/store/auth";
import {
  CalendarPlus,
  Banknote,
  LayoutGrid,
  X as StopIcon,
  Loader2,
  AlertCircle,
  FilePlus2,
} from "lucide-react";

const TYPE_LABELS: Record<string, string> = {
  extension: "Przedłużenie",
  rate_change: "Zmiana stawki",
  scope_change: "Zmiana zakresu",
  early_termination: "Wcześniejsze zakończenie",
  // Typy zapisywane po podpisie aneksu z Generatora aneksów (0362).
  start_date_change: "Zmiana daty startu",
  party_data_change: "Uzupełnienie danych firmy",
  subcontractor_consent: "Osoba skierowana",
  mandate_change: "Aneks do umowy zlecenie",
};

/** Nazwa typu aneksu; typ, którego front jeszcze nie zna, nie zostaje pusty. */
export function amendmentTypeLabel(type: string): string {
  return TYPE_LABELS[type] ?? "Aneks";
}

/** Typy, które zakłada formularz tej zakładki. */
type ManualAmendmentType =
  | "extension"
  | "rate_change"
  | "scope_change"
  | "early_termination";

interface Amendment {
  id: number;
  contract_id: number;
  amendment_type:
    | ManualAmendmentType
    | "start_date_change"
    | "party_data_change"
    | "subcontractor_consent"
    | "mandate_change";
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  effective_date: string;
  reason: string | null;
  document_id: number | null;
  created_by: number | null;
  created_by_email: string | null;
  created_at: string;
  // Zakładka jako tabela (13.10.2026). Opcjonalne: odpowiedź starszego
  // backendu ich nie ma, a aneks nadal ma się wyświetlić.
  created_by_name?: string | null;
  /** `generator` = podpisany w Generatorze aneksów, `manual` = dodany tutaj. */
  source?: "generator" | "manual";
  b2b_document_id?: number | null;
  state?: AnnexState;
  document?: { id: number; filename: string; is_signed_scan: boolean } | null;
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

/** Co zmieni się w kontrakcie po podpisie — zdanie do komunikatu nad tabelą. */
function pendingEffect(row: AnnexDocumentRow): string {
  const change = annexChangeText(row.change);
  const since = row.effective_date ? ` od ${formatDate(row.effective_date)}` : "";
  if (!change) return "Po oznaczeniu jako podpisany zmiana wejdzie do kontraktu.";
  if (row.change?.kind === "rate") {
    return `Po oznaczeniu jako podpisany stawka kosztowa zmieni się na ${change.after}${since}.`;
  }
  if (row.change?.kind === "start_date") {
    return `Po oznaczeniu jako podpisany data rozpoczęcia kontraktu zmieni się na ${change.after}.`;
  }
  if (row.change?.kind === "party") {
    return `Po oznaczeniu jako podpisany Partnerem będzie ${change.after}${since}.`;
  }
  return `Po oznaczeniu jako podpisany do kontraktu wejdzie: ${change.after}${since}.`;
}

type AmendmentType = ManualAmendmentType;

interface FormState {
  amendment_type: AmendmentType;
  effective_date: string;
  reason: string;
  new_end_date: string;
  new_rate_candidate: string;
  new_rate_client: string;
  new_project_name: string;
  new_team_name: string;
}

/**
 * Pusty formularz aneksu — liczony przy KAŻDYM otwarciu, nie raz przy
 * załadowaniu modułu. Stała `TODAY` z czasu importu zamrażała datę: karta
 * otwarta wczoraj podpowiadała wczorajszą datę wejścia w życie, a wyliczenie
 * z `toISOString()` dawało datę UTC, czyli między północą w Warszawie
 * a północą UTC — wczoraj (audyt FE-07).
 */
export function emptyAmendmentForm(
  amendmentType: AmendmentType = "extension",
  today: string = warsawToday(),
): FormState {
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

export function ContractAmendmentsTab({
  contractId,
  clientId,
  readOnly = false,
  extensionLocked = false,
  onRequestTermination,
  personName = null,
}: {
  contractId: number;
  clientId: number;
  readOnly?: boolean;
  /** Osoba z kontraktu — fraza linku „Otwórz w rejestrze aneksów”. */
  personName?: string | null;
  /** Umowa B2B bez ręcznego zakończenia — aneks przedłużający jest odrzucany
   *  przez backend, więc przycisk go nie oferuje (`b2bExtensionLocked`). */
  extensionLocked?: boolean;
  /** „Zakończ wcześniej" otwiera okno „Zakończ współpracę" (ticket 09.2026) —
   *  zakończenie kontraktu ma jedno wejście, które zapisuje powód, datę końca
   *  projektu i rozwiązanie umowy. Bez callbacku przycisku nie ma. */
  onRequestTermination?: () => void;
}) {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  // „Zmień stawkę” = to samo, co przepuszcza backend aneksów: trasa wymaga
  // edycji kontraktów (to niesie `readOnly` z góry), a aneks `rate_change`
  // dodatkowo uprawnienia „Stawki i kwoty: zmiana” u tego klienta.
  const canAmendRates = canAmendContractRates(user, clientId);
  const canViewFinance = canViewClientFinance(user, clientId);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(() => emptyAmendmentForm());
  const [error, setError] = useState("");

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

  // „Dołącz skan” przy aneksie z generatora: plik trafia do Dokumentów
  // kontraktu i zastępuje wygenerowany DOCX jako plik aneksu.
  const scanInput = useRef<HTMLInputElement>(null);
  const [scanTarget, setScanTarget] = useState<number | null>(null);
  const [scanError, setScanError] = useState<{ id: number; message: string } | null>(
    null,
  );
  const scanMutation = useMutation({
    mutationFn: ({ amendmentId, file }: { amendmentId: number; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return api.post(
        `/api/contracts/${contractId}/amendments/${amendmentId}/document`,
        form,
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
      queryClient.invalidateQueries({ queryKey: ["contracts-expiring-v2"] });
      queryClient.invalidateQueries({ queryKey: ["contract-rate-history", contractId] });
      setShowForm(false);
      setForm(emptyAmendmentForm());
      setError("");
    },
    onError: (err: unknown) => {
      setError(apiErrorMessage(err, err instanceof Error ? err.message : "Błąd"));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (form.amendment_type === "rate_change" && !canAmendRates) {
      setShowForm(false);
      setForm(emptyAmendmentForm());
      setError("");
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

  const amendments = (amendmentsQuery.data ?? []).filter(
    (amendment) =>
      canViewFinance || amendment.amendment_type !== "rate_change",
  );
  // Aneksy z Generatora aneksów widać od wygenerowania („czeka na podpis”),
  // nie dopiero po podpisie. Wiersze bez `document_id` odrzucamy: to nie jest
  // odpowiedź tej trasy (starszy backend, pomyłka w zaślepce testu).
  const annexDocuments = (
    Array.isArray(annexDocumentsQuery.data) ? annexDocumentsQuery.data : []
  ).filter(
    (row) =>
      typeof row?.document_id === "number" &&
      (canViewFinance || row.document_type !== "annex_rate_change"),
  );
  const waiting = annexDocuments.filter((row) => row.state === "waiting");
  const otherDocuments = annexDocuments.filter((row) => row.state !== "waiting");
  const waitingRateAnnex = waiting.some(
    (row) => row.document_type === "annex_rate_change",
  );

  const hasRows = amendments.length > 0 || annexDocuments.length > 0;
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

  return (
    <div className="space-y-4">
      {/* Bramka zapisu jest jedna i przychodzi z góry (`readOnly`) — bez
          zagnieżdżonej bramki po roli, która chowała przyciski posiadaczom
          uprawnienia spoza ról admin/Delivery Lead. */}
      {!readOnly && !showForm && (
        <div className="flex flex-wrap gap-2">
            <button
              onClick={() => {
                setForm(emptyAmendmentForm("extension"));
                setShowForm(true);
              }}
              disabled={extensionLocked}
              title={extensionLocked ? B2B_EXTENSION_HINT : undefined}
              className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:hover:bg-emerald-600 text-white px-3 py-2 rounded-lg text-sm font-medium"
            >
              <CalendarPlus className="w-4 h-4" /> Przedłuż
            </button>
            {canAmendRates && (
              <button
                onClick={() => {
                  setForm(emptyAmendmentForm("rate_change"));
                  setShowForm(true);
                }}
                className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white px-3 py-2 rounded-lg text-sm font-medium"
              >
                <Banknote className="w-4 h-4" /> Zmień stawkę
              </button>
            )}
            <button
              onClick={() => {
                setForm(emptyAmendmentForm("scope_change"));
                setShowForm(true);
              }}
              className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white px-3 py-2 rounded-lg text-sm font-medium"
            >
              <LayoutGrid className="w-4 h-4" /> Zmień zakres
            </button>
            {onRequestTermination && (
              <button
                type="button"
                onClick={onRequestTermination}
                className="flex items-center gap-2 bg-red-600 hover:bg-red-700 text-white px-3 py-2 rounded-lg text-sm font-medium"
              >
                <StopIcon className="w-4 h-4" /> Zakończ wcześniej
              </button>
            )}
            {/* Dokument aneksu do podpisu (DOCX) — zakładka „Generator
                aneksów” w module Generator Umów B2B (`documentsHref` z typem
                aneksu prowadzi tam), umowa bazowa po tym kontrakcie. */}
            <Link
              href={documentsHref({ newType: "annex_rate_change", contractId })}
              className="flex items-center gap-2 border border-border hover:bg-muted text-foreground px-3 py-2 rounded-lg text-sm font-medium"
            >
              <FilePlus2 className="w-4 h-4" /> Wygeneruj dokument aneksu
            </Link>
            {extensionLocked && (
              <p className="basis-full text-xs text-muted-foreground">
                {B2B_EXTENSION_HINT}
              </p>
            )}
        </div>
      )}

      {!readOnly && showForm && (
        <form
          onSubmit={handleSubmit}
          className="bg-card dark:bg-muted rounded-2xl shadow-xs p-4 space-y-3 border border-primary/20 dark:border-primary/10"
        >
          <h3 className="text-sm font-semibold">
            {TYPE_LABELS[form.amendment_type]}
          </h3>
          {error && (
            <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 dark:bg-red-900/30 dark:text-red-300 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4" /> {error}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                Data wejścia w życie
              </span>
              <input
                type="date"
                value={form.effective_date}
                onChange={(e) => setForm({ ...form, effective_date: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>

            {/* Wcześniejsze zakończenie nie jest już aneksem z tego formularza —
                idzie oknem „Zakończ współpracę” (audyt 24.09, S5: backend
                odmawia `termination_required`). */}
            {form.amendment_type === "extension" && (
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  Nowa data zakończenia
                </span>
                <input
                  type="date"
                  value={form.new_end_date}
                  onChange={(e) =>
                    setForm({ ...form, new_end_date: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
            )}
          </div>

          {form.amendment_type === "rate_change" && waitingRateAnnex && (
            <p className="rounded-lg bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
              Aneks zmiany stawki z Generatora aneksów czeka na podpis — po jego
              podpisaniu stawka zmieni się jeszcze raz. Jeśli to ta sama zmiana,
              oznacz tamten aneks jako podpisany zamiast zapisywać stawkę tutaj.
            </p>
          )}
          {form.amendment_type === "rate_change" && canAmendRates && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  Nowa stawka kandydata
                </span>
                <input
                  type="number"
                  step="0.001"
                  value={form.new_rate_candidate}
                  onChange={(e) =>
                    setForm({ ...form, new_rate_candidate: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  Nowa stawka klienta
                </span>
                <input
                  type="number"
                  step="0.001"
                  value={form.new_rate_client}
                  onChange={(e) =>
                    setForm({ ...form, new_rate_client: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
            </div>
          )}

          {form.amendment_type === "scope_change" && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  Nowy projekt
                </span>
                <input
                  type="text"
                  value={form.new_project_name}
                  onChange={(e) =>
                    setForm({ ...form, new_project_name: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  Nowy zespół
                </span>
                <input
                  type="text"
                  value={form.new_team_name}
                  onChange={(e) =>
                    setForm({ ...form, new_team_name: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
            </div>
          )}

          <label className="block">
            <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
              Powód / uwagi
            </span>
            <textarea
              rows={2}
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
              className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
            />
          </label>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setShowForm(false);
                setForm(emptyAmendmentForm());
                setError("");
              }}
              className="px-3 py-2 text-sm text-foreground hover:bg-muted dark:text-muted-foreground dark:hover:bg-muted rounded-lg"
            >
              Anuluj
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="bg-primary hover:bg-primary/90 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              {createMutation.isPending ? "Zapisywanie…" : "Zapisz aneks"}
            </button>
          </div>
        </form>
      )}

      {viewState === "loading" ? (
        <div className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie aneksów…
        </div>
      ) : viewState === "forbidden" ||
        viewState === "not_found" ||
        viewState === "error" ? (
        <QueryStateNotice
          state={viewState}
          onRetry={() => void amendmentsQuery.refetch()}
        />
      ) : viewState === "empty" ? (
        <div className="text-sm text-muted-foreground italic bg-card dark:bg-muted rounded-2xl p-8 text-center shadow-xs">
          {readOnly ? (
            "Brak aneksów."
          ) : (
            <>
              Brak aneksów — użyj przycisków powyżej, żeby przedłużyć,
              {canAmendRates ? " zmienić stawkę," : ""} zmienić zakres lub
              zakończyć kontrakt wcześniej.
            </>
          )}
        </div>
      ) : (
        <>
          {annexDocumentsQuery.isError ? (
            <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
              Nie udało się wczytać aneksów czekających na podpis — tabela
              pokazuje tylko zmiany już zapisane w kontrakcie.{" "}
              <button
                type="button"
                className="font-medium underline"
                onClick={() => void annexDocumentsQuery.refetch()}
              >
                Ponów
              </button>
            </p>
          ) : null}
          {waiting.map((row) => (
            <div
              key={row.document_id}
              role="status"
              className="flex flex-wrap items-start justify-between gap-3 rounded-lg bg-warning-muted px-4 py-3 text-warning-muted-foreground"
            >
              <div className="min-w-0 flex-1 basis-80">
                <div className="text-sm font-semibold">
                  Aneks „{annexTitle(row.document_type)}” czeka na podpis
                </div>
                <div className="text-sm">{pendingEffect(row)}</div>
              </div>
              <Link
                href={annexRegisterHref(personName)}
                className="shrink-0 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
              >
                Otwórz w rejestrze aneksów
              </Link>
            </div>
          ))}
          {hasRows ? (
          <div className="relative overflow-x-auto rounded-2xl bg-card px-4 py-2 shadow-xs dark:bg-muted">
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
            <table className="w-full min-w-[900px] table-fixed text-sm">
              <colgroup>
                <col className="w-[11%]" />
                <col className="w-[17%]" />
                <col className="w-[23%]" />
                <col className="w-[14%]" />
                <col className="w-[10%]" />
                <col className="w-[14%]" />
                <col className="w-[11%]" />
              </colgroup>
              <thead>
                <tr className="border-b border-border text-left">
                  <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Wchodzi w życie</th>
                  <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Typ aneksu</th>
                  <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Zmiana</th>
                  <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Status</th>
                  <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Źródło</th>
                  <th scope="col" className={`py-2 pr-3 ${CALM_HEAD}`}>Dokument</th>
                  <th scope="col" className={`py-2 ${CALM_HEAD}`}>Dodał</th>
                </tr>
              </thead>
              <tbody>
                {waiting.map((row) => (
                  <AnnexDocumentTableRow key={`d-${row.document_id}`} row={row} />
                ))}
                {amendments.map((a) => {
                  const state = annexStateLabel(a.state ?? "in_force");
                  const fromGenerator = a.source === "generator";
                  return (
                    <tr key={`a-${a.id}`} className={`${CALM_ROW} align-top`}>
                      <td className="whitespace-nowrap py-2.5 pr-3 tabular-nums">
                        {formatDate(a.effective_date)}
                      </td>
                      <td className="py-2.5 pr-3 font-medium text-foreground">
                        {amendmentTypeLabel(a.amendment_type)}
                      </td>
                      <td className="py-2.5 pr-3">
                        {/* Czytelna lista pól zamiast surowego JSON-a (audyt
                            24.09, N9): klucz → etykieta PL, wartość → data,
                            status, jednostka po polsku. */}
                        <AmendmentValues old={a.old_values} next={a.new_values} />
                        {a.reason && !fromGenerator ? (
                          <span className={CALM_SUBLINE}>{a.reason}</span>
                        ) : null}
                      </td>
                      <td className="py-2.5 pr-3">
                        <StatusDot
                          tone={state.tone}
                          note={
                            a.state === "signed_pending"
                              ? `wejdzie w życie ${formatDate(a.effective_date)}`
                              : null
                          }
                        >
                          {state.label}
                        </StatusDot>
                      </td>
                      <td className="py-2.5 pr-3">
                        {fromGenerator ? "Generator aneksów" : "Ręcznie"}
                      </td>
                      <td className="py-2.5 pr-3">
                        {a.document ? (
                          <button
                            type="button"
                            className="break-words text-left font-medium text-primary hover:underline"
                            onClick={() => {
                              if (a.document) void openContractDocument(contractId, a.document);
                            }}
                          >
                            {a.document.filename}
                          </button>
                        ) : (
                          <span className={CALM_EMPTY}>brak</span>
                        )}
                        {a.document && fromGenerator ? (
                          <span className={CALM_SUBLINE}>
                            {a.document.is_signed_scan
                              ? "skan podpisany"
                              : "wygenerowany, bez podpisów"}
                          </span>
                        ) : null}
                        {fromGenerator && !readOnly && !a.document?.is_signed_scan ? (
                          <button
                            type="button"
                            className="mt-0.5 block text-xs font-medium text-primary hover:underline disabled:opacity-60"
                            disabled={scanMutation.isPending}
                            onClick={() => {
                              setScanTarget(a.id);
                              scanInput.current?.click();
                            }}
                          >
                            Dołącz skan
                          </button>
                        ) : null}
                        {scanError?.id === a.id ? (
                          <span role="alert" className="mt-0.5 block text-xs text-destructive">
                            {scanError.message}
                          </span>
                        ) : null}
                      </td>
                      <td className="py-2.5">
                        <span className="whitespace-nowrap text-xs tabular-nums text-foreground">
                          {formatDate(a.created_at)}
                        </span>
                        <span className={CALM_SUBLINE}>
                          {a.created_by_name || a.created_by_email || "—"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
                {otherDocuments.map((row) => (
                  <AnnexDocumentTableRow key={`d-${row.document_id}`} row={row} />
                ))}
              </tbody>
            </table>
          </div>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Aneks z Generatora aneksów zmienia kontrakt dopiero po podpisie.
            Aneks dodany przyciskami powyżej działa od razu i nie ma dokumentu
            do podpisu.
          </p>
        </>
      )}
    </div>
  );
}

/** Wiersz aneksu z Generatora aneksów bez wpisu w historii kontraktu. */
function AnnexDocumentTableRow({ row }: { row: AnnexDocumentRow }) {
  const state = annexStateLabel(row.state);
  const change = annexChangeText(row.change);
  const muted = row.state === "cancelled" ? "text-muted-foreground" : "";
  return (
    <tr className={`${CALM_ROW} align-top ${muted}`}>
      <td className="whitespace-nowrap py-2.5 pr-3 tabular-nums">
        {row.effective_date ? (
          formatDate(row.effective_date)
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
      </td>
      <td className="py-2.5 pr-3 font-medium">{annexTitle(row.document_type)}</td>
      <td className="py-2.5 pr-3 tabular-nums">
        {change ? (
          <>
            {change.before ? (
              <>
                <span className="text-muted-foreground line-through">
                  {change.before}
                </span>
                {" → "}
              </>
            ) : null}
            {change.after}
          </>
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
        {row.state === "cancelled" ? (
          <span className={CALM_SUBLINE}>nie weszła w życie</span>
        ) : null}
      </td>
      <td className="py-2.5 pr-3">
        <StatusDot
          tone={state.tone}
          note={row.state === "cancelled" ? row.cancelled_reason : null}
        >
          {state.label}
        </StatusDot>
      </td>
      <td className="py-2.5 pr-3">Generator aneksów</td>
      <td className="py-2.5 pr-3">
        <span className={CALM_EMPTY}>
          {row.state === "waiting" ? "po podpisie" : "brak"}
        </span>
      </td>
      <td className="py-2.5">
        <span className="whitespace-nowrap text-xs tabular-nums text-foreground">
          {row.created_at ? formatDate(row.created_at) : "—"}
        </span>
        <span className={CALM_SUBLINE}>{row.created_by_name || "—"}</span>
      </td>
    </tr>
  );
}

/** Pola zmienione aneksem: „przed → po” dla kluczy z `new_values`. */
export function amendmentChangeRows(
  old: Record<string, unknown> | null,
  next: Record<string, unknown> | null,
): { key: string; label: string; before: string; after: string }[] {
  const keys = Object.keys(next ?? {});
  return keys.map((key) => ({
    key,
    label: contractDetailLabel(key),
    before: contractDetailValue(key, old?.[key]),
    after: contractDetailValue(key, next?.[key]),
  }));
}

function AmendmentValues({
  old,
  next,
}: {
  old: Record<string, unknown> | null;
  next: Record<string, unknown> | null;
}) {
  const rows = amendmentChangeRows(old, next);
  if (rows.length === 0) return null;
  return (
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
      {rows.map((row) => (
        <div key={row.key} className="contents">
          <dt className="text-muted-foreground">{row.label}</dt>
          <dd className="min-w-0 break-words">
            {row.before !== "—" && row.before !== row.after ? (
              <>
                <span className="text-muted-foreground line-through">
                  {row.before}
                </span>{" "}
                → {row.after}
              </>
            ) : (
              row.after
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
