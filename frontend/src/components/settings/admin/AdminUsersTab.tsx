"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
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
  ShieldCheck,
  MoreHorizontal,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { adminApi, extractErrorMsg } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  extraPermissionsLabel,
  extraPermissionsTitle,
  isStalePolicyError,
  type UserPermissionsSave,
} from "@/lib/admin-permissions";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { useAuthStore, hasRole, type User } from "@/store/auth";
import {
  AdminUser,
  UserFormData,
  ROLE_LABELS,
  HR_PROGRAM_ROLE,
  formatDate,
} from "./types";
import { useHrProgram } from "@/lib/api/hr";
import { UserModal } from "./UserModal";
import { ResetPasswordModal } from "./ResetPasswordModal";
import { SystemTab } from "./SystemTab";
import { AuditLogTab } from "./AuditLogTab";
import { ImportTab } from "./ImportTab";
import { NewPersonSetupDialog } from "@/components/v2/dashboard/NewPersonSetupDialog";
import { AdminToolsGrid } from "./AdminToolsGrid";
import { DISCARD_PERMISSION_CHANGES, PermissionsTab } from "./PermissionsTab";
import {
  ADMIN_SUBTAB_PARAM,
  useAdminSubTab,
  type AdminSubTab as SubTab,
} from "@/lib/settings-admin-subtab";

interface AdminUsersTabProps {
  /** Ustawienia (22.09.2026): pokaż tylko te podzakładki i bez nagłówka
   *  „Panel administracyjny" — strona ma własny. Pozostałe podzakładki dalej
   *  otwierają się adresem `?sub=`. */
  embedded?: boolean;
  /** Podzakładka, gdy adres nie niesie `?sub=` (harness `/preview/permissions`). */
  defaultSubTab?: SubTab;
}

const EMBEDDED_SUBTABS: readonly SubTab[] = ["users", "permissions"];

/** Strona listy kont (makieta rundy 2, 21.10.2026: 252 konta na jednej stronie = 15 085 px). */
export const ADMIN_USERS_PAGE_SIZE = 25;

export type AdminUserStatus = "all" | "active" | "inactive";
export type AdminUserSort = "name" | "activity";

/**
 * Błędy drugiego żądania zapisu: dane konta już się zapisały, dodatkowe
 * uprawnienia nie. Okno ma wtedy zostać otwarte i powiedzieć, która połowa
 * przeszła. Błąd zostaje oryginalnym błędem axios (telemetria odróżnia po nim
 * odmowę 4xx od awarii) — ten zbiór pamięta tylko, z którego żądania pochodzi.
 */
const permissionStageFailures = new WeakSet<object>();

function failedOnPermissions(error: unknown): boolean {
  return typeof error === "object" && error !== null && permissionStageFailures.has(error);
}

function updateErrorMessage(error: unknown): string {
  if (!failedOnPermissions(error)) return extractErrorMsg(error);
  if (isStalePolicyError(error)) {
    return "Dane konta zostały zapisane, ale uprawnienia nie: ktoś zmienił zasady w międzyczasie. Wczytaliśmy aktualną wersję — zaznacz uprawnienia jeszcze raz i zapisz.";
  }
  return `Dane konta zostały zapisane, ale uprawnień nie udało się zapisać. ${apiErrorMessage(error, "Spróbuj ponownie za chwilę.")}`;
}

/**
 * Profil do „podglądu jako”: odpowiedź serwera w całości. Ręcznie przepisywana
 * lista pól gubiła `effective_action_access`, `can_delete_clients`
 * i `delivery_client_scope`, więc podgląd liczył uprawnienia z domyślnych ról
 * zamiast z tego, co konto naprawdę ma.
 */
export function impersonationProfile(profile: User): User {
  return {
    ...profile,
    roles: profile.roles?.length ? profile.roles : [profile.role],
    // Podgląd nie przechodzi za kogoś onboardingu ani wymuszonej zmiany hasła.
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    allowed_sections: [],
  };
}

export function AdminUsersTab({
  embedded = false,
  defaultSubTab,
}: AdminUsersTabProps = {}) {
  const { user } = useAuthStore();
  const impersonate = useAuthStore((s) => s.impersonate);
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  // `?sub=` w adresie (B42): F5 na „Uprawnieniach" nie wraca do „Użytkowników".
  const searchParams = useSearchParams();
  const [subTab, setSubTab] = useAdminSubTab(
    searchParams?.get(ADMIN_SUBTAB_PARAM) ?? defaultSubTab ?? null,
  );
  const [permissionsDirty, setPermissionsDirty] = useState(false);
  const [modal, setModal] = useState<"create" | "edit" | "reset" | null>(null);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);
  // W Ustawieniach domyślnie aktywni: 207 z 252 kont to byli pracownicy (prod 21.10.2026).
  const [statusFilter, setStatusFilter] = useState<AdminUserStatus>(embedded ? "active" : "all");
  const [idleOnly, setIdleOnly] = useState(false);
  const [pendingOnly, setPendingOnly] = useState(false);
  const [setupFor, setSetupFor] = useState<AdminUser | null>(null);
  const [sort, setSort] = useState<AdminUserSort>("name");
  const [page, setPage] = useState(0);
  // UAT M11-B02: przy ~240 kontach sama lista ze statusem nie wystarczała.
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const hrProgram = useHrProgram();

  const { data: users, isLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => adminApi.listUsers().then((r) => r.data as AdminUser[]),
    enabled: subTab === "users",
  });

  // Zmiana konta rusza też ekran uprawnień: liczbę osób z rolą i to, co role
  // dają tej osobie.
  const invalidateAccounts = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
      queryClient.invalidateQueries({ queryKey: ["admin-section-permissions"] }),
      queryClient.invalidateQueries({ queryKey: ["admin-user-permissions"] }),
    ]);

  const createMutation = useMutation({
    mutationFn: (data: UserFormData) =>
      adminApi.createUser({
        ...data,
        roles: data.roles,
      }),
    onSuccess: () => {
      void invalidateAccounts();
      setModal(null);
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({
      id,
      data,
      permissions,
    }: {
      id: number;
      data: Partial<UserFormData>;
      permissions: UserPermissionsSave | null;
    }) => {
      await adminApi.updateUser(id, {
        ...data,
        roles: data.roles,
      });
      if (!permissions) return;
      try {
        await adminApi.updateUserSectionPermissions(
          id,
          permissions.revision,
          permissions.changes,
          permissions.actionChanges,
        );
      } catch (reason) {
        if (typeof reason === "object" && reason !== null) {
          permissionStageFailures.add(reason);
        }
        throw reason;
      }
    },
    onSuccess: () => {
      void invalidateAccounts();
      setModal(null);
    },
    onError: (error) => {
      // Okno zostaje otwarte. Lista pod nim ma już nowe dane konta, a po 409
      // okno dostaje świeże zasady i świeże nadania tej osoby.
      if (failedOnPermissions(error)) void invalidateAccounts();
    },
  });

  const toggleActiveMutation = useMutation({
    mutationFn: (u: AdminUser) =>
      u.is_active
        ? adminApi.deactivateUser(u.id)
        : adminApi.updateUser(u.id, { is_active: true }),
    onSuccess: () => invalidateAccounts(),
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

  // Filtr po statusie, roli i wyszukiwarce + domyślne sortowanie alfabetyczne
  // po imieniu (locale pl).
  const displayedUsers = useMemo(
    () =>
      filterAdminUsers(users ?? [], {
        status: statusFilter,
        role: roleFilter,
        search,
        idle: idleOnly,
        pending: pendingOnly,
        sort,
      }),
    [users, statusFilter, roleFilter, search, idleOnly, pendingOnly, sort],
  );
  const counts = useMemo(() => adminUserCounts(users ?? []), [users]);
  const filtersActive =
    statusFilter !== "all" || roleFilter !== "all" || search.trim() !== "" || idleOnly || pendingOnly;
  const pageCount = Math.max(1, Math.ceil(displayedUsers.length / ADMIN_USERS_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pageUsers = displayedUsers.slice(
    currentPage * ADMIN_USERS_PAGE_SIZE,
    (currentPage + 1) * ADMIN_USERS_PAGE_SIZE,
  );
  // Każda zmiana filtra wraca na pierwszą stronę.
  const withFirstPage =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      set(value);
      setPage(0);
    };

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
      impersonate(impersonationProfile(res.data as User));
      // impersonate() przekierowuje na "/" po ustawieniu stanu.
    } catch (e) {
      showError(extractErrorMsg(e));
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
          can_delete_clients: data.can_delete_clients,
          ...(data.clear_microsoft_identity
            ? { clear_microsoft_identity: true }
            : {}),
        },
        permissions: data.permissions ?? null,
      });
    }
  };

  // Niezapisane przełączniki roli przepadają razem z zakładką — pytamy
  // w oknie aplikacji, zanim ją przełączymy.
  const selectSubTab = (next: SubTab) => {
    if (next === subTab) return;
    if (subTab !== "permissions" || !permissionsDirty) {
      setSubTab(next);
      return;
    }
    void askConfirm(DISCARD_PERMISSION_CHANGES).then((ok) => {
      if (ok) setSubTab(next);
    });
  };

  const addUserButton =
    subTab === "users" ? (
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
    ) : null;

  const subTabs = (
    <div className="min-w-0 overflow-x-auto overscroll-x-contain">
      <div
        className={`flex w-max gap-1 rounded-lg bg-muted p-1 ${embedded ? "" : "min-w-full"}`}
      >
        {[
          { id: "users" as SubTab, label: "Użytkownicy", icon: Users },
          { id: "permissions" as SubTab, label: "Uprawnienia", icon: ShieldCheck },
          { id: "system" as SubTab, label: "System", icon: Server },
          { id: "audit" as SubTab, label: "Log aktywności", icon: Activity },
          { id: "import" as SubTab, label: "Import CV", icon: Database },
          { id: "tools" as SubTab, label: "Narzędzia", icon: Wrench },
        ]
          .filter(({ id }) => !embedded || EMBEDDED_SUBTABS.includes(id))
          .map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => selectSubTab(id)}
              aria-pressed={subTab === id}
              className={`flex items-center gap-2 whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition-colors pointer-coarse:min-h-10 ${
                subTab === id
                  ? "bg-card text-foreground shadow-xs dark:bg-card"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </button>
          ))}
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      {confirmDialog}
      <NewPersonSetupDialog
        person={
          setupFor && setupFor.setup_pending_since
            ? {
                user_id: setupFor.id,
                name: setupFor.name,
                email: setupFor.email,
                since: setupFor.setup_pending_since,
                needs_decision: true,
                missing: [],
              }
            : null
        }
        isAdmin
        onClose={() => setSetupFor(null)}
      />
      {embedded ? (
        // W Ustawieniach zakładki i „Dodaj użytkownika” stoją w jednym rzędzie
        // (makieta 02.10.2026). Osobny, pusty rząd nad zakładkami zabierał
        // wysokość, której na laptopie 1280 × 720 brakuje przełącznikom.
        <div className="flex flex-wrap items-center justify-between gap-3">
          {subTabs}
          {addUserButton}
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <Shield className="w-6 h-6 text-primary" />
              <div>
                <h2 className="text-xl font-bold">Panel administracyjny</h2>
                <p className="text-sm text-muted-foreground dark:text-muted-foreground">
                  Zarządzaj użytkownikami, uprawnieniami i systemem
                </p>
              </div>
            </div>
            {addUserButton}
          </div>
          {subTabs}
        </>
      )}

      {subTab === "users" && (
        <div className="relative bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-x-auto">
          <div className="flex items-center gap-2 flex-wrap px-4 py-3 border-b border-border dark:border-border">
            <div className="inline-flex overflow-hidden rounded-lg border border-border" role="group" aria-label="Status">
              {([
                { id: "active", label: "Aktywni", count: counts.active },
                { id: "inactive", label: "Nieaktywni", count: counts.inactive },
                { id: "all", label: "Wszyscy", count: counts.all },
              ] as const).map(({ id, label, count }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => withFirstPage(setStatusFilter)(id)}
                  aria-pressed={statusFilter === id}
                  className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                    statusFilter === id
                      ? "bg-primary text-white"
                      : "bg-card text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                  {users ? (
                    <>
                      {" "}
                      <span className="tabular-nums opacity-80">{count}</span>
                    </>
                  ) : null}
                </button>
              ))}
            </div>
            {counts.idle > 0 ? (
              <button
                type="button"
                onClick={() => withFirstPage(setIdleOnly)(!idleOnly)}
                aria-pressed={idleOnly}
                title="Aktywne konta bez żadnej zapisanej aktywności"
                className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                  idleOnly
                    ? "border-warning bg-warning-muted text-warning-muted-foreground"
                    : "border-border bg-card text-muted-foreground hover:text-foreground"
                }`}
              >
                Bez aktywności · <span className="tabular-nums">{counts.idle}</span>
              </button>
            ) : null}
            {counts.pending > 0 || pendingOnly ? (
              // 0610: konta po pierwszym logowaniu, o których nikt nie zdecydował.
              <button
                type="button"
                onClick={() => withFirstPage(setPendingOnly)(!pendingOnly)}
                aria-pressed={pendingOnly}
                title="Konta po pierwszym logowaniu — nikt jeszcze nie zdecydował, kim jest ta osoba"
                className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                  pendingOnly
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-primary/40 bg-primary/5 text-primary hover:bg-primary/10"
                }`}
              >
                Do decyzji · <span className="tabular-nums">{counts.pending}</span>
              </button>
            ) : null}
            <input
              type="search"
              value={search}
              onChange={(e) => withFirstPage(setSearch)(e.target.value)}
              placeholder="Szukaj po imieniu lub e-mailu…"
              aria-label="Szukaj użytkowników"
              className="min-w-[14rem] rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            />
            <select
              value={roleFilter}
              onChange={(e) => withFirstPage(setRoleFilter)(e.target.value)}
              aria-label="Filtr roli"
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            >
              <option value="all">Wszystkie role</option>
              {Object.entries(ROLE_LABELS)
                .filter(([id]) => hrProgram || id !== HR_PROGRAM_ROLE)
                .map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
            <select
              value={sort}
              onChange={(e) => withFirstPage(setSort)(e.target.value as AdminUserSort)}
              aria-label="Kolejność"
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            >
              <option value="name">Sortuj: imię</option>
              <option value="activity">Sortuj: ostatnia aktywność</option>
            </select>
            <span className="ml-auto text-xs text-muted-foreground dark:text-muted-foreground">
              {displayedUsers.length}
              {filtersActive && users ? ` z ${users.length}` : ""}{" "}
              {displayedUsers.length === 1 && !filtersActive ? "użytkownik" : "użytkowników"}
            </span>
          </div>
          {isLoading ? (
            <div className="p-8 text-center text-muted-foreground dark:text-muted-foreground">Ładowanie...</div>
          ) : (
            // Siedem kolumn nie mieści się na telefonie: tabela przewija się
            // w poziomie, a kolumna „Imię” zostaje przyklejona (decyzja 23.09.2026).
            <div className="relative overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-border dark:border-border bg-muted dark:bg-card">
                  <th className="sticky left-0 z-10 bg-muted dark:bg-card px-4 py-3 text-left font-semibold text-foreground">Osoba</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Rola i uprawnienia</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Ostatnia aktywność</th>
                  <th className="px-4 py-3 text-right font-semibold text-foreground">
                    <span className="sr-only">Akcje</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {pageUsers.map((u) => (
                  <tr key={u.id} className="group hover:bg-muted dark:bg-card transition-colors">
                    <td className="sticky left-0 z-10 bg-card group-hover:bg-muted px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-foreground dark:text-foreground">{u.name}</span>
                        {!u.is_active ? (
                          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-destructive/15 text-destructive">
                            Nieaktywny
                          </span>
                        ) : null}
                        {u.is_active && u.setup_pending_since ? (
                          <button
                            type="button"
                            onClick={() => setSetupFor(u)}
                            className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                          >
                            Nowa · zdecyduj
                          </button>
                        ) : null}
                      </div>
                      <div className="text-xs text-muted-foreground">{u.email}</div>
                    </td>
                    <td className="px-4 py-2.5">
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
                        {(u.extra_permissions?.length ?? 0) > 0 && (
                          <span
                            className="px-2 py-0.5 rounded-full text-xs font-medium bg-warning-muted text-warning-muted-foreground"
                            title={extraPermissionsTitle(u.extra_permissions ?? [])}
                          >
                            {extraPermissionsLabel(u.extra_permissions?.length ?? 0)}
                          </span>
                        )}
                        {u.can_delete_clients && (
                          <span
                            className="px-2 py-0.5 rounded-full text-xs font-medium bg-destructive/10 text-destructive"
                            title="Imienne uprawnienie do usuwania klientów"
                          >
                            Usuwa klientów
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      {u.last_activity ? (
                        <span className="text-muted-foreground">
                          {formatDate(u.last_activity)}
                          {u.activity_count > 0 && <span className="ml-1">({u.activity_count})</span>}
                        </span>
                      ) : u.is_active ? (
                        <span className="rounded-full bg-warning-muted px-2 py-0.5 font-medium text-warning-muted-foreground">
                          bez aktywności
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      {/* Jedna podpisana akcja na wierzchu, rzadkie w menu — zamiast czterech ikon bez podpisu. */}
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setSelectedUser(u);
                            setModal("edit");
                          }}
                        >
                          <PencilLine className="mr-1.5 h-4 w-4" aria-hidden />
                          Edytuj
                        </Button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-sm" aria-label={`Więcej: ${u.name}`}>
                              <MoreHorizontal className="h-4 w-4" aria-hidden />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {u.is_active && u.id !== user.id ? (
                              <DropdownMenuItem onSelect={() => void handleImpersonate(u)}>
                                <Eye className="mr-2 h-4 w-4" aria-hidden />
                                Podgląd jako ten użytkownik
                              </DropdownMenuItem>
                            ) : null}
                            <DropdownMenuItem
                              onSelect={() => {
                                setSelectedUser(u);
                                setModal("reset");
                              }}
                            >
                              <KeyRound className="mr-2 h-4 w-4" aria-hidden />
                              Resetuj hasło
                            </DropdownMenuItem>
                            <DropdownMenuItem onSelect={() => toggleActiveMutation.mutate(u)}>
                              {u.is_active ? (
                                <UserX className="mr-2 h-4 w-4" aria-hidden />
                              ) : (
                                <UserCheck className="mr-2 h-4 w-4" aria-hidden />
                              )}
                              {u.is_active ? "Dezaktywuj" : "Aktywuj"}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </td>
                  </tr>
                ))}
                {displayedUsers.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                      {filtersActive
                        ? "Brak użytkowników pasujących do filtrów"
                        : "Brak użytkowników"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {pageCount > 1 ? (
              <div className="flex items-center gap-2 border-t border-border px-4 py-2">
                <span className="flex-1 text-xs text-muted-foreground">
                  {currentPage * ADMIN_USERS_PAGE_SIZE + 1}–
                  {Math.min((currentPage + 1) * ADMIN_USERS_PAGE_SIZE, displayedUsers.length)} z{" "}
                  {displayedUsers.length}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                >
                  Poprzednie
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={currentPage >= pageCount - 1}
                  onClick={() => setPage(currentPage + 1)}
                >
                  Następne
                </Button>
              </div>
            ) : null}
            </div>
          )}
        </div>
      )}

      {subTab === "system" && <SystemTab />}
      {subTab === "permissions" && (
        <PermissionsTab onDirtyChange={setPermissionsDirty} />
      )}
      {subTab === "import" && <ImportTab />}
      {subTab === "tools" && <AdminToolsGrid />}
      {subTab === "audit" && <AuditLogTab />}

      {(modal === "create" || modal === "edit") && (
        <UserModal
          initial={modal === "edit" ? selectedUser : null}
          onClose={() => {
            createMutation.reset();
            updateMutation.reset();
            setModal(null);
          }}
          onSave={handleSave}
          loading={createMutation.isPending || updateMutation.isPending}
          error={
            createMutation.error
              ? extractErrorMsg(createMutation.error)
              : updateMutation.error
                ? updateErrorMessage(updateMutation.error)
                : null
          }
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

function foldText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .toLowerCase();
}

/** Liczniki przy filtrach: aktywni, nieaktywni, wszyscy i aktywni bez żadnej aktywności. */
export function adminUserCounts(users: readonly AdminUser[]) {
  const active = users.filter((u) => u.is_active);
  return {
    all: users.length,
    active: active.length,
    inactive: users.length - active.length,
    idle: active.filter((u) => !u.last_activity).length,
    pending: active.filter((u) => u.setup_pending_since).length,
  };
}

/** Filtrowanie listy użytkowników po stronie klienta (lista to komplet kont).
 *  Rola pasuje po roli głównej ALBO dodatkowej; wyszukiwarka ignoruje wielkość
 *  liter i polskie znaki. `idle` = aktywne konta bez zapisanej aktywności.
 *  Kolejność: po imieniu (locale pl) albo od ostatniej aktywności (bez
 *  aktywności na końcu). */
export function filterAdminUsers(
  users: AdminUser[],
  {
    status,
    role,
    search,
    idle = false,
    pending = false,
    sort = "name",
  }: {
    status: AdminUserStatus;
    role: string;
    search: string;
    idle?: boolean;
    /** Tylko konta czekające na decyzję po pierwszym logowaniu (0610). */
    pending?: boolean;
    sort?: AdminUserSort;
  },
): AdminUser[] {
  const needle = foldText(search.trim());
  const list = users.filter((u) => {
    if (status === "active" && !u.is_active) return false;
    if (status === "inactive" && u.is_active) return false;
    if (idle && (!u.is_active || u.last_activity)) return false;
    if (pending && !u.setup_pending_since) return false;
    if (role !== "all" && u.role !== role && !(u.roles ?? []).includes(role)) {
      return false;
    }
    if (needle && !foldText(`${u.name} ${u.email}`).includes(needle)) return false;
    return true;
  });
  const byName = (a: AdminUser, b: AdminUser) => a.name.localeCompare(b.name, "pl");
  if (sort === "activity") {
    return [...list].sort((a, b) => {
      if (a.last_activity && b.last_activity) return b.last_activity.localeCompare(a.last_activity);
      if (a.last_activity) return -1;
      if (b.last_activity) return 1;
      return byName(a, b);
    });
  }
  return [...list].sort(byName);
}
