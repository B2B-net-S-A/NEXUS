"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  CopyCheck,
  FileSpreadsheet,
  Link2,
  Users,
} from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import api from "@/lib/api";
import { resolveViewState } from "@/lib/view-state";

interface ClientRef {
  id: number;
  name: string;
  display_name: string | null;
  legal_name: string | null;
  external_source: string | null;
  external_id: string | null;
}

interface ImportPlan {
  manifest_sha256: string;
  snapshot_date: string;
  plan_sha256: string;
  summary: {
    manifest_rows: number;
    matched_groups: number;
    created_groups: number;
    blocked_groups: number;
    nexus_only_clients: number;
    duplicate_candidates: number;
    blockers: number;
    warnings: number;
  };
  blockers: Array<Record<string, unknown>>;
  warnings: Array<Record<string, unknown>>;
  groups: Array<{
    client_key: string;
    action: "match" | "create" | "blocked";
    match_method?: string | null;
    target_client?: ClientRef;
    rows: Array<{
      source_key: string;
      display_name: string;
      legal_name: string;
      category: string;
      scope_label: string | null;
    }>;
  }>;
  duplicate_candidates: Array<{
    client_ids: number[];
    names: string[];
    reason: string;
    score: number;
    clients: ClientRef[];
    dependency_counts: Record<
      string,
      Array<{ table: string; column: string; rows: number }>
    >;
    jsonb_dependency_counts: Record<string, number>;
  }>;
  nexus_only: ClientRef[];
  kir_merge: null | {
    source: ClientRef;
    target: ClientRef;
    fk_impact: Array<{ table: string; column: string; rows: number }>;
    jsonb_candidates: number;
  };
}

function JsonDetails({
  title,
  value,
}: {
  title: string;
  value: unknown;
}) {
  return (
    <details className="rounded-lg border border-border bg-card">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-foreground">
        {title}
      </summary>
      <pre className="max-h-96 overflow-auto border-t border-border bg-muted/40 p-4 text-xs text-muted-foreground">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

export default function ClientPortfolioPreviewPage() {
  const query = useQuery({
    queryKey: ["admin-client-portfolio-preview"],
    queryFn: () =>
      api
        .get<ImportPlan>("/api/admin/client-portfolio/import-preview")
        .then((response) => response.data),
    retry: false,
  });
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: !query.data,
  });

  if (viewState !== "ready") {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-6">
        <Link
          href="/settings"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Ustawienia
        </Link>
        {viewState === "loading" ? (
          <div className="h-48 animate-pulse rounded-xl bg-muted" />
        ) : (
          <QueryStateNotice
            state={viewState === "empty" ? "not_found" : viewState}
            onRetry={() => void query.refetch()}
          />
        )}
      </div>
    );
  }

  const plan = query.data!;
  const safeToApply = plan.summary.blockers === 0;
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            href="/settings"
            className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Ustawienia
          </Link>
          <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
            Administracja · Klienci
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-heading-tight">
            Podgląd importu portfela
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Plan tylko do odczytu dla snapshotu {plan.snapshot_date}. Ta strona
            nie zapisuje ani nie scala rekordów.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={safeToApply ? "success" : "danger"}>
            {safeToApply ? "Brak blockerów" : `${plan.summary.blockers} blockerów`}
          </Badge>
          <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
            Odśwież
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          {
            label: "Wiersze manifestu",
            value: plan.summary.manifest_rows,
            icon: FileSpreadsheet,
          },
          {
            label: "Dopasowane grupy",
            value: plan.summary.matched_groups,
            icon: Link2,
          },
          {
            label: "Nowi klienci",
            value: plan.summary.created_groups,
            icon: Users,
          },
          {
            label: "Podejrzenia duplikatów",
            value: plan.summary.duplicate_candidates,
            icon: CopyCheck,
          },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded-xl border border-border bg-card p-4 shadow-xs"
          >
            <item.icon className="h-5 w-5 text-primary" aria-hidden="true" />
            <p className="mt-3 text-2xl font-semibold tabular-nums">
              {item.value}
            </p>
            <p className="text-sm text-muted-foreground">{item.label}</p>
          </div>
        ))}
      </div>

      <section className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-start gap-3">
          {safeToApply ? (
            <CheckCircle2
              className="mt-0.5 h-5 w-5 text-success"
              aria-hidden="true"
            />
          ) : (
            <AlertTriangle
              className="mt-0.5 h-5 w-5 text-destructive"
              aria-hidden="true"
            />
          )}
          <div>
            <h2 className="font-semibold">Wynik walidacji</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {safeToApply
                ? "Plan może przejść do etapu zatwierdzonego apply-once."
                : "Apply-once zakończy się bez zapisów, dopóki każdy blocker nie zostanie rozwiązany."}
            </p>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">
          Plan dopasowań ({plan.groups.length})
        </h2>
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="min-w-full divide-y divide-border text-sm">
            <thead className="bg-muted/40 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Klucz klienta</th>
                <th className="px-4 py-3">Akcja</th>
                <th className="px-4 py-3">Metoda</th>
                <th className="px-4 py-3">Rekord docelowy</th>
                <th className="px-4 py-3">Zakresy</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {plan.groups.map((group) => (
                <tr key={group.client_key}>
                  <td className="px-4 py-3 font-medium">{group.client_key}</td>
                  <td className="px-4 py-3">
                    <Badge
                      size="sm"
                      variant={
                        group.action === "blocked"
                          ? "danger"
                          : group.action === "create"
                            ? "soft"
                            : "success"
                      }
                    >
                      {group.action}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {group.match_method || "—"}
                  </td>
                  <td className="px-4 py-3">
                    {group.target_client
                      ? `#${group.target_client.id} · ${
                          group.target_client.display_name ||
                          group.target_client.name
                        }`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {group.rows
                      .map((row) =>
                        row.scope_label
                          ? `${row.category}: ${row.scope_label}`
                          : row.category,
                      )
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Znany merge KIR</h2>
        {plan.kir_merge ? (
          <div className="rounded-xl border border-border bg-card p-4 text-sm">
            <p>
              <strong>{plan.kir_merge.source.display_name || plan.kir_merge.source.name}</strong>
              {" → "}
              <strong>{plan.kir_merge.target.display_name || plan.kir_merge.target.name}</strong>
            </p>
            <p className="mt-1 text-muted-foreground">
              Rekord źródłowy #{plan.kir_merge.source.id}, rekord zachowany #
              {plan.kir_merge.target.id}; zależności:{" "}
              {plan.kir_merge.fk_impact.reduce(
                (sum, item) => sum + item.rows,
                0,
              ) + plan.kir_merge.jsonb_candidates}
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Brak jednoznacznej pary do scalenia — szczegóły są w ostrzeżeniach
            lub blockerach.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">
          Inne podejrzenia duplikatów ({plan.duplicate_candidates.length})
        </h2>
        {plan.duplicate_candidates.length ? (
          <div className="overflow-x-auto rounded-xl border border-border bg-card">
            <table className="min-w-full divide-y divide-border text-sm">
              <thead className="bg-muted/40 text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">Nazwy</th>
                  <th className="px-4 py-3">Identyfikatory źródłowe</th>
                  <th className="px-4 py-3">Zależności</th>
                  <th className="px-4 py-3">Powód</th>
                  <th className="px-4 py-3">Pewność</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {plan.duplicate_candidates.map((candidate) => (
                  <tr key={candidate.client_ids.join("-")}>
                    <td className="px-4 py-3 tabular-nums">
                      {candidate.client_ids.join(", ")}
                    </td>
                    <td className="px-4 py-3 font-medium">
                      {candidate.names.join(" / ")}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {candidate.clients
                        .map((client) =>
                          client.external_id
                            ? `${client.external_source || "?"}:${client.external_id}`
                            : `#${client.id}: brak`,
                        )
                        .join(" / ")}
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {candidate.client_ids
                        .map((clientId) => {
                          const count = (
                            candidate.dependency_counts[String(clientId)] || []
                          ).reduce((sum, item) => sum + item.rows, 0) +
                            (candidate.jsonb_dependency_counts[
                              String(clientId)
                            ] || 0);
                          return `#${clientId}: ${count}`;
                        })
                        .join(" / ")}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {candidate.reason}
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {(candidate.score * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Nie wykryto dodatkowych kandydatów do scalenia.
          </p>
        )}
      </section>

      <div className="space-y-2">
        <JsonDetails
          title={`Blockery (${plan.blockers.length})`}
          value={plan.blockers}
        />
        <JsonDetails
          title={`Ostrzeżenia (${plan.warnings.length})`}
          value={plan.warnings}
        />
        <JsonDetails
          title={`Klienci tylko w NEXUS (${plan.nexus_only.length})`}
          value={plan.nexus_only}
        />
        <JsonDetails
          title="Pełny plan dopasowań"
          value={plan.groups}
        />
        <JsonDetails
          title="Identyfikatory planu"
          value={{
            manifest_sha256: plan.manifest_sha256,
            plan_sha256: plan.plan_sha256,
          }}
        />
      </div>
    </div>
  );
}
