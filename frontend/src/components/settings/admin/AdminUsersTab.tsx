"use client";

import { useState } from "react";
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
} from "lucide-react";
import { adminApi } from "@/lib/api";
import { useAuthStore, hasRole } from "@/store/auth";
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

type SubTab = "users" | "system" | "audit" | "import" | "tools";

export function AdminUsersTab() {
  const { user } = useAuthStore();
  const queryClient = useQueryClient();
  const [subTab, setSubTab] = useState<SubTab>("users");
  const [modal, setModal] = useState<"create" | "edit" | "reset" | null>(null);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);

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

  if (!user) {
    return (
      <div className="p-8 flex items-center justify-center">
        <div className="animate-spin w-6 h-6 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }
  if (!hasRole(user, "admin")) return null;

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
          { id: "users" as SubTab, label: "Użytkownicy", icon: Users },
          { id: "system" as SubTab, label: "System", icon: Server },
          { id: "audit" as SubTab, label: "Log aktywności", icon: Activity },
          { id: "import" as SubTab, label: "Import CV", icon: Database },
          { id: "tools" as SubTab, label: "Narzędzia", icon: Wrench },
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
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-hidden">
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
                {(users ?? []).map((u) => (
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
                      {u.recruiter_role ? (RECRUITER_ROLE_LABELS[u.recruiter_role] ?? u.recruiter_role) : "–"}
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
                {users?.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                      Brak użytkowników
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
