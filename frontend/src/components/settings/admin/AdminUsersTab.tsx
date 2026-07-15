"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Shield,
  Users,
  Server,
  PencilLine,
  UserX,
  UserCheck,
  KeyRound,
  Plus,
  Activity,
  Database,
  Wrench,
  Eye,
} from "lucide-react";
import { adminApi, extractErrorMsg } from "@/lib/api";
import { useAuthStore, hasRole, type UserRole } from "@/store/auth";
import {
  AdminUser,
  UserFormData,
  ROLE_LABELS,
  RECRUITER_ROLE_LABELS,
  formatDate,
} from "./types";
import { UserModal } from "./UserModal";
import { ResetPasswordModal } from "./ResetPasswordModal";
import { SystemTab } from "./SystemTab";
import { AuditLogTab } from "./AuditLogTab";
import { ImportTab } from "./ImportTab";
import { AdminToolsGrid } from "./AdminToolsGrid";

export type AdminSubTab = "users" | "system" | "audit" | "import" | "tools";

export function AdminUsersTab({
  initialSubTab = "users",
}: {
  initialSubTab?: AdminSubTab;
}) {
  const { user } = useAuthStore();
  const impersonate = useAuthStore((s) => s.impersonate);
  const queryClient = useQueryClient();
  const [subTab, setSubTab] = useState<AdminSubTab>(initialSubTab);
  const [modal, setModal] = useState<"create" | "edit" | "reset" | null>(null);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "inactive">("all");

  const { data: users, isLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => adminApi.listUsers().then((r) => r.data as AdminUser[]),
    enabled: subTab === "users",
  });

  const createMutation = useMutation({
    mutationFn: (data: UserFormData) =>
      adminApi.createUser({
        ...data,
        roles: data.roles,
        recruiter_role: data.recruiter_role || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setModal(null);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<UserFormData> }) =>
      adminApi.updateUser(id, {
        ...data,
        roles: data.roles,
        recruiter_role: data.recruiter_role || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setModal(null);
    },
  });

  const toggleActiveMutation = useMutation({
    mutationFn: (u: AdminUser) =>
      u.is_active
        ? adminApi.deactivateUser(u.id)
        : adminApi.updateUser(u.id, { is_active: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      adminApi.resetPassword(id, password),
    onSuccess: () => {
      setModal(null);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  const sendResetLinkMutation = useMutation({
    mutationFn: (id: number) => adminApi.sendResetLink(id),
    onSuccess: () => {
      setModal(null);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  // Filtr po statusie + domyślne sortowanie alfabetyczne po imieniu (locale pl).
  const displayedUsers = useMemo(() => {
    const list = (users ?? []).filter((u) =>
      statusFilter === "active"
        ? u.is_active
        : statusFilter === "inactive"
          ? !u.is_active
          : true,
    );
    return [...list].sort((a, b) => a.name.localeCompare(b.name, "pl"));
  }, [users, statusFilter]);

  if (!user) {
    return (
      <div className="p-8 flex items-center justify-center">
        <div className="animate-spin w-6 h-6 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }
  if (!hasRole(user, "admin")) return null;

  // „Podgląd jako użytkownik": pobierz autorytatywny profil (audyt po stronie
  // backendu), wejdź w tryb podglądu i przeładuj na stronę główną jako ten user.
  const handleImpersonate = async (u: AdminUser) => {
    try {
      const res = await adminApi.startImpersonation(u.id);
      const d = res.data;
      impersonate({
        id: d.id,
        email: d.email,
        name: d.name,
        role: d.role as UserRole,
        roles: (d.roles?.length ? d.roles : [d.role]) as UserRole[],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        allowed_sections: [],
      });
      // impersonate() przekierowuje na "/" po ustawieniu stanu.
    } catch (e) {
      alert(extractErrorMsg(e));
    }
  };

  const handleSave = (data: UserFormData) => {
    if (modal === "create") {
      createMutation.mutate(data);
    } else if (modal === "edit" && selectedUser) {
      updateMutation.mutate({
        id: selectedUser.id,
        data: {
          name: data.name,
          role: data.role,
          roles: data.roles,
          recruiter_role: data.recruiter_role,
        },
      });
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className="w-6 h-6 text-primary" />
          <div>
            <h2 className="text-xl font-bold">Panel administracyjny</h2>
            <p className="text-sm text-muted-foreground dark:text-muted-foreground">
              Zarządzaj użytkownikami i systemem
            </p>
          </div>
        </div>
        {subTab === "users" && (
          <button
            onClick={() => {
              setSelectedUser(null);
              setModal("create");
            }}
            className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" />
            Dodaj użytkownika
          </button>
        )}
      </div>

      <div className="flex gap-1 bg-muted dark:bg-muted p-1 rounded-lg w-fit">
        {[
          { id: "users" as AdminSubTab, label: "Użytkownicy", icon: Users },
          { id: "system" as AdminSubTab, label: "System", icon: Server },
          { id: "audit" as AdminSubTab, label: "Log aktywności", icon: Activity },
          { id: "import" as AdminSubTab, label: "Import CV", icon: Database },
          { id: "tools" as AdminSubTab, label: "Narzędzia", icon: Wrench },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setSubTab(id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              subTab === id
                ? "bg-card dark:bg-gray-600 text-foreground dark:text-foreground shadow-sm"
                : "text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-foreground"
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {subTab === "users" && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-x-auto">
          <div className="flex items-center gap-2 flex-wrap px-4 py-3 border-b border-border dark:border-border">
            <span className="text-sm text-muted-foreground dark:text-muted-foreground">Status:</span>
            {([
              { id: "all", label: "Wszyscy" },
              { id: "active", label: "Aktywni" },
              { id: "inactive", label: "Nieaktywni" },
            ] as const).map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setStatusFilter(id)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  statusFilter === id
                    ? "bg-primary text-white"
                    : "bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
            <span className="ml-auto text-xs text-muted-foreground dark:text-muted-foreground">
              {displayedUsers.length}{" "}
              {displayedUsers.length === 1 ? "użytkownik" : "użytkowników"}
            </span>
          </div>
          {isLoading ? (
            <div className="p-8 text-center text-muted-foreground dark:text-muted-foreground">Ładowanie...</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border dark:border-border bg-muted dark:bg-card">
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Imię</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Email</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Rola</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Rola rekrutacyjna</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Status</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Ostatnia aktywność</th>
                  <th className="px-4 py-3 text-right font-semibold text-foreground">Akcje</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {displayedUsers.map((u) => (
                  <tr key={u.id} className="hover:bg-muted dark:bg-card transition-colors">
                    <td className="px-4 py-3 font-medium text-foreground dark:text-foreground">{u.name}</td>
                    <td className="px-4 py-3 text-muted-foreground dark:text-muted-foreground">{u.email}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        <span
                          className="px-2 py-0.5 rounded-full text-xs font-medium bg-primary/15 text-primary"
                          title="Primary role"
                        >
                          {ROLE_LABELS[u.role] ?? u.role}
                        </span>
                        {(u.roles ?? [])
                          .filter((r) => r !== u.role)
                          .map((r) => (
                            <span
                              key={r}
                              className="px-2 py-0.5 rounded-full text-xs font-medium bg-muted text-muted-foreground"
                              title="Secondary role"
                            >
                              {ROLE_LABELS[r] ?? r}
                            </span>
                          ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground dark:text-muted-foreground">
                      {u.recruiter_role ? (RECRUITER_ROLE_LABELS[u.recruiter_role] ?? u.recruiter_role) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          u.is_active
                            ? "bg-green-100 text-green-700"
                            : "bg-destructive/15 text-destructive"
                        }`}
                      >
                        {u.is_active ? "Aktywny" : "Nieaktywny"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground dark:text-muted-foreground text-xs">
                      {formatDate(u.last_activity)}
                      {u.activity_count > 0 && (
                        <span className="ml-1 text-muted-foreground">({u.activity_count})</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {u.is_active && u.id !== user.id && (
                          <button
                            onClick={() => handleImpersonate(u)}
                            title="Podgląd jako ten użytkownik"
                            className="p-1.5 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg transition-colors"
                          >
                            <Eye className="w-4 h-4" />
                          </button>
                        )}

                        <button
                          onClick={() => {
                            setSelectedUser(u);
                            setModal("edit");
                          }}
                          title="Edytuj"
                          className="p-1.5 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg transition-colors"
                        >
                          <PencilLine className="w-4 h-4" />
                        </button>

                        <button
                          onClick={() => {
                            setSelectedUser(u);
                            setModal("reset");
                          }}
                          title="Resetuj hasło"
                          className="p-1.5 text-muted-foreground hover:text-amber-600 hover:bg-amber-50 rounded-lg transition-colors"
                        >
                          <KeyRound className="w-4 h-4" />
                        </button>

                        <button
                          onClick={() => toggleActiveMutation.mutate(u)}
                          title={u.is_active ? "Dezaktywuj" : "Aktywuj"}
                          className={`p-1.5 rounded-lg transition-colors ${
                            u.is_active
                              ? "text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                              : "text-muted-foreground hover:text-green-600 hover:bg-green-50"
                          }`}
                        >
                          {u.is_active ? <UserX className="w-4 h-4" /> : <UserCheck className="w-4 h-4" />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {displayedUsers.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                      Brak użytkowników{statusFilter !== "all" ? " o wybranym statusie" : ""}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      )}

      {subTab === "system" && <SystemTab />}
      {subTab === "import" && <ImportTab />}
      {subTab === "tools" && <AdminToolsGrid />}
      {subTab === "audit" && <AuditLogTab />}

      {(modal === "create" || modal === "edit") && (
        <UserModal
          initial={modal === "edit" ? selectedUser : null}
          onClose={() => setModal(null)}
          onSave={handleSave}
          loading={createMutation.isPending || updateMutation.isPending}
        />
      )}

      {modal === "reset" && selectedUser && (
        <ResetPasswordModal
          user={selectedUser}
          onClose={() => setModal(null)}
          onSaveManual={(pw) =>
            resetPasswordMutation.mutate({ id: selectedUser.id, password: pw })
          }
          onSendLink={() => sendResetLinkMutation.mutate(selectedUser.id)}
          loading={resetPasswordMutation.isPending || sendResetLinkMutation.isPending}
        />
      )}
    </div>
  );
}

export default AdminUsersTab;
