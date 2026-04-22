"use client";

import { Briefcase, Users, Trophy, DollarSign, Clock } from "lucide-react";
import { StatsCard } from "@/components/StatsCard";
import type { ClientProfileSummary } from "@/types/client-profile";
import { formatPLN } from "@/types/client-profile";

interface Props {
  summary: ClientProfileSummary;
}

export function SummaryBar({ summary }: Props) {
  const avgFill = summary.avg_time_to_fill_days;
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
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
        title="Wstawienia łącznie"
        value={summary.total_placements}
        subtitle="aktywne + historyczne"
        color="teal"
        icon={<Trophy className="w-4 h-4" />}
      />
      <StatsCard
        title="Aktywne MRR"
        value={formatPLN(summary.active_mrr)}
        subtitle="miesięczna marża"
        color="orange"
        icon={<DollarSign className="w-4 h-4" />}
      />
      <StatsCard
        title={avgFill != null ? "Śr. czas obsadzenia" : "LTV klienta"}
        value={
          avgFill != null
            ? `${avgFill.toFixed(0)} dni`
            : formatPLN(summary.ltv)
        }
        subtitle={
          avgFill != null
            ? `LTV: ${formatPLN(summary.ltv)}`
            : "łączny przychód"
        }
        color="blue"
        icon={<Clock className="w-4 h-4" />}
      />
    </div>
  );
}
