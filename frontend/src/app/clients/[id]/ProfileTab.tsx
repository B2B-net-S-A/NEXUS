"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users, FileText } from "lucide-react";
import api from "@/lib/api";
import {
  filterConsultantsByPart,
  isEzdrowieClient,
  PROJECT_PARTS,
  type ProjectPart,
} from "@/lib/ezdrowie";
import { cn } from "@/lib/utils";
import type { ClientProfileResponse } from "@/types/client-profile";
import { SummaryBar } from "@/components/client-profile/SummaryBar";
import {
  ConsultantsTable,
  toConsultantRow,
} from "@/components/client-profile/ConsultantsTable";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { ExtendContractMenu } from "@/components/client-profile/actions/ExtendContractMenu";
import { ReEngageButton } from "@/components/client-profile/actions/ReEngageButton";

interface Props {
  clientId: number;
}

export function ProfileTab({ clientId }: Props) {
  const { data, isLoading, isError } = useQuery<ClientProfileResponse>({
    queryKey: ["client-profile", clientId],
    queryFn: () =>
      api.get(`/api/clients/${clientId}/profile`).then((r) => r.data),
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

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <div className="w-5 h-5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin mr-2" />
        Ładowanie profilu...
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="text-center py-12 text-destructive text-sm">
        Nie udało się wczytać profilu klienta.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SummaryBar summary={data.summary} />

      <ConsultantsSection
        active={data.active_consultants}
        archived={data.historical.placements}
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

type ConsultantsTab = "obecni" | "archiwum";

function ConsultantsSection({
  active,
  archived,
  clientId,
}: {
  active: ClientProfileResponse["active_consultants"];
  archived: ClientProfileResponse["historical"]["placements"];
  clientId: number;
}) {
  const [tab, setTab] = useState<ConsultantsTab>("obecni");
  // Filtr „części umowy" — widoczny wyłącznie dla Centrum e-Zdrowia
  // (ticket #3; bramka po client_id). Domyślnie pełna lista.
  const ezdrowie = isEzdrowieClient(clientId);
  const [partFilter, setPartFilter] = useState<ProjectPart | "all">("all");
  const filtered = ezdrowie
    ? filterConsultantsByPart(active, partFilter)
    : active;

  const isArchive = tab === "archiwum";
  const activeCount =
    ezdrowie && partFilter !== "all" ? filtered.length : active.length;

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
            value: "archiwum",
            label: "Archiwum konsultantów",
            icon: FileText,
            count: archived.length,
          },
        ]}
      />

      <SectionHeader
        icon={
          isArchive ? (
            <FileText className="w-4 h-4 text-emerald-600" />
          ) : (
            <Users className="w-4 h-4 text-emerald-600" />
          )
        }
        title={isArchive ? "Archiwum konsultantów" : "Obecni konsultanci"}
        count={isArchive ? archived.length : activeCount}
      />
      <p className="text-xs text-muted-foreground">
        Widok informacyjny. Zakończenie projektu odbywa się w Zamówieniach lub
        Kontraktach.
      </p>

      {!isArchive ? (
        <>
          {ezdrowie && active.length > 0 && (
            <div
              className="flex flex-wrap gap-2"
              role="group"
              aria-label="Filtr części umowy"
            >
              <PartFilterPill
                active={partFilter === "all"}
                onClick={() => setPartFilter("all")}
              >
                Wszystkie części
              </PartFilterPill>
              {PROJECT_PARTS.map((p) => (
                <PartFilterPill
                  key={p.value}
                  active={partFilter === p.value}
                  onClick={() => setPartFilter(p.value)}
                >
                  {p.label}
                </PartFilterPill>
              ))}
            </div>
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
            return placement ? <ReEngageButton placement={placement} /> : null;
          }}
        />
      )}
    </section>
  );
}

function PartFilterPill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "px-3 py-1 text-xs font-medium rounded-full border transition-colors",
        active
          ? "bg-purple-50 dark:bg-purple-900/30 border-purple-300 text-purple-700 dark:text-purple-300"
          : "border-border text-muted-foreground hover:text-foreground hover:border-purple-200",
      )}
    >
      {children}
    </button>
  );
}

// ── Mini helpers ──────────────────────────────────────────────────────────────

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
