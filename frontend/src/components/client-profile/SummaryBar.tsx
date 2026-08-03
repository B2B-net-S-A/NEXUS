"use client";

import { Briefcase, Users, DollarSign } from "lucide-react";
import { StatsCard } from "@/components/StatsCard";
import type { ClientProfileSummary } from "@/types/client-profile";
import { formatPLN } from "@/types/client-profile";

interface Props {
  summary: ClientProfileSummary;
}

export function SummaryBar({ summary }: Props) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <StatsCard
        title="Otwarte rekrutacje"
        value={summary.open_jobs}
        color="purple"
        icon={<Briefcase className="w-4 h-4" />}
      />
      <StatsCard
        title="Aktywni konsultanci"
        value={summary.active_consultants}
        color="green"
        icon={<Users className="w-4 h-4" />}
      />
      <StatsCard
        title="Aktywne MRR"
        value={formatPLN(summary.active_mrr)}
        subtitle="miesięczna marża"
        color="orange"
        icon={<DollarSign className="w-4 h-4" />}
      />
    </div>
  );
}
