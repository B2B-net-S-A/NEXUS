"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2 } from "lucide-react";
import { phase3Api } from "@/lib/api";

interface TimeToHireRow {
  recruiter_id: number;
  name: string;
  placements: number;
  median_days: number | null;
  p90_days: number | null;
}

interface TTHResponse {
  by_recruiter: TimeToHireRow[];
  total_placements: number;
}

export function TimeToHireSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["insights-tth"],
    queryFn: () => phase3Api.timeToHire().then((r) => r.data as TTHResponse),
  });

  const rows = data?.by_recruiter ?? [];
  const totalPlacements = data?.total_placements ?? 0;

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2 mb-4">
        <BarChart3 className="w-5 h-5 text-green-500" />
        Time-to-hire
        <span className="ml-auto text-xs text-muted-foreground font-normal">
          180 dni · łącznie {totalPlacements} zatrudnień
        </span>
      </h2>

      {isLoading ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak zatrudnień w okresie — dane pojawią się po pierwszej zamkniętej rekrutacji ze stage „Zatrudniony".
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-muted-foreground">
            <tr>
              <th className="text-left py-2">Rekruter</th>
              <th className="text-right py-2">Zatrudnień</th>
              <th className="text-right py-2">Mediana (dni)</th>
              <th className="text-right py-2">P90 (dni)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.recruiter_id} className="border-t border-border">
                <td className="py-2 font-medium text-foreground">{r.name}</td>
                <td className="py-2 text-right">{r.placements}</td>
                <td className="py-2 text-right">{r.median_days ?? "—"}</td>
                <td className="py-2 text-right">{r.p90_days ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
