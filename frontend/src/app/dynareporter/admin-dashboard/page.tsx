"use client";

/**
 * DynaReporter Admin dashboard.
 *
 * Port `/admin` z artur-t-96/InfraReporter (`client/src/pages/AdminPanel.tsx`).
 *
 * Zawiera 3 zakładki:
 * - **Userzy** — wszystkie konta nexus z DR legacy mapping + KPI completeness
 * - **Upload history** — dr_upload_history (audyt uploadów Excel)
 * - **Audit log** — dr_data_audit_log (zmiany w bazie)
 *
 * Tylko rola `admin` może wyświetlać (per-endpoint gating).
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shield, Users, Upload, History } from "lucide-react";
import { dynareporterAdminApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type Tab = "users" | "uploads" | "audit";

function formatDate(d: string): string {
  try {
    return new Date(d).toLocaleString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return d;
  }
}

export default function AdminDashboardPage() {
  const { user, hydrated } = useAuthStore();
  const [tab, setTab] = useState<Tab>("users");
  const queryEnabled = hydrated && !!user && user.role === "admin";

  const usersQuery = useQuery({
    queryKey: ["dr-admin-users"],
    queryFn: () => dynareporterAdminApi.users(),
    staleTime: 60_000,
    enabled: queryEnabled && tab === "users",
  });
  const uploadsQuery = useQuery({
    queryKey: ["dr-admin-uploads"],
    queryFn: () => dynareporterAdminApi.uploadHistory(),
    staleTime: 60_000,
    enabled: queryEnabled && tab === "uploads",
  });
  const auditQuery = useQuery({
    queryKey: ["dr-admin-audit"],
    queryFn: () => dynareporterAdminApi.auditLog(),
    staleTime: 60_000,
    enabled: queryEnabled && tab === "audit",
  });

  if (!hydrated) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie sesji…</div>;
  }
  if (!user) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Zaloguj się żeby zobaczyć DynaReporter Admin.
      </div>
    );
  }
  if (user.role !== "admin") {
    return (
      <div className="p-8">
        <Card>
          <CardContent className="py-8">
            <h2 className="font-semibold text-destructive">Brak dostępu</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              DynaReporter Admin wymaga roli <code>admin</code>. Twoja rola:{" "}
              <code>{user.role}</code>.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4 sm:p-6">
      {/* Header */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-r from-rose-700 to-rose-900 rounded-lg">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold">DynaReporter Admin</h1>
              <p className="text-sm text-muted-foreground">
                Zarządzanie userami DR, historia uploadów Excel + audit log.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        <TabButton
          active={tab === "users"}
          onClick={() => setTab("users")}
          icon={<Users className="w-4 h-4" />}
          label="Userzy"
        />
        <TabButton
          active={tab === "uploads"}
          onClick={() => setTab("uploads")}
          icon={<Upload className="w-4 h-4" />}
          label="Upload history"
        />
        <TabButton
          active={tab === "audit"}
          onClick={() => setTab("audit")}
          icon={<History className="w-4 h-4" />}
          label="Audit log"
        />
      </div>

      {/* Users tab */}
      {tab === "users" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Userzy ({usersQuery.data?.length ?? "…"})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {usersQuery.isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Ładowanie…
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Name
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Email
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Role
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Allowed sections
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        DR legacy ID
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        KPI wpisów
                      </th>
                      <th className="px-3 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(usersQuery.data ?? []).map((u) => (
                      <tr
                        key={u.id}
                        className={`hover:bg-muted/40 ${!u.is_active ? "opacity-60" : ""}`}
                      >
                        <td className="px-3 py-2 text-sm font-medium">{u.name}</td>
                        <td className="px-3 py-2 text-sm text-muted-foreground">
                          {u.email}
                        </td>
                        <td className="px-3 py-2 text-sm">
                          <Badge variant="neutral">{u.role}</Badge>
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {u.allowed_sections.length === 0 ? (
                            <span className="text-muted-foreground">—</span>
                          ) : (
                            <div className="flex flex-wrap gap-1">
                              {u.allowed_sections.map((s) => (
                                <Badge key={s} variant="soft" size="sm">
                                  {s}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-sm">
                          {u.dynareporter_legacy_id ?? (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-sm">
                          {u.kpi_entries_count}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {u.is_active ? (
                            <Badge variant="success" size="sm">
                              aktywny
                            </Badge>
                          ) : (
                            <Badge variant="neutral" size="sm">
                              nieaktywny
                            </Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Uploads tab */}
      {tab === "uploads" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Upload history ({uploadsQuery.data?.length ?? "…"})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {uploadsQuery.isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Ładowanie…
              </p>
            ) : uploadsQuery.data?.length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Brak uploadów. Migracja z DR nie zawierała historii uploads
                (dr_upload_history = 0 wpisów).
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Plik
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Typ
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Uploadowany przez
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        Rekordów
                      </th>
                      <th className="px-3 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Status
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Data
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(uploadsQuery.data ?? []).map((u) => (
                      <tr key={u.id} className="hover:bg-muted/40">
                        <td className="px-3 py-2 text-sm font-medium">
                          {u.file_name}
                        </td>
                        <td className="px-3 py-2 text-sm">
                          <Badge variant="neutral" size="sm">
                            {u.file_type}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-sm text-muted-foreground">
                          {u.uploaded_by_name}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-sm">
                          {u.records_count}
                        </td>
                        <td className="px-3 py-2 text-center">
                          <Badge
                            variant={u.status === "success" ? "success" : "danger"}
                            size="sm"
                          >
                            {u.status}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">
                          {formatDate(u.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Audit log tab */}
      {tab === "audit" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Audit log (ostatnie {auditQuery.data?.length ?? "…"} zmian)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {auditQuery.isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Ładowanie…
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Tabela
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Akcja
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        Rekordów
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Przez
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Kiedy
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(auditQuery.data ?? []).map((a) => (
                      <tr key={a.id} className="hover:bg-muted/40">
                        <td className="px-3 py-2 text-sm font-mono">
                          {a.table_name}
                        </td>
                        <td className="px-3 py-2 text-sm">
                          <Badge
                            variant={
                              a.action.includes("DELETE") ? "danger" : "neutral"
                            }
                            size="sm"
                          >
                            {a.action}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-sm">
                          {a.records_count}
                        </td>
                        <td className="px-3 py-2 text-sm text-muted-foreground">
                          {a.performed_by_name ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">
                          {formatDate(a.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
        active
          ? "text-foreground border-primary"
          : "text-muted-foreground border-transparent hover:text-foreground"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}
