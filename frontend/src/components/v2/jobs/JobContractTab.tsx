"use client";

/**
 * Krok 08 „Umowa" — program „flow w języku C2" (PR 7/7).
 *
 * Ostatni krok rozgrywa się dziś w trzech modułach POZA rekrutacją: Generator
 * Umów B2B (`/contracts/b2b-generator`), Kontrakty (`/contracts`) i Zamówienia
 * (profil klienta). Ta zakładka NICZEGO stamtąd nie przenosi — czyta ich stan
 * i linkuje w odpowiednie miejsce, tak żeby „podpis → kontrakt → zamówienie →
 * Delivery" dało się zobaczyć w jednym miejscu.
 *
 * Czego tu ŚWIADOMIE nie ma:
 *
 * - **Kwot kontraktu i marży.** Rejestr kontraktorów jest bramkowany sekcją
 *   Delivery i wąską listą ról (admin/DL/finanse/TCM), a rekruter prowadzący
 *   rekrutację zwykle żadnej z nich nie ma. Pokazanie tu stawek wymagałoby
 *   albo obejścia tamtej bramki, albo tabeli, która dla większości ról jest
 *   ciągiem „—”. Karta linkuje do modułu, w którym te dane mają swoje miejsce.
 * - **Listy braków POLICZONEJ dla konkretnego kontraktu.** `missing_fields`
 *   liczy backend na wierszu kontraktora (`validate_ready_for_activation`,
 *   z harmonogramami stawek), a ten wiersz jest za tą samą bramką. Zakładka
 *   pokazuje BRAMKĘ — dokładnie te pola, których wymaga aktywacja — zamiast
 *   liczyć je po swojemu i ryzykować, że powie co innego niż 409.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  CheckCircle2,
  ClipboardList,
  FileSignature,
  Loader2,
  ShieldAlert,
  XCircle,
} from "lucide-react";

import {
  b2bGeneratorApi,
  CONTRACT_FIELD_LABELS,
  type B2BGeneratedContractRow,
  type B2BStatusEvent,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, QueryStateNotice } from "@/components/ds";
import { cn, formatDate } from "@/lib/utils";
import { countPl } from "@/lib/plural-pl";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { terminalOf } from "@/lib/kanban-terminal";
import { isContractStage } from "@/lib/job-flow-stages";
import {
  columnLabel,
  type KanbanColumn,
  type KanbanItem,
} from "@/components/v2/pages/kanban-shared";
import { JobCloseWithReasonDialog } from "@/components/v2/jobs/JobCloseWithReasonDialog";

/**
 * Bramka aktywacji kontraktu — lustro `ACTIVATION_REQUIRED_FIELDS`
 * z `backend/app/services/contract_service.py`. `end_date` jest tu CELOWO
 * wypisane jako NIEwymagane: umowa bezterminowa to stan docelowy w
 * body-leasingu, a wymaganie daty końca więziło kompletne kontrakty w szkicu.
 */
const ACTIVATION_REQUIRED_FIELDS = [
  "start_date",
  "rate_candidate",
  "rate_client",
  "contract_type",
] as const;

const SIGNATURE_LABEL: Record<string, string> = {
  unsigned: "Czeka na podpis",
  signed_both: "Podpisana obustronnie",
};

const CONTRACT_STATUS_LABEL: Record<string, string> = {
  active: "Aktywna",
  in_progress: "W trakcie podpisu",
  suspended: "Bez projektu",
  closed: "Zakończona",
};

export interface JobContractTabProps {
  jobId: number;
  jobTitle: string;
  clientId?: number | null;
  columns: KanbanColumn[];
  readOnly: boolean;
  columnsLoading?: boolean;
  /**
   * Błąd zapytania kanbana. Pipeline przychodzi PROPSEM, więc bez tego 403
   * albo 500 renderowałby się tu jako „nikt nie doszedł do umowy".
   */
  columnsError?: unknown;
  columnsSuccess?: boolean;
  onColumnsRetry?: () => void;
  /** `job.update` — lustro `TacPlus`, tej samej bramki co `POST /jobs/{id}/close`. */
  canCloseJob: boolean;
}

interface ContractEntry {
  item: KanbanItem;
  col: KanbanColumn;
}

export function JobContractTab({
  jobId,
  jobTitle,
  clientId,
  columns,
  readOnly,
  columnsLoading = false,
  columnsError,
  columnsSuccess = true,
  onColumnsRetry,
  canCloseJob,
}: JobContractTabProps) {
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(
    null,
  );
  const [closeOpen, setCloseOpen] = useState(false);

  const entries = useMemo<ContractEntry[]>(
    () =>
      columns
        .filter(isContractStage)
        .flatMap((col) => col.items.map((item) => ({ item, col }))),
    [columns],
  );
  const hiredCount = useMemo(
    () =>
      columns
        .filter((c) => terminalOf(c) === "hired")
        .reduce((sum, c) => sum + c.items.length, 0),
    [columns],
  );

  const selected = useMemo<ContractEntry | null>(() => {
    if (entries.length === 0) return null;
    if (selectedCandidateId == null) return entries[0];
    return (
      entries.find((e) => e.item.candidate_id === selectedCandidateId) ??
      entries[0]
    );
  }, [entries, selectedCandidateId]);

  // Umowy wygenerowane DLA TEJ REKRUTACJI — filtr serwerowy (`job_id`), nie
  // przesiewanie pobranych `limit` wierszy rejestru.
  const contractsQuery = useQuery<B2BGeneratedContractRow[]>({
    queryKey: ["b2b-generated", "job", jobId],
    queryFn: () => b2bGeneratorApi.generated(50, { jobId }),
    staleTime: 60_000,
  });

  const contractsForSelected = useMemo(() => {
    const rows = contractsQuery.data ?? [];
    if (!selected) return rows;
    const forCandidate = rows.filter(
      (r) => r.candidate_id === selected.item.candidate_id,
    );
    // Umowa bez dowiązanego kandydata dalej dotyczy TEJ rekrutacji — ukrycie
    // jej zostawiłoby pustą kartę podpisu przy istniejącym dokumencie.
    return forCandidate.length > 0
      ? forCandidate
      : rows.filter((r) => r.candidate_id == null);
  }, [contractsQuery.data, selected]);

  const primaryContract = contractsForSelected[0] ?? null;

  const contractsViewState = resolveViewState({
    isLoading: contractsQuery.isLoading,
    isError: contractsQuery.isError,
    error: contractsQuery.error,
    isSuccess: contractsQuery.isSuccess,
    isEmpty: (contractsQuery.data ?? []).length === 0,
  });

  const listViewState = resolveViewState({
    isLoading: columnsLoading,
    isError: Boolean(columnsError),
    error: columnsError,
    isEmpty: entries.length === 0,
    isSuccess: columnsSuccess,
  });
  const listBlocked = isBlockingViewState(listViewState);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
      {/* ── Lewa kolumna: na etapach umowy ─────────────────────────── */}
      <aside className="space-y-4">
        <section className="rounded-xl border border-border bg-card p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold text-foreground">
              Na etapach umowy
            </h3>
            <Badge variant="outline" size="sm" className="tabular-nums">
              {entries.length}
            </Badge>
          </div>
          {listViewState === "loading" ? (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
            </div>
          ) : listBlocked ? (
            <QueryStateNotice
              state={listViewState as "forbidden" | "not_found" | "error"}
              description={
                listViewState === "error"
                  ? "Nie udało się wczytać pipeline'u tej rekrutacji. Kandydaci nie zniknęli — to nieudane pobranie."
                  : undefined
              }
              onRetry={listViewState === "error" ? onColumnsRetry : undefined}
            />
          ) : listViewState === "empty" ? (
            <p className="text-xs text-muted-foreground">
              Nikt nie jest jeszcze na etapie umowy ani zatrudnienia.
            </p>
          ) : (
            <ul className="space-y-1">
              {entries.map(({ item, col }) => {
                const active = item.candidate_id === selected?.item.candidate_id;
                return (
                  <li key={item.candidate_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedCandidateId(item.candidate_id)}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "w-full rounded-lg border px-2 py-1.5 text-left text-xs transition-colors",
                        active
                          ? "border-primary bg-primary/5 text-foreground"
                          : "border-border bg-background text-muted-foreground hover:bg-muted",
                      )}
                    >
                      <span className="block truncate font-medium text-foreground">
                        {`${item.name ?? ""} ${item.lastname ?? ""}`.trim() ||
                          "Kandydat"}
                      </span>
                      <span className="truncate">{columnLabel(col)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-border bg-card p-3 text-xs">
          <h3 className="mb-1 font-semibold text-foreground">Moduły</h3>
          <div className="flex flex-col gap-1">
            <ModuleLink href="/contracts/b2b-generator" label="Generator Umów B2B" />
            <ModuleLink href="/contracts" label="Kontrakty" />
            {clientId != null && (
              <ModuleLink
                href={`/clients/${clientId}?tab=zamowienia`}
                label="Zamówienia klienta"
              />
            )}
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Te moduły nie zmieniają miejsca — ta zakładka czyta ich stan.
          </p>
        </section>
      </aside>

      {/* ── Środek: podpis + hook + bramka aktywacji ───────────────── */}
      <section className="min-w-0 space-y-4">
        {listBlocked ? null : listViewState === "empty" ? (
          <EmptyState
            icon={FileSignature}
            title="Nikt nie doszedł jeszcze do umowy"
            description="Ten krok zbiera kandydatów na etapach „Umowa wysłana”, „Umowa podpisana”, „Zatrudniony” i „Onboarding”. Podpis prowadzi Generator Umów B2B — ta zakładka pokazuje jego wynik."
          />
        ) : (
          <>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[10px] font-semibold tracking-wide text-primary uppercase">
                    Podpis
                  </div>
                  <h2 className="truncate text-base font-semibold text-foreground">
                    {selected
                      ? `${selected.item.name ?? ""} ${selected.item.lastname ?? ""}`.trim() ||
                        "Kandydat"
                      : "Kandydat"}
                  </h2>
                  {selected && (
                    <p className="text-xs text-muted-foreground">
                      {columnLabel(selected.col)}
                      {selected.item.days_in_stage != null
                        ? ` · ${selected.item.days_in_stage} ${selected.item.days_in_stage === 1 ? "dzień" : "dni"} na etapie`
                        : ""}
                    </p>
                  )}
                </div>
                {primaryContract && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline" size="sm" className="font-mono">
                      {primaryContract.contract_number}
                    </Badge>
                    <Badge
                      size="sm"
                      variant={
                        primaryContract.signature_status === "signed_both"
                          ? "success"
                          : "warning"
                      }
                    >
                      {SIGNATURE_LABEL[primaryContract.signature_status] ??
                        primaryContract.signature_status}
                    </Badge>
                    <Badge size="sm" variant="soft">
                      {CONTRACT_STATUS_LABEL[primaryContract.contract_status] ??
                        primaryContract.contract_status}
                    </Badge>
                  </div>
                )}
              </div>

              <div className="mt-3">
                {contractsViewState === "loading" ? (
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie
                    umów…
                  </div>
                ) : contractsViewState === "forbidden" ||
                  contractsViewState === "not_found" ||
                  contractsViewState === "error" ? (
                  <QueryStateNotice
                    state={contractsViewState}
                    description={
                      contractsViewState === "error"
                        ? "Nie udało się wczytać umów tej rekrutacji. Umowy nadal istnieją — to nieudane pobranie listy."
                        : undefined
                    }
                    onRetry={
                      contractsViewState === "error"
                        ? () => void contractsQuery.refetch()
                        : undefined
                    }
                  />
                ) : primaryContract ? (
                  <>
                    {selected &&
                    primaryContract.candidate_id !== selected.item.candidate_id ? (
                      <p className="mb-2 rounded-md border border-warning-muted bg-warning-muted/40 px-2 py-1 text-[11px] text-warning-muted-foreground">
                        Ta umowa nie jest powiązana z żadnym kandydatem —
                        pokazujemy ją, bo należy do tej rekrutacji. Powiązanie
                        ustawia potwierdzenie podpisu w Generatorze B2B.
                      </p>
                    ) : null}
                    <SigningTimeline contract={primaryContract} />
                  </>
                ) : (
                  <p className="rounded-lg border border-dashed border-border p-3 text-xs text-muted-foreground">
                    Dla tej rekrutacji nie wygenerowano jeszcze umowy B2B.
                    Dokument tworzy Generator Umów B2B — hooki podpisu same
                    przeniosą kandydata na „Umowa wysłana” i „Umowa podpisana”.
                  </p>
                )}
              </div>

              {primaryContract && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <ModuleLink
                    href="/contracts/b2b-generator"
                    label="Otwórz w Generatorze B2B"
                    variant="button"
                  />
                  {primaryContract.contract_id != null && (
                    <ModuleLink
                      href={`/contracts/${primaryContract.contract_id}`}
                      label="Kontrakt w rejestrze"
                      variant="button"
                    />
                  )}
                </div>
              )}
            </div>

            <HiredHookCard clientId={clientId} hiredCount={hiredCount} />

            <ActivationGateCard
              contractId={primaryContract?.contract_id ?? null}
            />
          </>
        )}
      </section>

      {/* ── Dok „Przekazanie do Delivery" ──────────────────────────── */}
      <aside className="lg:col-span-2 xl:col-span-1 xl:sticky xl:top-4 xl:self-start">
        <div className="space-y-3 rounded-xl border border-border bg-card p-4">
          <div>
            <div className="text-[10px] font-semibold tracking-wide text-primary uppercase">
              Przekazanie do Delivery
            </div>
            <h3 className="text-sm font-semibold text-foreground">
              {jobTitle}
            </h3>
          </div>

          <dl className="space-y-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Na etapach umowy</dt>
              <dd className="font-medium tabular-nums text-foreground">
                {entries.length}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Zatrudnieni</dt>
              <dd className="font-medium tabular-nums text-foreground">
                {hiredCount}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Umowy tej rekrutacji</dt>
              <dd className="font-medium tabular-nums text-foreground">
                {contractsQuery.isLoading
                  ? "—"
                  : (contractsQuery.data ?? []).length}
              </dd>
            </div>
          </dl>

          <div className="space-y-1.5 border-t border-border pt-3">
            <div className="text-xs font-semibold text-foreground">
              Kto dostaje powiadomienie
            </div>
            <p className="text-[11px] text-muted-foreground">
              Po ruchu na „Zatrudniony” Delivery Leadowie tego klienta dostają
              „Nowy draft kontraktu + zamówienia” z linkiem do zakładki
              Zamówienia. Finanse widzą kontrakt dopiero po jego aktywacji.
            </p>
          </div>

          <div className="space-y-1.5 border-t border-border pt-3">
            {canCloseJob && !readOnly ? (
              <Button
                type="button"
                size="sm"
                className="w-full justify-start"
                onClick={() => setCloseOpen(true)}
              >
                <CheckCircle2 className="h-3.5 w-3.5" /> Zamknij rekrutację
                z powodem
              </Button>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                Zamknięcie rekrutacji wymaga roli TAC, Delivery Leada albo
                administratora.
              </p>
            )}
            <p className="text-[11px] text-muted-foreground">
              Automatu zamykania rekrutacji celowo nie ma — to przycisk, nie
              skutek uboczny zatrudnienia.
            </p>
          </div>
        </div>
      </aside>

      <JobCloseWithReasonDialog
        open={closeOpen}
        onOpenChange={setCloseOpen}
        jobId={jobId}
        jobTitle={jobTitle}
        clientId={clientId}
        defaultReason={hiredCount > 0 ? "filled_by_us" : "other"}
      />
    </div>
  );
}

// ── Oś podpisu ──────────────────────────────────────────────────────────────

function SigningTimeline({ contract }: { contract: B2BGeneratedContractRow }) {
  const historyQuery = useQuery<B2BStatusEvent[]>({
    queryKey: ["b2b-status-history", contract.id],
    queryFn: () => b2bGeneratorApi.statusHistory(contract.id),
    staleTime: 60_000,
  });

  const viewState = resolveViewState({
    isLoading: historyQuery.isLoading,
    isError: historyQuery.isError,
    error: historyQuery.error,
    isSuccess: historyQuery.isSuccess,
    isEmpty: (historyQuery.data ?? []).length === 0,
  });

  return (
    <div className="space-y-2">
      <ol className="space-y-2 text-xs">
        <TimelineRow
          done
          title="Umowa wygenerowana"
          detail={[
            contract.contract_number,
            contract.created_at ? formatDate(contract.created_at) : null,
            contract.created_by_name,
          ]
            .filter(Boolean)
            .join(" · ")}
        />
        <TimelineRow
          done={contract.signature_status === "signed_both"}
          title={
            contract.signature_status === "signed_both"
              ? "Podpisana obustronnie"
              : "Czeka na podpis"
          }
          detail={
            contract.signed_at
              ? `${formatDate(contract.signed_at)}${contract.signed_by_name ? ` · ${contract.signed_by_name}` : ""}`
              : "→ „Umowa podpisana”, obie strony → „Zatrudniony”"
          }
        />
      </ol>

      <details className="rounded-lg border border-border bg-muted/20 p-2.5 text-xs">
        <summary className="cursor-pointer font-medium text-foreground">
          Historia statusów umowy
        </summary>
        <div className="mt-2 space-y-1.5">
          {viewState === "loading" ? (
            <span className="inline-flex items-center gap-1.5 text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
            </span>
          ) : viewState === "forbidden" ||
            viewState === "not_found" ||
            viewState === "error" ? (
            <QueryStateNotice
              state={viewState}
              onRetry={
                viewState === "error"
                  ? () => void historyQuery.refetch()
                  : undefined
              }
            />
          ) : viewState === "empty" ? (
            <span className="text-muted-foreground">
              Status tej umowy nie był jeszcze zmieniany.
            </span>
          ) : (
            (historyQuery.data ?? []).map((event) => (
              <div
                key={event.id}
                className="flex items-start justify-between gap-2 text-muted-foreground"
              >
                <span>
                  <span className="font-medium text-foreground">
                    {CONTRACT_STATUS_LABEL[event.to_status] ?? event.to_status}
                  </span>
                  {event.from_status
                    ? ` ← ${CONTRACT_STATUS_LABEL[event.from_status] ?? event.from_status}`
                    : ""}
                  {event.changed_by_name ? ` · ${event.changed_by_name}` : ""}
                </span>
                <span className="shrink-0">
                  {event.effective_date
                    ? formatDate(event.effective_date)
                    : event.created_at
                      ? formatDate(event.created_at)
                      : ""}
                </span>
              </div>
            ))
          )}
        </div>
      </details>
    </div>
  );
}

function TimelineRow({
  done,
  title,
  detail,
}: {
  done: boolean;
  title: string;
  detail?: string | null;
}) {
  return (
    <li className="flex items-start gap-2">
      <span
        className={cn(
          "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
          done
            ? "bg-success-muted text-success-muted-foreground"
            : "bg-warning-muted text-warning-muted-foreground",
        )}
        aria-hidden="true"
      >
        {done ? (
          <CheckCircle2 className="h-3 w-3" />
        ) : (
          <XCircle className="h-3 w-3" />
        )}
      </span>
      <span className="min-w-0">
        <span className="block font-medium text-foreground">{title}</span>
        {detail ? (
          <span className="block text-muted-foreground">{detail}</span>
        ) : null}
      </span>
    </li>
  );
}

// ── „Co zrobi system po »Zatrudniony«" ──────────────────────────────────────

function HiredHookCard({
  clientId,
  hiredCount,
}: {
  clientId?: number | null;
  hiredCount: number;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h3 className="text-sm font-semibold text-foreground">
        Co zrobi system po „Zatrudniony”
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        Ruch na etap terminalny „Zatrudniony” wymaga jawnego potwierdzenia
        i uruchamia poniższe skutki. Zbiorczego zatrudniania nie ma — kartę
        przeciąga się pojedynczo.
      </p>
      <ul className="mt-2 space-y-1.5 text-xs">
        <HookRow
          label="Szkic kontraktu (osoba × klient)"
          detail="stawki, daty i tryb pracy do uzupełnienia w module Kontrakty"
        />
        <HookRow
          label="Szkic zamówienia klienta"
          detail="pomijany z podanym powodem, gdy osoba jest już na żywej linii zamówienia MD albo klient jest kosztowy"
        />
        <HookRow
          label="Powiadomienie do Delivery Leadów klienta"
          detail={
            clientId != null
              ? "„Nowy draft kontraktu + zamówienia” z linkiem do zakładki Zamówienia"
              : "wymaga klienta przypisanego do rekrutacji"
          }
        />
        <HookRow
          label="Podpowiedź zamknięcia rekrutacji"
          detail={
            hiredCount > 0
              ? `Zatrudnionych: ${countPl(hiredCount, "osoba", "osoby", "osób")} — przy komplecie obsady system podpowiada „Obsadzone przez nas”.`
              : "przy komplecie obsady system podpowiada powód „Obsadzone przez nas”"
          }
        />
      </ul>
    </div>
  );
}

function HookRow({ label, detail }: { label: string; detail: string }) {
  return (
    <li className="flex items-start gap-2">
      <ClipboardList
        className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
        aria-hidden="true"
      />
      <span>
        <span className="font-medium text-foreground">{label}</span>{" "}
        <span className="text-muted-foreground">— {detail}</span>
      </span>
    </li>
  );
}

// ── Bramka aktywacji kontraktu ──────────────────────────────────────────────

function ActivationGateCard({ contractId }: { contractId: number | null }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <ShieldAlert
          className="h-4 w-4 text-warning-muted-foreground"
          aria-hidden="true"
        />
        <h3 className="text-sm font-semibold text-foreground">
          Czego wymaga aktywacja kontraktu
        </h3>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Szkic przechodzi na „Aktywny” dopiero z kompletem tych pól. Backend
        odbija brak 409 z ich listą — tu jest ta sama lista, żeby nikt jej nie
        szukał po komunikacie błędu.
      </p>
      <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
        {ACTIVATION_REQUIRED_FIELDS.map((field) => (
          <li
            key={field}
            className="rounded-md border border-border bg-muted/20 px-2 py-1 text-foreground"
          >
            {CONTRACT_FIELD_LABELS[field] ?? field}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Data zakończenia NIE jest wymagana — umowa bezterminowa jest stanem
        docelowym, a nie brakiem danych.
      </p>
      {contractId != null ? (
        <div className="mt-2">
          <ModuleLink
            href={`/contracts/${contractId}`}
            label="Sprawdź braki na kontrakcie"
            variant="button"
          />
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-muted-foreground">
          Lista braków POLICZONA dla konkretnego kontraktu żyje w module
          Kontrakty — pojawi się tu jako link, gdy umowa zostanie powiązana
          z kontraktem.
        </p>
      )}
    </div>
  );
}

function ModuleLink({
  href,
  label,
  variant = "link",
}: {
  href: string;
  label: string;
  variant?: "link" | "button";
}) {
  return (
    <Link
      href={href}
      className={cn(
        variant === "button"
          ? "inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
          : "inline-flex items-center gap-1 text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
      <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
    </Link>
  );
}
