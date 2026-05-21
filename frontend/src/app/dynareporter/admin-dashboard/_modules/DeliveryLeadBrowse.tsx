"use client";

/**
 * DeliveryLeadBrowse — zakładka "Przeglądaj dane" dla Delivery Lead.
 *
 * Wybór miesiąca + roku (zostaje, zgodnie z modelem miesięcznych KPI) → tabela
 * per-DL (requests / placements / vacancies / hit ratio / fill rate) z dashboardu
 * dla wybranego miesiąca. Port "browse" z artur-t-96/InfraReporter.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, RefreshCw, AlertCircle } from "lucide-react";
import { dynareporterDeliveryLeadApi, type DrDLMember } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const MONTHS_PL = [
  "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
  "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień",
];

export function DeliveryLeadBrowse() {
  const now = new Date();
  const [selectedYear, setSelectedYear] = useState(now.getFullYear());
  const [selectedMonth, setSelectedMonth] = useState(now.getMonth() + 1);

  const reportMonth = `${selectedYear}-${String(selectedMonth).padStart(2, "0")}`;
  const monthStart = `${reportMonth}-01`;
  const monthEnd = new Date(selectedYear, selectedMonth, 0)
    .toISOString()
    .split("T")[0];

  const monthQuery = useQuery({
    queryKey: ["dr-dl-browse", monthStart, monthEnd],
    queryFn: () =>
      dynareporterDeliveryLeadApi.dashboard({
        start_date: monthStart,
        end_date: monthEnd,
      }),
    staleTime: 30_000,
  });

  const yearOptions = useMemo(() => {
    const base = new Date().getFullYear();
    return [base + 1, base, base - 1, base - 2];
  }, []);

  // Tylko DL-e z jakimikolwiek danymi w miesiącu (parytet z widokiem zespołu).
  const rows = useMemo(() => {
    const dls = monthQuery.data?.delivery_leads ?? [];
    return dls
      .filter((d: DrDLMember) => d.requests > 0 || d.placements > 0 || d.vacancies > 0)
      .sort((a, b) => b.placements - a.placements);
  }, [monthQuery.data]);

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-center gap-3">
            <Calendar className="w-4 h-4 text-muted-foreground" />
            <label className="text-sm text-muted-foreground">Miesiąc:</label>
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(Number(e.target.value))}
              className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              aria-label="Wybierz miesiąc"
            >
              {MONTHS_PL.map((m, i) => (
                <option key={m} value={i + 1}>
                  {m}
                </option>
              ))}
            </select>
            <label className="text-sm text-muted-foreground">Rok:</label>
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(Number(e.target.value))}
              className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              aria-label="Wybierz rok"
            >
              {yearOptions.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => monthQuery.refetch()}
              aria-label="Odśwież"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
            </Button>
            <span className="text-xs text-muted-foreground ml-auto">
              {MONTHS_PL[selectedMonth - 1]} {selectedYear} · {rows.length} DL
            </span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {monthQuery.isLoading ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              Ładowanie…
            </p>
          ) : rows.length === 0 ? (
            <div className="py-10 text-center space-y-2">
              <AlertCircle className="w-8 h-8 text-muted-foreground mx-auto" />
              <p className="text-sm text-muted-foreground">
                Brak danych Delivery Lead za {MONTHS_PL[selectedMonth - 1]} {selectedYear}.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/40">
                  <tr>
                    {[
                      ["Delivery Lead", "left"],
                      ["Zapytania", "center"],
                      ["Wakaty", "center"],
                      ["Placements", "center"],
                      ["Hit Ratio", "center"],
                      ["Fill Rate", "center"],
                    ].map(([h, align]) => (
                      <th
                        key={h}
                        className={`px-3 py-2 text-${align} text-[10px] font-medium text-muted-foreground uppercase`}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rows.map((d) => (
                    <tr key={d.id}>
                      <td className="px-3 py-2 font-medium">{d.name}</td>
                      <td className="px-3 py-2 text-center tabular-nums">
                        {d.requests}
                      </td>
                      <td className="px-3 py-2 text-center tabular-nums">
                        {d.vacancies}
                      </td>
                      <td className="px-3 py-2 text-center tabular-nums font-semibold">
                        {d.placements}
                      </td>
                      <td className="px-3 py-2 text-center tabular-nums">
                        <span
                          className={
                            d.target_achieved
                              ? "text-emerald-600 font-semibold"
                              : "text-muted-foreground"
                          }
                        >
                          {d.hit_ratio.toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center tabular-nums">
                        {d.fill_rate.toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
