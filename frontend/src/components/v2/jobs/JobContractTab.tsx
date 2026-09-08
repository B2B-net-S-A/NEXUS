"use client";

/**
 * Krok 08 „Umowa" — program „flow w języku C2" (układ z makiety, fala 3).
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
  BellRing,
  CheckCircle2,
  FileSignature,
  HandHeart,
  Loader2,
  ShieldAlert,
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
import {
  ChromeTimeline,
  ChromeTimelineEntry,
  DockActions,
  DockSection,
  KvList,
  RailRow,
  RailSection,
  ReadyItem,
  ReqRow,
  ToolPill,
  WorkbenchCard,
  WorkbenchDock,
  WorkbenchHeader,
  WorkbenchRail,
  type DockTabItem,
} from "@/components/v2/jobs/workbench-chrome";

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

type DockTab = "after" | "order" | "alerts";

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
  const [dockTab, setDockTab] = useState<DockTab>("after");

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

  const selectedName = selected
    ? `${selected.item.name ?? ""} ${selected.item.lastname ?? ""}`.trim() ||
      "Kandydat"
    : null;

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

  const dockTabs: DockTabItem[] = [
    { value: "after", label: "Po podpisie" },
    { value: "order", label: "Zamówienie" },
    { value: "alerts", label: "Alerty DL" },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
      {/* ── Szyna: na etapach umowy, podpis, alternatywy, moduły ────── */}
      <WorkbenchRail
        icon={<FileSignature className="h-4 w-4 text-primary" />}
        title="Na etapach umowy"
        count={entries.length}
        meta={hiredCount > 0 ? `${hiredCount} zatrudnionych` : null}
        footer={
          primaryContract ? (
            <SigningStatusHistory contract={primaryContract} />
          ) : undefined
        }
      >
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
          <div className="space-y-0.5" role="list" aria-label="Na etapach umowy">
            {entries.map(({ item, col }) => (
              <div key={item.candidate_id} role="listitem">
                <RailRow
                  tone="warn"
                  label={
                    `${item.name ?? ""} ${item.lastname ?? ""}`.trim() ||
                    "Kandydat"
                  }
                  meta={columnLabel(col)}
                  active={item.candidate_id === selected?.item.candidate_id}
                  onSelect={() => setSelectedCandidateId(item.candidate_id)}
                />
              </div>
            ))}
          </div>
        )}

        <RailSection label="Podpis">
          {contractsViewState === "loading" ? (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie umów…
            </div>
          ) : contractsViewState === "forbidden" ||
            contractsViewState === "not_found" ||
            contractsViewState === "error" ? (
            // Komunikat awarii stoi RAZ, w karcie obok — dwa te same napisy
            // na jednym ekranie czyta się jak dwie różne awarie.
            <p className="text-[11px] text-warning-muted-foreground">
              Stanu podpisu nie znamy — patrz komunikat w karcie zamknięcia.
            </p>
          ) : primaryContract ? (
            <SigningTimeline contract={primaryContract} />
          ) : (
            <p className="text-[11px] text-muted-foreground">
              Brak wygenerowanej umowy B2B dla tej rekrutacji.
            </p>
          )}
        </RailSection>

        <RailSection
          label="Alternatywy (jak dziś)"
          note="Wszystkie trzy akcje mieszkają w Generatorze Umów B2B — tu jest do nich wejście, nie ich kopia."
        >
          <div className="flex flex-wrap gap-1">
            {["Oznacz wysłaną", "Wgraj podpisaną (PDF)", "Potwierdź w pełni podpisaną"].map(
              (label) => (
                <Link
                  key={label}
                  href="/contracts/b2b-generator"
                  className="inline-flex h-6 items-center rounded-full border border-border px-2 text-[11px] text-foreground hover:border-primary hover:bg-primary/5"
                >
                  {label}
                </Link>
              ),
            )}
          </div>
        </RailSection>

        <RailSection
          label="Moduły"
          note="Te moduły nie zmieniają miejsca — ta zakładka czyta ich stan."
        >
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
        </RailSection>
      </WorkbenchRail>

      {/* ── Środek: zamknięcie, hook i bramka aktywacji ────────────── */}
      <section className="min-w-0 space-y-4">
        {listBlocked ? null : listViewState === "empty" ? (
          <EmptyState
            icon={FileSignature}
            title="Nikt nie doszedł jeszcze do umowy"
            description="Ten krok zbiera kandydatów na etapach „Umowa wysłana”, „Umowa podpisana”, „Zatrudniony” i „Onboarding”. Podpis prowadzi Generator Umów B2B — ta zakładka pokazuje jego wynik."
          />
        ) : (
          <>
            <WorkbenchHeader
              title={`Zamknięcie · ${selectedName ?? "Kandydat"}`}
              subtitle={[
                primaryContract
                  ? `Umowa ${primaryContract.contract_number}`
                  : "Bez wygenerowanej umowy B2B",
                primaryContract?.start_date
                  ? `start ${formatDate(primaryContract.start_date)}`
                  : null,
                primaryContract?.client_name,
              ]
                .filter(Boolean)
                .join(" · ")}
              badges={
                primaryContract ? (
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
                ) : null
              }
              actions={
                <>
                  <ModuleLink
                    href="/contracts/b2b-generator"
                    label="Otwórz w Generatorze B2B"
                    variant="button"
                  />
                  {primaryContract?.contract_id != null && (
                    <ModuleLink
                      href={`/contracts/${primaryContract.contract_id}`}
                      label="Kontrakt w rejestrze"
                      variant="button"
                    />
                  )}
                </>
              }
              tools={
                <>
                  {selected && (
                    <ToolPill tone="warn">
                      {columnLabel(selected.col)}
                      {selected.item.days_in_stage != null
                        ? ` · ${selected.item.days_in_stage} d`
                        : ""}
                    </ToolPill>
                  )}
                  <ToolPill
                    tone={
                      primaryContract?.contract_id != null ? "info" : "neutral"
                    }
                  >
                    Kontrakt:{" "}
                    {primaryContract?.contract_id != null
                      ? `#${primaryContract.contract_id}`
                      : "szkic po podpisie"}
                  </ToolPill>
                  <ToolPill>Zamówienie: szkic po podpisie</ToolPill>
                  {primaryContract && (
                    <ToolPill>
                      {CONTRACT_STATUS_LABEL[primaryContract.contract_status] ??
                        primaryContract.contract_status}
                    </ToolPill>
                  )}
                </>
              }
            />

            {contractsViewState === "forbidden" ||
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
            ) : !primaryContract && contractsViewState !== "loading" ? (
              <p className="rounded-lg border border-dashed border-border p-3 text-xs text-muted-foreground">
                Dla tej rekrutacji nie wygenerowano jeszcze umowy B2B. Dokument
                tworzy Generator Umów B2B — hooki podpisu same przeniosą
                kandydata na „Umowa wysłana” i „Umowa podpisana”.
              </p>
            ) : selected &&
              primaryContract &&
              primaryContract.candidate_id !== selected.item.candidate_id ? (
              <p className="rounded-md border border-warning-muted bg-warning-muted/40 px-2 py-1 text-[11px] text-warning-muted-foreground">
                Ta umowa nie jest powiązana z żadnym kandydatem — pokazujemy ją,
                bo należy do tej rekrutacji. Powiązanie ustawia potwierdzenie
                podpisu w Generatorze B2B.
              </p>
            ) : null}

            <HiredHookCard clientId={clientId} hiredCount={hiredCount} />

            <ActivationGateCard
              contractId={primaryContract?.contract_id ?? null}
            />
          </>
        )}
      </section>

      {/* ── Dok „Przekazanie do Delivery" ──────────────────────────── */}
      <aside className="lg:col-span-2 xl:col-span-1 xl:sticky xl:top-4 xl:self-start">
        <WorkbenchDock
          name="Przekazanie do Delivery"
          who={selectedName ?? jobTitle}
          whoSub={[
            primaryContract?.client_name,
            jobTitle,
            primaryContract?.start_date
              ? `od ${formatDate(primaryContract.start_date)}`
              : null,
          ]
            .filter(Boolean)
            .join(" · ")}
          tabs={dockTabs}
          activeTab={dockTab}
          onTabChange={(v) => setDockTab(v as DockTab)}
          footer={
            <>
              <ShieldAlert className="h-3 w-3 shrink-0" />
              Automatu zamykania rekrutacji celowo nie ma — przycisk, nie skutek
              uboczny.
            </>
          }
        >
          {dockTab === "after" && (
            <>
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

              <DockSection
                title="Kontrakt"
                right={
                  primaryContract?.contract_id != null
                    ? `/contracts/${primaryContract.contract_id}`
                    : undefined
                }
              >
                <KvList
                  rows={[
                    {
                      k: "Status",
                      v:
                        primaryContract?.contract_id != null
                          ? "Szkic → Aktywny po uzupełnieniu bramki"
                          : "Szkic powstanie po ruchu na „Zatrudniony”",
                    },
                    {
                      k: "Stawki",
                      v: "w module Kontrakty (bramka finansowa Delivery)",
                    },
                    {
                      k: "Okres",
                      v: primaryContract?.start_date
                        ? `${formatDate(primaryContract.start_date)} → bezterminowo, o ile nikt nie wpisze daty końca`
                        : "start z umowy, koniec niewymagany",
                    },
                  ]}
                />
              </DockSection>

              <DockSection title="Kto dostał powiadomienie">
                <ul className="space-y-1 text-xs">
                  <NotifiedRow
                    label="Delivery Leadowie klienta"
                    detail={
                      clientId != null
                        ? "„Nowy draft kontraktu + zamówienia” — po ruchu na „Zatrudniony”"
                        : "wymaga klienta przypisanego do rekrutacji"
                    }
                    done={hiredCount > 0 && clientId != null}
                  />
                  <NotifiedRow
                    label="TAC — właściciel requestu"
                    detail="podpowiedź „komplet obsady — zamknij rekrutację”"
                    done={hiredCount > 0}
                  />
                  <NotifiedRow
                    label="Finanse"
                    detail="dopiero po aktywacji kontraktu"
                    done={false}
                  />
                </ul>
              </DockSection>
            </>
          )}

          {dockTab === "order" && (
            <DockSection
              title="Zamówienie"
              right={
                clientId != null
                  ? `/clients/${clientId}?tab=zamowienia`
                  : undefined
              }
            >
              <KvList
                rows={[
                  { k: "Status", v: "Szkic · numer z PDF zamówienia (PO)" },
                  {
                    k: "Typ",
                    v: "okresowe — chyba że klient jest kosztowy albo osoba jest na żywej linii grupy MD (wtedy szkic nie powstaje, z podanym powodem)",
                  },
                  {
                    k: "Odczyt PDF",
                    v: "reguły klienta stosują się przy wgraniu PO w module Zamówienia",
                  },
                ]}
              />
              {clientId != null ? (
                <ModuleLink
                  href={`/clients/${clientId}?tab=zamowienia`}
                  label="Otwórz Zamówienia klienta"
                  variant="button"
                />
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  Ta rekrutacja nie ma przypiętego klienta — bez niego nie ma
                  zakładki Zamówienia ani odbiorcy powiadomienia.
                </p>
              )}
            </DockSection>
          )}

          {dockTab === "alerts" && (
            <DockSection title="Alerty Delivery Leada">
              <p className="text-xs text-muted-foreground">
                Po przekazaniu do Delivery kontraktem i zamówieniem opiekuje się
                skaner alertów DL. Pięć typów spraw: kontrakt bez kompletu do
                aktywacji, brak PDF zamówienia (PO), zbliżający się koniec
                zamówienia, zbliżający się koniec kontraktu i wyczerpany budżet
                MD. Nieobsłużona sprawa wraca co 7 dni jako NOWY wpis — dziennik
                jest raportem czasu reakcji.
              </p>
              {clientId != null && (
                <ModuleLink
                  href={`/clients/${clientId}?tab=zamowienia`}
                  label="Sprawy tego klienta"
                  variant="button"
                />
              )}
            </DockSection>
          )}

          <div className="space-y-1.5 border-t border-border pt-3">
            <DockActions>
              {canCloseJob && !readOnly ? (
                <Button
                  type="button"
                  size="sm"
                  className="col-span-2 w-full justify-start"
                  onClick={() => setCloseOpen(true)}
                >
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {hiredCount > 0
                    ? "Zamknij rekrutację: „Obsadzone przez nas”"
                    : "Zamknij rekrutację z powodem"}
                </Button>
              ) : (
                <p className="col-span-2 text-[11px] text-muted-foreground">
                  Zamknięcie rekrutacji wymaga roli TAC, Delivery Leada albo
                  administratora.
                </p>
              )}
              {selected && (
                <Link
                  href={`/candidates/${selected.item.candidate_id}`}
                  className="inline-flex h-8 items-center justify-start gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
                  title="Profil kandydata — onboarding i dokumenty"
                >
                  <HandHeart className="h-3.5 w-3.5" /> Onboarding →
                </Link>
              )}
              <Link
                href="/contracts"
                className="inline-flex h-8 items-center justify-start gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
                title="Alerty DL prowadzi moduł Kontrakty i zakładka Zamówienia klienta"
              >
                <BellRing className="h-3.5 w-3.5" /> Alerty DL (5 typów)
              </Link>
            </DockActions>
          </div>
        </WorkbenchDock>
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
  const signed = contract.signature_status === "signed_both";
  return (
    <ChromeTimeline>
      <ChromeTimelineEntry
        tone="done"
        title="Umowa wygenerowana"
        meta={contract.contract_number}
        who={[
          contract.language ? `DOCX ${contract.language.toUpperCase()}` : null,
          contract.created_at ? formatDate(contract.created_at) : null,
          contract.created_by_name,
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      <ChromeTimelineEntry
        tone={signed ? "done" : "now"}
        title={signed ? "Podpisana obustronnie" : "Czeka na podpis"}
        meta={
          contract.signing_date ? formatDate(contract.signing_date) : undefined
        }
        who={
          contract.signed_at
            ? `${formatDate(contract.signed_at)}${contract.signed_by_name ? ` · ${contract.signed_by_name}` : ""}`
            : "→ „Umowa podpisana”, obie strony → „Zatrudniony”"
        }
      />
    </ChromeTimeline>
  );
}

/** Historia statusów umowy — rozwijana, w stopce szyny (jak w makiecie). */
function SigningStatusHistory({
  contract,
}: {
  contract: B2BGeneratedContractRow;
}) {
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
  );
}

function NotifiedRow({
  label,
  detail,
  done,
}: {
  label: string;
  detail: string;
  done: boolean;
}) {
  return (
    <li className="flex items-start gap-2">
      <span
        aria-hidden="true"
        className={cn(
          "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
          done ? "bg-success" : "bg-border",
        )}
      />
      <span className="min-w-0">
        <span className="font-medium text-foreground">{label}</span>{" "}
        <span className="text-muted-foreground">— {detail}</span>
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
    <WorkbenchCard
      title="Co zrobi system po „Zatrudniony”"
      status="hook `hired` · jak dziś"
    >
      <p className="text-xs text-muted-foreground">
        Ruch na etap terminalny „Zatrudniony” wymaga jawnego potwierdzenia
        i uruchamia poniższe skutki. Zbiorczego zatrudniania nie ma — kartę
        przeciąga się pojedynczo.
      </p>
      <div>
        <ReqRow
          tone="y"
          label="Szkic kontraktu (osoba × klient) — stawki, daty i tryb pracy do uzupełnienia"
          tag="contracts"
        />
        <ReqRow
          tone="y"
          label="Szkic zamówienia — pomijany z podanym powodem przy żywej linii grupy MD albo kliencie kosztowym"
          tag="client_orders"
        />
        <ReqRow
          tone={clientId != null ? "y" : "w"}
          label={
            clientId != null
              ? "Powiadomienie do Delivery Leadów klienta: „Nowy draft kontraktu + zamówienia”"
              : "Powiadomienie do Delivery Leadów — wymaga klienta przypisanego do rekrutacji"
          }
          tag="notyfikacja"
        />
        <ReqRow
          tone={hiredCount > 0 ? "w" : "n"}
          label={
            hiredCount > 0
              ? `Zatrudnionych: ${countPl(hiredCount, "osoba", "osoby", "osób")} — przy komplecie obsady system podpowiada „Obsadzone przez nas”`
              : "Przy komplecie obsady system podpowiada powód „Obsadzone przez nas”"
          }
          tag="suggest_next_step"
        />
      </div>
    </WorkbenchCard>
  );
}

// ── Bramka aktywacji kontraktu ──────────────────────────────────────────────

function ActivationGateCard({ contractId }: { contractId: number | null }) {
  return (
    <WorkbenchCard
      title="Czego wymaga aktywacja kontraktu"
      status={contractId != null ? undefined : "bramka, nie policzone braki"}
    >
      <p className="text-xs text-muted-foreground">
        Szkic przechodzi na „Aktywny” dopiero z kompletem tych pól. Backend
        odbija brak 409 z ich listą — tu jest ta sama lista, żeby nikt jej nie
        szukał po komunikacie błędu.
      </p>
      <div className="space-y-1.5">
        {ACTIVATION_REQUIRED_FIELDS.map((field) => (
          <ReadyItem
            key={field}
            // `z`, nie `y`: nie wiemy, czy pole JEST wypełnione (wiersz
            // kontraktu stoi za bramką Delivery). Zielony haczyk obiecywałby
            // wiedzę, której ta zakładka nie ma.
            tone="z"
            title={CONTRACT_FIELD_LABELS[field] ?? field}
            detail="wymagane do przejścia na „Aktywny”"
          />
        ))}
        <ReadyItem
          tone="z"
          title={CONTRACT_FIELD_LABELS.end_date ?? "end_date"}
          detail="niewymagana — umowa bezterminowa jest stanem docelowym, a nie brakiem danych"
        />
      </div>
      {contractId != null ? (
        <ModuleLink
          href={`/contracts/${contractId}`}
          label="Sprawdź braki na kontrakcie"
          variant="button"
        />
      ) : (
        <p className="text-[11px] text-muted-foreground">
          Lista braków POLICZONA dla konkretnego kontraktu żyje w module
          Kontrakty — pojawi się tu jako link, gdy umowa zostanie powiązana
          z kontraktem.
        </p>
      )}
    </WorkbenchCard>
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
          ? "inline-flex h-8 w-fit items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
          : "inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
      <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
    </Link>
  );
}
