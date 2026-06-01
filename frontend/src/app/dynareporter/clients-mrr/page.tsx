"use client";

/**
 * DynaReporter B.2.5 – Clients + MRR + Finances (readonly).
 */

import { useQuery } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";

interface ClientMrr {
  client_id: number;
  client_name?: string;
  report_month: string;
  consultants_count: number;
  mrr: string;
}
interface Finance {
  report_month: string;
  total_revenue: string;
  total_costs: string;
  profit: string;
  cv_database_count: number;
  consultants_churn: number;
  department?: string;
}
interface MrrSummary {
  from_month: string;
  to_month: string;
  total_mrr: string;
  avg_consultants: number;
  distinct_clients: number;
}

export default function ClientsMrrPage() {
  const { user, hydrated } = useAuthStore();
  const mrrQ = useQuery({
    queryKey: ["dr", "mrr"],
    queryFn: () =>
      api.get<ClientMrr[]>("/api/dynareporter/clients-mrr/mrr").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "clients-mrr"),
  });
  const finQ = useQuery({
    queryKey: ["dr", "finances"],
    queryFn: () =>
      api
        .get<Finance[]>("/api/dynareporter/clients-mrr/finances", { params: { months: 12 } })
        .then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "clients-mrr"),
  });
  const sumQ = useQuery({
    queryKey: ["dr", "mrr", "summary"],
    queryFn: () =>
      api.get<MrrSummary>("/api/dynareporter/clients-mrr/summary").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "clients-mrr"),
  });

  if (!hydrated) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  if (!user) return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  if (!hasSection(user, "clients-mrr")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">Brak sekcji <code>clients-mrr</code>.</p>
        </div>
      </div>
    );
  }

  const formatPLN = (v: string | number) =>
    new Intl.NumberFormat("pl-PL", { style: "currency", currency: "PLN", maximumFractionDigits: 0 })
      .format(typeof v === "string" ? parseFloat(v) : v);

  return (
    <div className="container mx-auto max-w-7xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Klienci + MRR + Finanse</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Konsultanci u klientów + miesięczny MRR + miesięczny P&L per departament.
        </p>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Card label="Suma MRR (12 mc)" value={sumQ.data ? formatPLN(sumQ.data.total_mrr) : "…"} accent />
        <Card label="Ø Konsultantów" value={sumQ.data?.avg_consultants.toFixed(1) ?? "…"} />
        <Card label="Aktywnych klientów" value={sumQ.data?.distinct_clients ?? "…"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="font-semibold text-sm mb-3">MRR – ostatnie miesiące</h2>
          {mrrQ.isLoading ? <p className="text-sm text-muted-foreground">Ładowanie…</p> :
           (mrrQ.data ?? []).length === 0 ? <p className="text-sm text-muted-foreground py-4">Brak danych.</p> :
           <div className="overflow-x-auto max-h-96 overflow-y-auto">
             <table className="w-full text-xs">
               <thead className="sticky top-0 bg-card">
                 <tr className="text-left text-muted-foreground border-b border-border">
                   <th className="pb-2 font-medium">Miesiąc</th>
                   <th className="pb-2 font-medium">Klient</th>
                   <th className="pb-2 font-medium text-right">Kons.</th>
                   <th className="pb-2 font-medium text-right">MRR</th>
                 </tr>
               </thead>
               <tbody>
                 {(mrrQ.data ?? []).slice(0, 100).map((m, i) => (
                   <tr key={i} className="border-b border-border last:border-0">
                     <td className="py-2 tabular-nums">{m.report_month.slice(0, 7)}</td>
                     <td className="py-2 truncate">{m.client_name || `#${m.client_id}`}</td>
                     <td className="py-2 text-right tabular-nums">{m.consultants_count}</td>
                     <td className="py-2 text-right tabular-nums font-semibold">{formatPLN(m.mrr)}</td>
                   </tr>
                 ))}
               </tbody>
             </table>
           </div>}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="font-semibold text-sm mb-3">Finanse miesięczne (P&L)</h2>
          {finQ.isLoading ? <p className="text-sm text-muted-foreground">Ładowanie…</p> :
           (finQ.data ?? []).length === 0 ? <p className="text-sm text-muted-foreground py-4">Brak danych.</p> :
           <div className="overflow-x-auto max-h-96 overflow-y-auto">
             <table className="w-full text-xs">
               <thead className="sticky top-0 bg-card">
                 <tr className="text-left text-muted-foreground border-b border-border">
                   <th className="pb-2 font-medium">Miesiąc</th>
                   <th className="pb-2 font-medium">Dept.</th>
                   <th className="pb-2 font-medium text-right">Przychód</th>
                   <th className="pb-2 font-medium text-right">Koszty</th>
                   <th className="pb-2 font-medium text-right">Zysk</th>
                 </tr>
               </thead>
               <tbody>
                 {(finQ.data ?? []).map((f, i) => (
                   <tr key={i} className="border-b border-border last:border-0">
                     <td className="py-2 tabular-nums">{f.report_month.slice(0, 7)}</td>
                     <td className="py-2 text-muted-foreground text-[10px] uppercase">{f.department ?? "all"}</td>
                     <td className="py-2 text-right tabular-nums">{formatPLN(f.total_revenue)}</td>
                     <td className="py-2 text-right tabular-nums text-destructive">{formatPLN(f.total_costs)}</td>
                     <td className="py-2 text-right tabular-nums font-semibold">{formatPLN(f.profit)}</td>
                   </tr>
                 ))}
               </tbody>
             </table>
           </div>}
        </div>
      </div>
    </div>
  );
}

function Card({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div className={accent ? "rounded-lg border border-primary/30 bg-card p-3" : "rounded-lg border border-border bg-card p-3"}>
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className={accent ? "mt-1 text-2xl font-bold tabular-nums text-primary" : "mt-1 text-2xl font-bold tabular-nums"}>{value}</p>
    </div>
  );
}
