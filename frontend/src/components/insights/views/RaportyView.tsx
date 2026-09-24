"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { buildDlPortfolioCsvExport } from "@/lib/insights-csv";
import {
  REPORT_GROUPS,
  reportById,
  reportHref,
  visibleReports,
  type ReportDef,
  type ReportId,
} from "@/lib/insights-reports";
import { hasRole, useAuthStore } from "@/store/auth";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import { CompetenceMatrix } from "@/components/insights/sections/CompetenceMatrix";
import { InsightsBoardYoY } from "@/components/insights/sections/InsightsBoardYoY";
import { InsightsClientsRanking } from "@/components/insights/sections/InsightsClientsRanking";
import {
  DlPortfolioTiles,
  InsightsDlPortfolio,
} from "@/components/insights/sections/InsightsDlPortfolio";
import { InsightsHallOfFame } from "@/components/insights/sections/InsightsHallOfFame";
import { InsightsIntegrations } from "@/components/insights/sections/InsightsIntegrations";
import { InsightsInviteLinks } from "@/components/insights/sections/InsightsInviteLinks";
import { InsightsPlacementAnalysis } from "@/components/insights/sections/InsightsPlacementAnalysis";
import { InsightsTeamActivity } from "@/components/insights/sections/InsightsTeamActivity";
import { InsightsTeamPerformance } from "@/components/insights/sections/InsightsTeamPerformance";
import { InsightsTimeToHire } from "@/components/insights/sections/InsightsTimeToHire";
import { InsightsYearlyStats } from "@/components/insights/sections/InsightsYearlyStats";
import { RecruitmentConversions } from "@/components/insights/sections/RecruitmentConversions";
import { SeniorityBoard } from "@/components/insights/sections/SeniorityBoard";
import { SourcesFunnelSection } from "@/components/insights/sections/SourcesFunnelSection";
import { PrepQualitySection } from "@/components/insights/chapters/PrepQualitySection";
import { StageBreakdownSection } from "@/components/insights/chapters/StageBreakdownSection";
import { AllocationWorkloadBoard } from "@/components/v2/priority-work/AllocationWorkloadBoard";
import { StaleJobsReport } from "./StaleJobsReport";
import { ViewHeader } from "./ViewKit";

/**
 * Raporty — biblioteka wszystkiego, czego nie ma na widokach. Lista kart
 * pogrupowanych tematycznie; `?report=<id>` otwiera jeden raport na całą
 * stronę z pytaniem w nagłówku.
 */
export function RaportyView({ reportId }: { reportId: ReportId | null }) {
  const user = useAuthStore((state) => state.user);
  if (reportId) return <ReportPage def={reportById(reportId)} />;

  const reports = visibleReports(user);
  return (
    <div className="space-y-6">
      <ViewHeader
        question="Raporty"
        lede="Wszystko, czego nie ma na widokach. Każdy raport otwiera się na całą stronę — z pytaniem, na które odpowiada."
      />
      <div className="divide-y divide-border rounded-xl border border-border bg-card">
        {REPORT_GROUPS.map((group) => {
          const items = reports.filter((r) => r.group === group);
          if (items.length === 0) return null;
          return (
            <section
              key={group}
              className="grid grid-cols-1 gap-3 p-4 md:grid-cols-[11rem_minmax(0,1fr)] md:gap-6 md:p-5"
            >
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {group}
              </h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {items.map((report) => (
                  <ReportCard key={report.id} report={report} />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

function ReportCard({ report }: { report: ReportDef }) {
  return (
    <Link
      href={reportHref(report.id)}
      className="flex flex-col gap-1.5 rounded-lg border border-border bg-background p-3.5 transition-colors hover:border-primary/50 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="text-sm font-semibold text-foreground">{report.title}</span>
      <span className="text-xs leading-relaxed text-muted-foreground">
        {report.question}
      </span>
      <span className="mt-auto flex flex-wrap gap-1.5 pt-1 text-[11px] text-muted-foreground">
        <span className="rounded-full bg-muted px-2 py-0.5">{report.window}</span>
        {report.note ? (
          <span className="rounded-full bg-muted px-2 py-0.5">{report.note}</span>
        ) : null}
      </span>
    </Link>
  );
}

function ReportPage({ def }: { def: ReportDef }) {
  return (
    <div className="space-y-6">
      <Link
        href="/insights?tab=raporty"
        className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Raporty
      </Link>
      {def.defaultPeriod ? (
        <PeriodReport def={def} fallback={def.defaultPeriod} />
      ) : (
        <>
          <ViewHeader question={def.title} lede={def.question} />
          <ReportBody id={def.id} period={null} />
        </>
      )}
    </div>
  );
}

function PeriodReport({
  def,
  fallback,
}: {
  def: ReportDef;
  fallback: InsightsPeriodParams;
}) {
  const { period, setPeriod } = useInsightsPeriod(fallback);
  // Eksport CSV portfeli DL — ten sam klucz zapytania co tabela raportu,
  // więc to drugie odwołanie czyta cache zamiast pytać drugi raz.
  const dlPortfolio = useQuery({
    queryKey: insightsQueryKeys.dlPortfolio(period),
    queryFn: () => insightsBoardApi.dlPortfolio(period),
    enabled: def.id === "portfele-dl",
  });
  return (
    <>
      <ViewHeader
        question={def.title}
        lede={def.question}
        actions={
          <PeriodPicker
            value={period}
            onChange={setPeriod}
            defaultValue={fallback}
            csv={
              def.id === "portfele-dl"
                ? buildDlPortfolioCsvExport(dlPortfolio.data)
                : null
            }
          />
        }
      />
      <ReportBody id={def.id} period={period} />
    </>
  );
}

function ReportBody({
  id,
  period,
}: {
  id: ReportId;
  period: InsightsPeriodParams | null;
}) {
  const user = useAuthStore((state) => state.user);
  const p = period ?? { period: "month", offset: -1 };
  switch (id) {
    case "lejek-etapy":
      return <StageBreakdownSection period={p} />;
    case "czas-konwersje":
      return (
        <div className="space-y-4">
          <RecruitmentConversions period={p} />
          <InsightsTimeToHire period={p} />
        </div>
      );
    case "placementy":
      return <InsightsPlacementAnalysis period={p} />;
    case "kompetencje":
      return <CompetenceMatrix />;
    case "aktywnosc-zespolu":
      return (
        <div className="space-y-6">
          <InsightsTeamPerformance period={p} />
          <InsightsTeamActivity period={p} />
        </div>
      );
    case "obciazenie":
      return <AllocationWorkloadBoard />;
    case "prepy":
      return <PrepQualitySection />;
    case "bez-ruchu":
      return <StaleJobsReport />;
    case "doplyw":
      return (
        <div className="space-y-6">
          <InsightsIntegrations />
          <SourcesFunnelSection />
          <InviteLinksWithPeriod />
        </div>
      );
    case "portfele-dl":
      return (
        <div className="space-y-4">
          <DlPortfolioTiles period={p} />
          <InsightsDlPortfolio period={p} />
        </div>
      );
    case "ranking-klientow":
      return <InsightsClientsRanking period={p} />;
    case "rok-do-roku":
      return (
        <div className="space-y-6">
          {hasRole(user, "admin", "finance", "head_of_recruitment") ? (
            <InsightsBoardYoY />
          ) : null}
          <InsightsYearlyStats />
        </div>
      );
    case "hall-of-fame":
      return <InsightsHallOfFame />;
    case "sciezka":
      return <SeniorityBoard />;
  }
}

const INVITE_LINKS_DEFAULT: InsightsPeriodParams = { period: "month", offset: -1 };

/** Linki aplikacyjne mają własny okres — pozostałe części raportu liczą 7/30/90 dni. */
function InviteLinksWithPeriod() {
  const { period, setPeriod } = useInsightsPeriod(INVITE_LINKS_DEFAULT);
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-foreground">Linki aplikacyjne</h3>
        <PeriodPicker
          value={period}
          onChange={setPeriod}
          defaultValue={INVITE_LINKS_DEFAULT}
        />
      </div>
      <InsightsInviteLinks period={period} />
    </section>
  );
}
