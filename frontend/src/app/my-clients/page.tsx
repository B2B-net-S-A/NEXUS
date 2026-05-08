"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  Crown,
  TrendingUp,
} from "lucide-react";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { MyClientRow } from "@/lib/api/dlPortal";

export default function MyClientsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["my-clients"],
    queryFn: async () => {
      const res = await dlPortalApi.listMyClients();
      return res.data;
    },
  });

  if (isLoading) {
    return (
      <div className="p-6 text-muted-foreground">Ładowanie listy klientów…</div>
    );
  }
  if (error) {
    return (
      <div className="p-6 text-destructive">
        Błąd ładowania. Sprawdź uprawnienia (rola: delivery_lead / admin / head_of_recruitment).
      </div>
    );
  }

  const clients = data ?? [];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <header>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Building2 className="w-6 h-6 text-violet-600" />
          Moi klienci
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Klienci do których jesteś przypisany jako Delivery Lead. Klikając
          klienta otworzysz pełny panel z umowami ramowymi, zamówieniami i
          analityką.
        </p>
      </header>

      {clients.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg p-12 text-center text-muted-foreground">
          Nie masz jeszcze przypisanych klientów. Skontaktuj się z Head of
          Recruitment aby dodać przypisanie.
        </div>
      ) : (
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {clients.map((c) => (
            <ClientCard key={c.client_id} client={c} />
          ))}
        </ul>
      )}
    </div>
  );
}

interface ClientCardProps {
  client: MyClientRow;
}

function ClientCard({ client }: ClientCardProps) {
  return (
    <li className="border border-border rounded-lg bg-card hover:shadow-md transition-shadow">
      <Link
        href={`/clients/${client.client_id}?tab=analityka`}
        className="block p-4"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold">{client.name}</h3>
              {client.is_head_dl && (
                <span className="text-xs flex items-center gap-1 bg-violet-100 text-violet-700 px-2 py-0.5 rounded">
                  <Crown className="w-3 h-3" />
                  Head DL
                </span>
              )}
            </div>
            {client.industry && (
              <p className="text-xs text-muted-foreground">{client.industry}</p>
            )}
          </div>
          <ArrowRight className="w-4 h-4 text-muted-foreground" />
        </div>

        <div className="mt-3 space-y-1.5 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Aktywne ordery:</span>
            <span className="font-medium">{client.active_orders_count}</span>
          </div>
          {client.active_revenue !== null && (
            <div className="flex justify-between">
              <span className="text-muted-foreground flex items-center gap-1">
                <TrendingUp className="w-3 h-3" />
                Active revenue:
              </span>
              <span className="font-medium">{fmt(client.active_revenue)}</span>
            </div>
          )}
          {client.framework_contract_status && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">MSA:</span>
              <span className="font-medium">
                {client.framework_contract_status}
                {client.framework_expiry_date &&
                  ` (do ${client.framework_expiry_date})`}
              </span>
            </div>
          )}
          {client.expiring_soon_count > 0 && (
            <div className="text-xs flex items-center gap-1 text-orange-700 bg-orange-50 px-2 py-1 rounded">
              <AlertTriangle className="w-3 h-3" />
              {client.expiring_soon_count} dokumentów wygasa w 30 dni
            </div>
          )}
        </div>
      </Link>
    </li>
  );
}

function fmt(v: string | number | null): string {
  if (v === null || v === undefined) return "—";
  const num = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(num)) return "—";
  return num.toLocaleString("pl-PL");
}
