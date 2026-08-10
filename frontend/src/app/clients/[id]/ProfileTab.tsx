"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users, FileText, XCircle } from "lucide-react";
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
import { ConsultantRow } from "@/components/client-profile/ConsultantRow";
import { PlacementRow } from "@/components/client-profile/PlacementRow";
import { LostJobRow } from "@/components/client-profile/LostJobRow";
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

  // Akcje rekrutacji (Dodaj/Lost) mieszkają w zakładce Projekty — sekcja
  // „Otwarte rekrutacje" usunięta (ticket #3). Zakończenie projektu (ticket
  // #5) odbywa się w Zamówieniach lub Kontraktach — Profil jest wyłącznie
  // odbiorcą danych (Obecni/Archiwum to read-modele).

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
      <LostJobsSection lostJobs={data.historical.lost_jobs} />
    </div>
  );
}

// ── Konsultanci: Obecni | Archiwum ───────────────────────────────────────────
// Sekcja „Otwarte rekrutacje" (lista) usunięta dla wszystkich klientów
// (ticket #3) — akcje Dodaj/Lost przeniesione do zakładki Projekty, kafelek
// metryki „Otwarte rekrutacje" w SummaryBar zostaje bez zmian.
// Ticket #5: Obecni BEZ akcji „Zakończ" (zakończenie w Zamówieniach lub
// Kontraktach); Archiwum = wyłącznie odbiorca danych — konsultant trafia tu
// automatycznie po zakończeniu projektu (read-model z zakończonych kontraktów).

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

  return (
    <section className="space-y-3">
      <SectionHeader
        icon={<Users className="w-4 h-4 text-emerald-600" />}
        title="Konsultanci"
        count={active.length + archived.length}
      />

      <div className="flex gap-2 border-b border-border dark:border-border">
        <SubTabButton
          active={tab === "obecni"}
          onClick={() => setTab("obecni")}
          icon={<Users className="w-3.5 h-3.5" />}
        >
          {/* Aktywny filtr części zawęża licznik do tego, co realnie widać —
              stały total przy filtrze czytał się jak błąd (review #1056). */}
          Obecni konsultanci (
          {ezdrowie && partFilter !== "all" ? filtered.length : active.length})
        </SubTabButton>
        <SubTabButton
          active={tab === "archiwum"}
          onClick={() => setTab("archiwum")}
          icon={<FileText className="w-3.5 h-3.5" />}
        >
          Archiwum konsultantów ({archived.length})
        </SubTabButton>
      </div>

      {tab === "obecni" ? (
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
            <div className="space-y-2">
              {filtered.map((c) => (
                <ConsultantRow
                  key={c.contract_id}
                  consultant={c}
                  actions={
                    <ExtendContractMenu
                      contractId={c.contract_id}
                      clientId={clientId}
                    />
                  }
                />
              ))}
            </div>
          )}
        </>
      ) : archived.length === 0 ? (
        <EmptyState icon={<FileText className="w-8 h-8" />}>
          Brak zakończonych kontraktów dla tego klienta.
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {archived.map((p) => (
            <PlacementRow
              key={p.contract_id}
              placement={p}
              actions={<ReEngageButton placement={p} />}
            />
          ))}
        </div>
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

// ── Przegrane rekrutacje ─────────────────────────────────────────────────────
// Dawna sekcja „Historia" miała dwie zakładki: Placementy (teraz „Archiwum
// konsultantów" obok Obecnych — ticket #5 krok 2) i Przegrane (zostają tutaj).

function LostJobsSection({
  lostJobs,
}: {
  lostJobs: ClientProfileResponse["historical"]["lost_jobs"];
}) {
  return (
    <section className="space-y-3">
      <SectionHeader
        icon={<XCircle className="w-4 h-4 text-muted-foreground" />}
        title="Przegrane rekrutacje"
        count={lostJobs.length}
      />
      {lostJobs.length === 0 ? (
        <EmptyState icon={<XCircle className="w-8 h-8" />}>
          Świetnie — żadna rekrutacja u tego klienta nie została przegrana.
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {lostJobs.map((j) => (
            <LostJobRow key={j.job_id} lost={j} />
          ))}
        </div>
      )}
    </section>
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

function SubTabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border-b-2 transition-colors",
        active
          ? "border-purple-600 text-purple-600"
          : "border-transparent text-muted-foreground hover:text-foreground dark:text-muted-foreground dark:hover:text-muted-foreground"
      )}
    >
      {icon}
      {children}
    </button>
  );
}
