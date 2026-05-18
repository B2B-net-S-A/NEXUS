"use client";

import { useQuery } from "@tanstack/react-query";
import { Link2, Target, Users } from "lucide-react";
import { reportsApi } from "@/lib/api";
import { KpiCard, LoadingSpinner } from "./_shared";
import type { Period } from "./PeriodSelector";

interface InviteLinksReportChannel {
  channel: string;
  links_count: number;
  applications: number;
  conversion_pct: number;
  last_used_at: string | null;
}

interface InviteLinksReportData {
  period: string;
  channels: InviteLinksReportChannel[];
  totals: {
    links: number;
    applications: number;
    candidates: number;
    conversion_pct: number;
  };
}

const REPORT_PERIOD_MAP: Record<Period, "week" | "month" | "quarter" | "year"> = {
  today: "week",
  week: "week",
  month: "month",
  quarter: "quarter",
};

interface Props {
  period: Period;
}

export function InviteLinksSection({ period }: Props) {
  const reportPeriod = REPORT_PERIOD_MAP[period];

  const { data, isLoading } = useQuery({
    queryKey: ["insights-invite-links", reportPeriod],
    queryFn: () =>
      reportsApi
        .inviteLinks({ period: reportPeriod })
        .then((r) => r.data as InviteLinksReportData),
  });

  if (isLoading) return <LoadingSpinner />;
  if (!data) return null;

  const hasData = data.channels.length > 0;

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Link2 className="w-5 h-5 text-primary" />
        Linki aplikacyjne
      </h2>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Linki" value={data.totals.links} icon={Link2} color="blue" />
        <KpiCard label="Aplikacje" value={data.totals.applications} icon={Users} color="green" />
        <KpiCard
          label="Unikalni kandydaci"
          value={data.totals.candidates}
          icon={Users}
          color="purple"
        />
        <KpiCard
          label="Konwersja"
          value={`${data.totals.conversion_pct}%`}
          icon={Target}
          color="orange"
        />
      </div>

      <div className="bg-card rounded-xl border border-border shadow-sm">
        <div className="px-6 py-4 border-b border-border">
          <h3 className="text-sm font-semibold text-foreground">Skuteczność kanałów</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Linki aplikacyjne grupowane po etykiecie (np. „LinkedIn post 04/26"). Linki bez
            etykiety trafiają do „Bez etykiety".
          </p>
        </div>
        {hasData ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs uppercase tracking-wider text-muted-foreground bg-muted/40">
                <tr>
                  {["Kanał", "Linki", "Aplikacje", "Konwersja", "Ostatnio użyty"].map((h) => (
                    <th key={h} className="text-left px-6 py-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.channels.map((ch) => (
                  <tr key={ch.channel} className="border-t border-border hover:bg-muted/30">
                    <td className="px-6 py-3 font-medium text-foreground">{ch.channel}</td>
                    <td className="px-6 py-3 text-foreground">{ch.links_count}</td>
                    <td className="px-6 py-3 text-foreground">{ch.applications}</td>
                    <td className="px-6 py-3 text-foreground">{ch.conversion_pct}%</td>
                    <td className="px-6 py-3 text-muted-foreground">
                      {ch.last_used_at
                        ? new Date(ch.last_used_at).toLocaleDateString("pl-PL", {
                            day: "2-digit",
                            month: "short",
                            year: "numeric",
                          })
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-6 py-12 text-center text-sm text-muted-foreground">
            Nie wygenerowano jeszcze żadnych linków w tym okresie.
          </div>
        )}
      </div>
    </section>
  );
}
