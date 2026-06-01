"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { BarChart3, Briefcase, Building2, Users } from "lucide-react";
import { api } from "@/lib/api";

interface HiringManagerKpi {
  contact_id: number;
  contact_name: string;
  position: string | null;
  client_id: number;
  client_name: string;
  jobs_total: number;
  jobs_open: number;
  contracts_total: number;
  contracts_active: number;
}

export default function HiringManagersAnalyticsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["hiring-managers-analytics"],
    queryFn: async () => {
      const res = await api.get<HiringManagerKpi[]>(
        "/api/reports/hiring-managers",
      );
      return res.data;
    },
  });

  if (isLoading) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }
  if (error) {
    return (
      <div className="p-6 text-destructive">
        Błąd ładowania. Wymaga roli admin / head_of_recruitment.
      </div>
    );
  }

  const rows = data ?? [];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <header>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <BarChart3 className="w-6 h-6 text-violet-600" />
          Top hiring managers
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Ranking osób po stronie klientów odpowiedzialnych za rekrutacje.
          Liczone tylko rekrutacje (Jobs) z przypisanym hiring_manager_contact_id.
        </p>
      </header>

      {rows.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg p-12 text-center text-muted-foreground">
          <Users className="w-12 h-12 mx-auto mb-2 opacity-40" />
          Brak danych. Przy tworzeniu nowych Jobów wybierz hiring managera
          (pole &quot;Hiring manager&quot; w formularzu), żeby zacząć zbierać statystyki.
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 border-b border-border">
              <tr>
                <th className="text-left px-3 py-2 font-medium">#</th>
                <th className="text-left px-3 py-2 font-medium">Hiring manager</th>
                <th className="text-left px-3 py-2 font-medium">Klient</th>
                <th className="text-right px-3 py-2 font-medium">Rekrutacje (total)</th>
                <th className="text-right px-3 py-2 font-medium">Otwarte</th>
                <th className="text-right px-3 py-2 font-medium">Kontrakty total</th>
                <th className="text-right px-3 py-2 font-medium">Aktywni</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr
                  key={r.contact_id}
                  className="border-b border-border hover:bg-accent/30"
                >
                  <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                  <td className="px-3 py-2">
                    <div className="font-medium">{r.contact_name}</div>
                    {r.position && (
                      <div className="text-xs text-muted-foreground">
                        {r.position}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      href={`/clients/${r.client_id}`}
                      className="text-violet-600 hover:underline flex items-center gap-1"
                    >
                      <Building2 className="w-3 h-3" />
                      {r.client_name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-right font-medium">
                    {r.jobs_total}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {r.jobs_open > 0 ? (
                      <span className="text-green-700">
                        <Briefcase className="w-3 h-3 inline mr-1" />
                        {r.jobs_open}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">–</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">{r.contracts_total}</td>
                  <td className="px-3 py-2 text-right text-green-700">
                    {r.contracts_active}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
