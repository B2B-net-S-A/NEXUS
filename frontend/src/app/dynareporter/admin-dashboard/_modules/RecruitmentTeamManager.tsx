"use client";

/**
 * Recruitment Team Manager — read-only view: skład zespołu rekrutacji.
 *
 * Port `RecruitmentTeamManager.tsx` z artur-t-96/InfraReporter (skrócony do
 * 3 zakładek: członkowie zespołu, TAC↔DL, Sourcer↔Category).
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users, GitBranch, Layers, RefreshCw } from "lucide-react";
import { dynareporterAdminUsersApi } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const ROLE_LABEL: Record<string, string> = {
  sourcer: "Sourcer",
  tac: "TAC",
  recruiter: "Rekruter",
  delivery_lead: "Delivery Lead",
};

const ROLE_COLOR: Record<string, "neutral" | "success" | "warning" | "info"> = {
  sourcer: "info",
  tac: "warning",
  recruiter: "success",
  delivery_lead: "neutral",
};

export function RecruitmentTeamManager() {
  const [tab, setTab] = useState<"members" | "tac_dl" | "sourcer_cat">("members");

  const membersQuery = useQuery({
    queryKey: ["dr-admin-team-members"],
    queryFn: () => dynareporterAdminUsersApi.teamMembers(),
    staleTime: 60_000,
  });

  const tacDlQuery = useQuery({
    queryKey: ["dr-admin-team-tac-dl"],
    queryFn: () => dynareporterAdminUsersApi.tacDl(),
    staleTime: 60_000,
    enabled: tab === "tac_dl",
  });

  const sourcerCatQuery = useQuery({
    queryKey: ["dr-admin-team-sourcer-cat"],
    queryFn: () => dynareporterAdminUsersApi.sourcerCategories(),
    staleTime: 60_000,
    enabled: tab === "sourcer_cat",
  });

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Users className="w-5 h-5 text-teal-600" />
            Zespół Rekrutacji
          </h3>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (tab === "members") membersQuery.refetch();
              if (tab === "tac_dl") tacDlQuery.refetch();
              if (tab === "sourcer_cat") sourcerCatQuery.refetch();
            }}
          >
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
          </Button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-border mb-4">
          {[
            { type: "members", label: "Członkowie", icon: Users },
            { type: "tac_dl", label: "TAC ↔ DL", icon: GitBranch },
            { type: "sourcer_cat", label: "Sourcer ↔ Kategoria", icon: Layers },
          ].map((t) => {
            const Icon = t.icon;
            const isActive = tab === t.type;
            return (
              <button
                key={t.type}
                onClick={() => setTab(t.type as typeof tab)}
                className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
                  isActive
                    ? "text-foreground border-primary"
                    : "text-muted-foreground border-transparent hover:text-foreground"
                }`}
              >
                <Icon className="w-4 h-4" />
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Tab content: members */}
        {tab === "members" && (
          <>
            {membersQuery.isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">Ładowanie…</p>
            ) : (membersQuery.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Brak członków zespołu rekrutacji.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Imię i Nazwisko
                      </th>
                      <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Email
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Rola
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(membersQuery.data ?? []).map((m) => (
                      <tr key={m.id}>
                        <td className="px-2 py-2 font-medium">{m.name}</td>
                        <td className="px-2 py-2 text-xs text-muted-foreground">{m.email}</td>
                        <td className="px-2 py-2 text-center">
                          <Badge variant={ROLE_COLOR[m.role] ?? "neutral"} size="sm">
                            {ROLE_LABEL[m.role] ?? m.role}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {/* Tab content: tac_dl */}
        {tab === "tac_dl" && (
          <>
            {tacDlQuery.isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">Ładowanie…</p>
            ) : (tacDlQuery.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Brak przypisań TAC ↔ DL.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Delivery Lead
                      </th>
                      <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        TAC
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(tacDlQuery.data ?? []).map((a, idx) => (
                      <tr key={`${a.tac_user_id}-${a.delivery_lead_user_id}-${idx}`}>
                        <td className="px-2 py-2 font-medium">{a.delivery_lead_name}</td>
                        <td className="px-2 py-2 text-muted-foreground">{a.tac_name}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {/* Tab content: sourcer_cat */}
        {tab === "sourcer_cat" && (
          <>
            {sourcerCatQuery.isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">Ładowanie…</p>
            ) : (sourcerCatQuery.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Brak przypisań Sourcer ↔ Kategoria.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Sourcer
                      </th>
                      <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Kategoria
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Priorytet
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(sourcerCatQuery.data ?? []).map((a, idx) => (
                      <tr key={`${a.user_id}-${a.category_id}-${idx}`}>
                        <td className="px-2 py-2 font-medium">{a.sourcer_name}</td>
                        <td className="px-2 py-2 text-muted-foreground">{a.category_name}</td>
                        <td className="px-2 py-2 text-center">
                          <Badge
                            variant={a.priority === 1 ? "success" : "neutral"}
                            size="sm"
                          >
                            P{a.priority}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        <p className="mt-4 text-xs text-muted-foreground italic">
          Read-only view. CRUD (assignments + reassignments) → core Nexus admin
          panel (Settings → Users).
        </p>
      </CardContent>
    </Card>
  );
}
