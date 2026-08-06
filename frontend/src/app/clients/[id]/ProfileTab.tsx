"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users, FileText, XCircle, Trash2 } from "lucide-react";
import api from "@/lib/api";
import {
  filterConsultantsByPart,
  isEzdrowieClient,
  PROJECT_PARTS,
  type ProjectPart,
} from "@/lib/ezdrowie";
import { cn } from "@/lib/utils";
import type {
  ActiveConsultantItem,
  ClientProfileResponse,
} from "@/types/client-profile";
import { SummaryBar } from "@/components/client-profile/SummaryBar";
import { ConsultantRow } from "@/components/client-profile/ConsultantRow";
import { PlacementRow } from "@/components/client-profile/PlacementRow";
import { LostJobRow } from "@/components/client-profile/LostJobRow";
import { TerminateContractModal } from "@/components/client-profile/actions/TerminateContractModal";
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

  // Modal state — a single in-flight action at a time. Keeping each modal's
  // trigger data colocated here avoids drilling setState through every Row.
  // Akcje rekrutacji (Dodaj/Lost) mieszkają teraz w zakładce Projekty —
  // sekcja „Otwarte rekrutacje" została usunięta (ticket #3), kafelek
  // metryki w SummaryBar zostaje.
  const [terminateContract, setTerminateContract] = useState<ActiveConsultantItem | null>(null);

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

      <ActiveConsultantsSection
        items={data.active_consultants}
        clientId={clientId}
        onTerminate={setTerminateContract}
      />
      <HistorySection
        placements={data.historical.placements}
        lostJobs={data.historical.lost_jobs}
      />

      {terminateContract && (
        <TerminateContractModal
          contractId={terminateContract.contract_id}
          candidateName={terminateContract.candidate.name}
          clientId={clientId}
          onClose={() => setTerminateContract(null)}
        />
      )}
    </div>
  );
}

// ── Obecni konsultanci ────────────────────────────────────────────────────────
// Sekcja „Otwarte rekrutacje" (lista) usunięta dla wszystkich klientów
// (ticket #3) — akcje Dodaj/Lost przeniesione do zakładki Projekty, kafelek
// metryki „Otwarte rekrutacje" w SummaryBar zostaje bez zmian.

function ActiveConsultantsSection({
  items,
  clientId,
  onTerminate,
}: {
  items: ClientProfileResponse["active_consultants"];
  clientId: number;
  onTerminate: (c: ActiveConsultantItem) => void;
}) {
  // Filtr „części umowy" — widoczny wyłącznie dla Centrum e-Zdrowia
  // (ticket #3; bramka po client_id). Domyślnie pełna lista.
  const ezdrowie = isEzdrowieClient(clientId);
  const [partFilter, setPartFilter] = useState<ProjectPart | "all">("all");
  const filtered = ezdrowie ? filterConsultantsByPart(items, partFilter) : items;

  return (
    <section className="space-y-3">
      <SectionHeader
        icon={<Users className="w-4 h-4 text-emerald-600" />}
        title="Obecni konsultanci"
        count={items.length}
      />
      {ezdrowie && items.length > 0 && (
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
      {items.length === 0 ? (
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
                <>
                  <ExtendContractMenu contractId={c.contract_id} clientId={clientId} />
                  <button
                    onClick={() => onTerminate(c)}
                    title="Zakończ kontrakt"
                    className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-destructive dark:text-red-300 hover:bg-destructive/10 dark:hover:bg-red-900/30 rounded-md transition-colors"
                  >
                    <Trash2 className="w-3 h-3" />
                    Zakończ
                  </button>
                </>
              }
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

// ── Historia ──────────────────────────────────────────────────────────────────

type HistoryTab = "placements" | "lost";

function HistorySection({
  placements,
  lostJobs,
}: {
  placements: ClientProfileResponse["historical"]["placements"];
  lostJobs: ClientProfileResponse["historical"]["lost_jobs"];
}) {
  const [tab, setTab] = useState<HistoryTab>("placements");
  const total = placements.length + lostJobs.length;

  return (
    <section className="space-y-3">
      <SectionHeader
        icon={<FileText className="w-4 h-4 text-muted-foreground" />}
        title="Historia"
        count={total}
      />

      <div className="flex gap-2 border-b border-border dark:border-border">
        <SubTabButton
          active={tab === "placements"}
          onClick={() => setTab("placements")}
          icon={<FileText className="w-3.5 h-3.5" />}
        >
          Placementy ({placements.length})
        </SubTabButton>
        <SubTabButton
          active={tab === "lost"}
          onClick={() => setTab("lost")}
          icon={<XCircle className="w-3.5 h-3.5" />}
        >
          Przegrane ({lostJobs.length})
        </SubTabButton>
      </div>

      {tab === "placements" ? (
        placements.length === 0 ? (
          <EmptyState icon={<FileText className="w-8 h-8" />}>
            Brak zakończonych kontraktów dla tego klienta.
          </EmptyState>
        ) : (
          <div className="space-y-2">
            {placements.map((p) => (
              <PlacementRow
                key={p.contract_id}
                placement={p}
                actions={<ReEngageButton placement={p} />}
              />
            ))}
          </div>
        )
      ) : lostJobs.length === 0 ? (
        <EmptyState icon={<XCircle className="w-8 h-8" />}>
          Świetnie — żadna oferta u tego klienta nie została przegrana.
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
