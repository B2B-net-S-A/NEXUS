"use client";

// Per-client analytics view — montowany jako sub-tab w `/clients/[id]?tab=analityka`.
// To NIE jest część top-level `/insights` (organizacyjne dashboardy). Top-level
// stronę `/analytics` usunęliśmy w PR #232; nie przenosić tutaj jej logiki.

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FileText, TrendingUp, Users } from "lucide-react";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { ClientDashboardResponse, ExpiringAlert } from "@/lib/api/dlPortal";
import { hasAnalyticsCapability, useAuthStore } from "@/store/auth";

interface AnalyticsTabProps {
  clientId: number;
}

export function AnalyticsTab({ clientId }: AnalyticsTabProps) {
  const { user, hydrated } = useAuthStore();
  const canSeeFinance = hasAnalyticsCapability(user, "view_finance");
  const scopeCacheKey = user?.data_scope
    ? JSON.stringify({
        kind: user.data_scope.kind,
        userId: user.data_scope.user_id,
        clientIds: [...user.data_scope.allowed_client_ids].sort((a, b) => a - b),
        tacUserIds: [...user.data_scope.allowed_tac_user_ids].sort(
          (a, b) => a - b,
        ),
        operatorUserIds: [...user.data_scope.allowed_operator_user_ids].sort(
          (a, b) => a - b,
        ),
        clientTacPairs: [
          ...(user.data_scope.allowed_client_tac_pairs ?? []),
        ].sort(
          (a, b) =>
            a.client_id - b.client_id || a.tac_user_id - b.tac_user_id,
        ),
      })
    : "no-scope";
  const capabilityCacheKey = Array.from(
    new Set([
      ...(user?.capabilities ?? []),
      ...(user?.analytics_capabilities ?? []),
    ]),
  )
    .sort()
    .join(",");
  const { data, isLoading, error } = useQuery({
    queryKey: [
      "client-dashboard",
      clientId,
      user?.id ?? null,
      user?.authorization_version ?? null,
      scopeCacheKey,
      capabilityCacheKey,
    ],
    queryFn: async () => {
      const res = await dlPortalApi.getDashboard(clientId);
      return res.data;
    },
    enabled: hydrated && Boolean(user),
  });

  if (!hydrated || isLoading) {
    return <div className="text-muted-foreground">Ładowanie analityki…</div>;
  }
  if (error || !data) {
    return (
      <div className="text-destructive">
        Błąd analityki — sprawdź uprawnienia lub spróbuj ponownie.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">{data.client_name} — analityka</h3>

      <KpiGrid data={data} showFinance={canSeeFinance} />

      {canSeeFinance ? <CurrencyBreakdown data={data} /> : null}

      <AlertsList alerts={data.alerts} />
    </div>
  );
}

function KpiGrid({
  data,
  showFinance,
}: {
  data: ClientDashboardResponse;
  showFinance: boolean;
}) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {showFinance ? (
        <>
          <KpiCard
            label="Revenue lifetime (PLN)"
            value={fmtMoney(data.total_revenue_all_time)}
            icon={<TrendingUp className="w-4 h-4 text-success-muted-foreground" />}
          />
          <KpiCard
            label="Active revenue (PLN)"
            value={fmtMoney(data.active_revenue)}
            sublabel={`${data.active_orders_count} zamówień`}
          />
          <KpiCard
            label="Marża/mc (PLN, gross)"
            value={
              data.monthly_margin_total != null
                ? `${data.monthly_margin_total}`
                : "—"
            }
            sublabel={
              data.monthly_margin_pct != null
                ? `${data.monthly_margin_pct}%`
                : undefined
            }
          />
        </>
      ) : null}
      <KpiCard
        label="Konsultanci aktywni"
        value={`${data.active_consultants}`}
        sublabel={`${data.active_contracts} aktywnych kontraktów · ${data.completed_consultants} zakończonych`}
        icon={<Users className="w-4 h-4 text-primary" />}
      />
      <KpiCard
        label="Avg time to fill"
        value={data.avg_days_to_fill !== null ? `${data.avg_days_to_fill} dni` : "—"}
      />
      <KpiCard
        label="MSA"
        value={`${data.framework_contracts_count}`}
        icon={<FileText className="w-4 h-4 text-primary" />}
      />
      <KpiCard label="Active orders" value={`${data.active_orders_count}`} />
      <KpiCard label="Completed orders" value={`${data.completed_orders_count}`} />
    </div>
  );
}

interface KpiCardProps {
  label: string;
  value: string;
  sublabel?: string;
  icon?: React.ReactNode;
}

function KpiCard({ label, value, sublabel, icon }: KpiCardProps) {
  return (
    <div className="border border-border rounded-lg p-3 bg-card">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
        {icon}
        {label}
      </div>
      <div className="text-xl font-semibold">{value}</div>
      {sublabel && <div className="text-xs text-muted-foreground mt-0.5">{sublabel}</div>}
    </div>
  );
}

function CurrencyBreakdown({ data }: { data: ClientDashboardResponse }) {
  const entries = Object.entries(data.currency_breakdown ?? {});
  if (entries.length === 0) return null;
  return (
    <div className="border border-border rounded-lg p-3 bg-card">
      <h4 className="text-sm font-medium mb-2">Revenue per waluta</h4>
      <ul className="space-y-1 text-sm">
        {entries.map(([currency, amount]) => (
          <li key={currency} className="flex justify-between">
            <span className="text-muted-foreground">{currency}</span>
            <span className="font-medium">{amount}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AlertsList({ alerts }: { alerts: ExpiringAlert[] }) {
  if (alerts.length === 0) {
    return (
      <div className="border border-border rounded-lg p-3 bg-card text-sm text-muted-foreground">
        Brak alertów ekspirujących w 30 dni.
      </div>
    );
  }
  return (
    <div className="border border-border rounded-lg p-3 bg-card">
      <h4 className="text-sm font-medium mb-2 flex items-center gap-1.5">
        <AlertTriangle className="w-4 h-4 text-warning" />
        Alerty (≤ 30 dni)
      </h4>
      <ul className="space-y-1.5">
        {alerts.map((a) => (
          <li
            key={`${a.kind}-${a.entity_id}`}
            className="flex items-center justify-between text-sm border-l-2 border-warning pl-2"
          >
            <div>
              <span className="font-medium">{a.label}</span>
              <span className="text-xs text-muted-foreground ml-2">
                {a.kind === "framework_contract" ? "umowa ramowa" : "zamówienie"}
              </span>
            </div>
            <div className="rounded bg-warning-muted px-2 py-0.5 text-xs text-warning-muted-foreground">
              {a.days_to_expiry} dni · {a.expiry_date}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function fmtMoney(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const num = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(num)) return "—";
  return num.toLocaleString("pl-PL");
}
