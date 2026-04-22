"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Briefcase, Users, FileText, XCircle, UserPlus, Trash2 } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  ActiveConsultantItem,
  ClientProfileResponse,
  OpenJobItem,
} from "@/types/client-profile";
import { SummaryBar } from "@/components/client-profile/SummaryBar";
import { JobRow } from "@/components/client-profile/JobRow";
import { ConsultantRow } from "@/components/client-profile/ConsultantRow";
import { PlacementRow } from "@/components/client-profile/PlacementRow";
import { LostJobRow } from "@/components/client-profile/LostJobRow";
import { CloseJobAsLostModal } from "@/components/client-profile/actions/CloseJobAsLostModal";
import { TerminateContractModal } from "@/components/client-profile/actions/TerminateContractModal";
import { ExtendContractMenu } from "@/components/client-profile/actions/ExtendContractMenu";
import { AddCandidateToJobModal } from "@/components/client-profile/actions/AddCandidateToJobModal";
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
  const [addCandidateTo, setAddCandidateTo] = useState<OpenJobItem | null>(null);
  const [closeJobAsLost, setCloseJobAsLost] = useState<OpenJobItem | null>(null);
  const [terminateContract, setTerminateContract] = useState<ActiveConsultantItem | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-gray-400">
        <div className="w-5 h-5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin mr-2" />
        Ładowanie profilu...
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="text-center py-12 text-red-500 text-sm">
        Nie udało się wczytać profilu klienta.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SummaryBar summary={data.summary} />

      <OpenJobsSection
        items={data.open_jobs}
        onAddCandidate={setAddCandidateTo}
        onCloseAsLost={setCloseJobAsLost}
      />
      <ActiveConsultantsSection
        items={data.active_consultants}
        clientId={clientId}
        onTerminate={setTerminateContract}
      />
      <HistorySection
        placements={data.historical.placements}
        lostJobs={data.historical.lost_jobs}
      />

      {addCandidateTo && (
        <AddCandidateToJobModal
          jobId={addCandidateTo.id}
          jobTitle={addCandidateTo.title}
          clientId={clientId}
          onClose={() => setAddCandidateTo(null)}
        />
      )}
      {closeJobAsLost && (
        <CloseJobAsLostModal
          jobId={closeJobAsLost.id}
          jobTitle={closeJobAsLost.title}
          clientId={clientId}
          onClose={() => setCloseJobAsLost(null)}
        />
      )}
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

// ── Otwarte rekrutacje ────────────────────────────────────────────────────────

function OpenJobsSection({
  items,
  onAddCandidate,
  onCloseAsLost,
}: {
  items: ClientProfileResponse["open_jobs"];
  onAddCandidate: (job: OpenJobItem) => void;
  onCloseAsLost: (job: OpenJobItem) => void;
}) {
  return (
    <section className="space-y-3">
      <SectionHeader
        icon={<Briefcase className="w-4 h-4 text-purple-600" />}
        title="Otwarte rekrutacje"
        count={items.length}
      />
      {items.length === 0 ? (
        <EmptyState icon={<Briefcase className="w-8 h-8" />}>
          Brak aktywnych rekrutacji dla tego klienta.
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {items.map((job) => (
            <JobRow
              key={job.id}
              job={job}
              actions={
                <>
                  <button
                    onClick={() => onAddCandidate(job)}
                    title="Dodaj kandydata do pipeline"
                    className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/30 hover:bg-purple-100 dark:hover:bg-purple-900/50 rounded-md transition-colors"
                  >
                    <UserPlus className="w-3 h-3" />
                    Dodaj
                  </button>
                  <button
                    onClick={() => onCloseAsLost(job)}
                    title="Zamknij jako przegraną"
                    className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-red-600 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-md transition-colors"
                  >
                    <XCircle className="w-3 h-3" />
                    Lost
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

// ── Obecni konsultanci ────────────────────────────────────────────────────────

function ActiveConsultantsSection({
  items,
  clientId,
  onTerminate,
}: {
  items: ClientProfileResponse["active_consultants"];
  clientId: number;
  onTerminate: (c: ActiveConsultantItem) => void;
}) {
  return (
    <section className="space-y-3">
      <SectionHeader
        icon={<Users className="w-4 h-4 text-emerald-600" />}
        title="Obecni konsultanci"
        count={items.length}
      />
      {items.length === 0 ? (
        <EmptyState icon={<Users className="w-8 h-8" />}>
          Nie mamy aktywnych konsultantów u tego klienta.
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {items.map((c) => (
            <ConsultantRow
              key={c.contract_id}
              consultant={c}
              actions={
                <>
                  <ExtendContractMenu contractId={c.contract_id} clientId={clientId} />
                  <button
                    onClick={() => onTerminate(c)}
                    title="Zakończ kontrakt"
                    className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-red-600 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-md transition-colors"
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
        icon={<FileText className="w-4 h-4 text-gray-500" />}
        title="Historia"
        count={total}
      />

      <div className="flex gap-2 border-b border-gray-200 dark:border-gray-700">
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
        <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
          {title}
        </h3>
        <span className="text-xs px-2 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded-full font-semibold">
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
    <div className="flex flex-col items-center justify-center py-10 text-gray-400 dark:text-gray-500">
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
          : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
      )}
    >
      {icon}
      {children}
    </button>
  );
}
