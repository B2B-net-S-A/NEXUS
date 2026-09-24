"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users, FileText, CalendarClock } from "lucide-react";
import api from "@/lib/api";
import {
  filterConsultantsByExecutiveContract,
  isEzdrowieClient,
  type ConsultantAssignmentFilter,
} from "@/lib/ezdrowie";
import type { ClientProfileResponse } from "@/types/client-profile";
import { SummaryBar } from "@/components/client-profile/SummaryBar";
import {
  ConsultantsTable,
  toConsultantRow,
} from "@/components/client-profile/ConsultantsTable";
import { ContractStructureSection } from "@/components/client-profile/ContractStructureSection";
import { ExecutiveContractFilter } from "@/components/client-profile/ExecutiveContractFilter";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { ExtendContractMenu } from "@/components/client-profile/actions/ExtendContractMenu";
import { ReEngageButton } from "@/components/client-profile/actions/ReEngageButton";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { countPl } from "@/lib/plural-pl";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";

interface Props {
  clientId: number;
}

export function ProfileTab({ clientId }: Props) {
  const query = useQuery<ClientProfileResponse>({
    queryKey: ["client-profile", clientId],
    queryFn: () =>
      api.get(`/api/clients/${clientId}/profile`).then((r) => r.data),
  });
  const { data } = query;
  // 403 ≠ awaria ≠ pusty profil — i awaria ma „Spróbuj ponownie” (audyt S10).
  const viewState = resolveViewState({
    isLoading: query.isPending,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });

  // Profil NIE pokazuje rekrutacji w żadnej formie — ani list („Otwarte",
  // „Przegrane"), ani liczników. Wszystkie rekrutacje klienta żyją w zakładce
  // Projekty, w dwóch kubełkach: aktywne i zamknięte. Profil jest wyłącznie
  // odbiorcą danych o KONSULTANTACH (Obecni/Archiwum to read-modele), a
  // zakończenie projektu odbywa się w Zamówieniach lub Kontraktach.
  //
  // UWAGA przy przywracaniu czegokolwiek tutaj: powód i notatka przegranej
  // (`close_reason`/`close_notes`) po usunięciu sekcji „Przegrane rekrutacje"
  // NIE MAJĄ w aplikacji żadnego widoku, mimo że rekruter dalej je wpisuje
  // przez „Lost" w Projektach. To znany, świadomie odłożony brak.

  if (viewState === "loading") {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <div className="w-5 h-5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin mr-2" />
        Ładowanie profilu...
      </div>
    );
  }

  if (isBlockingViewState(viewState) || !data) {
    return (
      <QueryStateNotice
        state={
          isBlockingViewState(viewState)
            ? (viewState as "forbidden" | "not_found" | "error")
            : "error"
        }
        description={
          viewState === "error" ? "Nie udało się wczytać profilu klienta." : undefined
        }
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <SummaryBar summary={data.summary} />

      {/* Centrum e-Zdrowia: struktura umów (ramowa → wykonawcze) NAD listą
          konsultantów — filtr i badge w tabeli czytają umowy stąd. */}
      {isEzdrowieClient(clientId) ? (
        <ContractStructureSection clientId={clientId} />
      ) : null}

      <ConsultantsSection
        active={data.active_consultants}
        planned={data.planned_consultants ?? []}
        archived={data.historical.placements}
        archivedTotal={data.historical.placements_total}
        activePeople={data.summary.active_consultants}
        clientId={clientId}
      />
    </div>
  );
}

// ── Konsultanci: Obecni | Archiwum ───────────────────────────────────────────
// To sekcja o KONSULTANTACH (kontrakty), nie o rekrutacjach — dlatego zostaje
// w Profilu, mimo że listy i liczniki rekrutacji zostały z niego zdjęte.
// Obecni BEZ akcji „Zakończ" (zakończenie w Zamówieniach lub Kontraktach);
// Archiwum = wyłącznie odbiorca danych — konsultant trafia tu automatycznie
// po zakończeniu projektu (read-model z zakończonych kontraktów).

// Planowani = kontrakt aktywny statusem, ale jeszcze nieobowiązujący: data
// startu umowy w przyszłości, a przy jej braku — start bieżącego zamówienia
// w przyszłości (brak jakiejkolwiek daty = obecny, audyt 18.09.2026). Osobna zakładka, bo do 09.2026 tacy konsultanci
// siedzieli w „Obecnych" i zawyżali „Aktywne MRR" o marżę, której nikt jeszcze
// nie zarabia (UAT B46); ukrycie ich w ogóle czytałoby się jak utrata danych.

type ConsultantsTab = "obecni" | "planowani" | "archiwum";

function ConsultantsSection({
  active,
  planned,
  archived,
  archivedTotal,
  activePeople,
  clientId,
}: {
  active: ClientProfileResponse["active_consultants"];
  planned: ClientProfileResponse["planned_consultants"];
  archived: ClientProfileResponse["historical"]["placements"];
  /** Wszystkie zakończone kontrakty — `archived` jest przycięte (audyt S7). */
  archivedTotal?: number;
  /** Osoby na obecnych kontraktach (kafel „Aktywni konsultanci”). */
  activePeople: number;
  clientId: number;
}) {
  const [tab, setTab] = useState<ConsultantsTab>("obecni");
  // Filtr po UMOWIE WYKONAWCZEJ — widoczny wyłącznie dla Centrum e-Zdrowia
  // (bramka po client_id). Domyślnie pełna lista; „Nieprzypisani" = osoby
  // sprzed struktury umów, do przeglądu w sekcji wyżej.
  const ezdrowie = isEzdrowieClient(clientId);
  const [assignmentFilter, setAssignmentFilter] =
    useState<ConsultantAssignmentFilter>("all");
  const filtered = ezdrowie
    ? filterConsultantsByExecutiveContract(active, assignmentFilter)
    : active;

  const isArchive = tab === "archiwum";
  const isPlanned = tab === "planowani";
  const activeCount =
    ezdrowie && assignmentFilter !== "all" ? filtered.length : active.length;
  const archiveCount = Math.max(archivedTotal ?? 0, archived.length);

  return (
    <section className="space-y-3">
      {/* Podzakładki na `ds/TabbedNav` — jak w sąsiedniej zakładce Projekty.
          Poprzedni, ręcznie zrobiony przełącznik nie miał `role="tab"` ani
          `aria-selected`, więc czytnik ekranu widział dwa zwykłe przyciski. */}
      <TabbedNav
        value={tab}
        onValueChange={(v) => setTab(v as ConsultantsTab)}
        ariaLabel="Konsultanci"
        tabs={[
          {
            value: "obecni",
            label: "Obecni konsultanci",
            icon: Users,
            // Aktywny filtr części zawęża licznik do tego, co realnie widać —
            // stały total przy filtrze czytał się jak błąd (review #1056).
            count: activeCount,
          },
          {
            value: "planowani",
            label: "Planowani konsultanci",
            icon: CalendarClock,
            count: planned.length,
          },
          {
            value: "archiwum",
            label: "Archiwum konsultantów",
            icon: FileText,
            count: archiveCount,
          },
        ]}
      />

      <SectionHeader
        icon={
          isArchive ? (
            <FileText className="w-4 h-4 text-emerald-600" />
          ) : isPlanned ? (
            <CalendarClock className="w-4 h-4 text-emerald-600" />
          ) : (
            <Users className="w-4 h-4 text-emerald-600" />
          )
        }
        title={
          isArchive
            ? "Archiwum konsultantów"
            : isPlanned
              ? "Planowani konsultanci"
              : "Obecni konsultanci"
        }
        count={isArchive ? archiveCount : isPlanned ? planned.length : activeCount}
      />
      <p className="text-xs text-muted-foreground">
        {isPlanned
          ? "Kontrakty, które jeszcze nie wystartowały (data startu umowy — a gdy jej brak, bieżącego zamówienia — jest w przyszłości). Nie wchodzą do „Obecnych” ani do „Aktywnego MRR”."
          : "Widok informacyjny. Zakończenie projektu odbywa się w Zamówieniach lub Kontraktach."}
      </p>
      {/* Liczniki zakładek liczą KONTRAKTY (wiersz tabeli), kafel nad nimi —
          OSOBY. Gdy się różnią, mówimy dlaczego (audyt N1). */}
      {!isArchive && !isPlanned && activePeople !== active.length ? (
        <p className="text-xs text-muted-foreground">
          {countPl(active.length, "kontrakt", "kontrakty", "kontraktów")} ·{" "}
          {countPl(activePeople, "osoba", "osoby", "osób")} — jedna osoba może
          mieć kilka kontraktów; wiersz tabeli to kontrakt.
        </p>
      ) : null}
      {isArchive && archiveCount > archived.length ? (
        <p className="text-xs text-muted-foreground">
          Pokazano {archived.length} najnowszych z {archiveCount} zakończonych
          kontraktów. Pełną historię znajdziesz w module Kontrakty.
        </p>
      ) : null}

      {isPlanned ? (
        planned.length === 0 ? (
          <EmptyState icon={<CalendarClock className="w-8 h-8" />}>
            Brak zaplanowanych kontraktów u tego klienta.
          </EmptyState>
        ) : (
          <ConsultantsTable
            rows={planned.map(toConsultantRow)}
            renderActions={(r) => (
              <ExtendContractMenu
                contractId={r.contract_id}
                clientId={clientId}
                contractStatus={statusOf(planned, r.contract_id)}
              />
            )}
          />
        )
      ) : !isArchive ? (
        <>
          {ezdrowie && active.length > 0 && (
            <ExecutiveContractFilter
              clientId={clientId}
              consultants={active}
              value={assignmentFilter}
              onChange={setAssignmentFilter}
            />
          )}
          {active.length === 0 ? (
            <EmptyState icon={<Users className="w-8 h-8" />}>
              Nie mamy aktywnych konsultantów u tego klienta.
            </EmptyState>
          ) : filtered.length === 0 ? (
            <EmptyState icon={<Users className="w-8 h-8" />}>
              Brak konsultantów spełniających wybrane kryteria.
            </EmptyState>
          ) : (
            <ConsultantsTable
              rows={filtered.map(toConsultantRow)}
              renderActions={(r) => (
                <ExtendContractMenu
                  contractId={r.contract_id}
                  clientId={clientId}
                  contractStatus={statusOf(active, r.contract_id)}
                />
              )}
            />
          )}
        </>
      ) : archived.length === 0 ? (
        <EmptyState icon={<FileText className="w-8 h-8" />}>
          Brak zakończonych kontraktów dla tego klienta.
        </EmptyState>
      ) : (
        <ConsultantsTable
          rows={archived.map(toConsultantRow)}
          showEndDate
          renderActions={(r) => {
            // ReEngage tworzy NOWY kontrakt, nie edytuje wiersza archiwalnego —
            // „nic się tu nie edytuje ręcznie" mówi o tym, że konsultant trafia
            // tu automatycznie, nie o odbieraniu akcji.
            const placement = archived.find(
              (p) => p.contract_id === r.contract_id,
            );
            // Kandydat usunięty (RODO) — nie ma kogo zapraszać.
            return placement && placement.candidate.id != null ? (
              <ReEngageButton placement={placement} />
            ) : null;
          }}
        />
      )}
    </section>
  );
}

// ── Mini helpers ──────────────────────────────────────────────────────────────

function statusOf(
  rows: ClientProfileResponse["active_consultants"],
  contractId: number,
): string | null {
  return rows.find((row) => row.contract_id === contractId)?.contract_status ?? null;
}

function SectionHeader({
  icon,
  title,
  count,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        {icon}
        <h3 className="text-sm font-semibold text-foreground dark:text-muted-foreground">
          {title}
        </h3>
        <span className="text-xs px-2 py-0.5 bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground rounded-full font-semibold">
          {count}
        </span>
      </div>
      {action}
    </div>
  );
}

function EmptyState({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-muted-foreground dark:text-muted-foreground">
      <div className="opacity-40 mb-2">{icon}</div>
      <p className="text-sm">{children}</p>
    </div>
  );
}
