"use client";

/**
 * Harness ekranu Ustawienia → Zespół i dostęp → „Osoby i role” (0410) —
 * prawdziwy `AdminUsersTab` na zasianym cache react-query, ZERO zapytań
 * (strażnik: `harness-seeds.test.ts`); sieć odcina interceptor, zapisy także
 * layout `/preview`.
 *
 * Warianty:
 * - bez parametrów — zakładka „Uprawnienia”, rola Finanse (dziewięć przełączników);
 * - `?tab=users` — lista osób z plakietką „+N uprawnienie”; ołówek otwiera okno
 *   każdej osoby (wszystkie są zasiane, jedna ma stare ograniczenia);
 * - `?modal=1` — okno „Edytuj użytkownika” fikcyjnej Talent Community Manager
 *   z jednym dodatkowym uprawnieniem.
 *
 * Osoby są zmyślone. Role i uprawnienia to katalog z repo
 * (`lib/permission-catalog.json`) w stanie domyślnym.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { AdminUsersTab } from "@/components/settings/admin/AdminUsersTab";
import { UserModal } from "@/components/settings/admin/UserModal";
import type { AdminUser } from "@/components/settings/admin/types";
import type {
  AdminPermissionsSnapshot,
  AdminRolePermissions,
  AdminUserPermissionsResponse,
} from "@/lib/admin-permissions";
import { api } from "@/lib/api";
import {
  PERMISSIONS,
  PERMISSION_GROUPS,
  PERMISSION_KEYS,
  closePermissions,
  deriveSections,
  impliedBy,
  type Permission,
} from "@/lib/permissions";
import { useAuthStore, type UserRole } from "@/store/auth";

const REVISION = 6;

interface PreviewPerson {
  id: number;
  name: string;
  roles: UserRole[];
  active?: boolean;
  grants?: Permission[];
  restrictions?: Permission[];
  legacyCaps?: AdminUserPermissionsResponse["user"]["legacy_section_caps"];
}

const PEOPLE: PreviewPerson[] = [
  { id: 1, name: "Aniela Administrująca", roles: ["admin"] },
  { id: 2, name: "Emil Fikcyjny", roles: ["finance"] },
  { id: 3, name: "Hanna Makietowa", roles: ["head_of_recruitment"] },
  { id: 4, name: "Igor Próbny", roles: ["delivery_lead"] },
  { id: 5, name: "Lena Szablonowa", roles: ["delivery_lead", "recruiter"] },
  {
    id: 6,
    name: "Celina Wzorcowa",
    roles: ["talent_community_manager"],
    grants: ["contracts_orders_edit"],
  },
  {
    id: 7,
    name: "Oskar Podglądowy",
    roles: ["talent_community_manager"],
    restrictions: ["contract_status"],
    legacyCaps: { delivery: "read" },
  },
  {
    id: 8,
    name: "Borys Przykładowy",
    roles: ["recruiter"],
    grants: ["delivery_view", "amounts_view"],
  },
  { id: 9, name: "Daria Testowa", roles: ["recruiter"] },
  { id: 10, name: "Nela Atrapowa", roles: ["recruiter"], active: false },
  { id: 11, name: "Tymon Zmyślony", roles: ["trainee"] },
];

const MODAL_PERSON_ID = 6;

const ALL_ROLES: UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "recruiter",
  "user",
  "trainee",
];

const UNGRANTABLE: UserRole[] = ["admin", "user", "trainee"];

function roleGrants(role: UserRole): Permission[] {
  if (role === "admin") return [...PERMISSION_KEYS];
  return PERMISSIONS.filter((permission) =>
    permission.default_roles.includes(role),
  ).map((permission) => permission.key);
}

function roleEntry(role: UserRole): AdminRolePermissions {
  const granted = roleGrants(role);
  const effective = closePermissions(granted);
  const sections = deriveSections(effective);
  const working = role === "trainee" ? "none" : role === "user" ? "read" : "write";
  return {
    role,
    users_count: PEOPLE.filter(
      (person) => person.active !== false && person.roles.includes(role),
    ).length,
    grantable: !UNGRANTABLE.includes(role),
    locked: role === "admin",
    permissions: {
      sourcing: working,
      pipeline: working,
      delivery: sections.delivery,
      insights: role === "trainee" ? "none" : "read",
      finance: sections.finance,
      system_admin: role === "admin" ? "write" : "none",
    },
    action_permissions: { b2b_contract_generator: "manage" },
    named: Object.fromEntries(
      PERMISSION_KEYS.map((key) => [
        key,
        {
          granted: granted.includes(key),
          effective: effective.has(key),
          implied_by: impliedBy(key, granted),
        },
      ]),
    ),
  };
}

const SNAPSHOT: AdminPermissionsSnapshot = {
  revision: REVISION,
  derived_sections: ["delivery", "finance"],
  permission_groups: PERMISSION_GROUPS.map((group) => ({
    key: group.key,
    label: group.label,
    permissions: [...group.permissions],
  })),
  permissions: PERMISSIONS.map((permission) => ({
    key: permission.key,
    label: permission.label,
    group: permission.group,
    requires: [...permission.requires],
    default_roles: [...permission.default_roles],
  })),
  roles: ALL_ROLES.map(roleEntry),
};

function fromRoles(person: PreviewPerson): Set<Permission> {
  return closePermissions(person.roles.flatMap(roleGrants));
}

function accountRow(person: PreviewPerson): AdminUser {
  const given = fromRoles(person);
  return {
    id: person.id,
    email: `konto${person.id}@example.com`,
    name: person.name,
    role: person.roles[0],
    roles: person.roles,
    is_active: person.active !== false,
    can_delete_clients: person.id === 4,
    extra_permissions: (person.grants ?? []).filter((key) => !given.has(key)),
    activity_count: person.id * 3,
    last_activity: person.active === false ? null : "2026-10-01T15:20:00",
    created_at: "2026-01-12T09:00:00",
  };
}

function personPermissions(person: PreviewPerson): AdminUserPermissionsResponse {
  const given = fromRoles(person);
  const grants = person.grants ?? [];
  const restrictions = person.restrictions ?? [];
  const effective = closePermissions([
    ...[...given].filter((key) => !restrictions.includes(key)),
    ...grants,
  ]);
  return {
    revision: REVISION,
    user: {
      user_id: person.id,
      name: person.name,
      role: person.roles[0],
      roles: person.roles,
      locked: person.roles.includes("admin"),
      grantable: !person.roles.some((role) => UNGRANTABLE.includes(role)),
      role_permissions: PERMISSION_KEYS.filter((key) => given.has(key)),
      grants,
      restrictions,
      effective: PERMISSION_KEYS.filter((key) => effective.has(key)),
      legacy_section_caps: person.legacyCaps ?? {},
    },
  };
}

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, retryOnMount: false, staleTime: Infinity },
    },
  });
  qc.setQueryData(["admin-users"], PEOPLE.map(accountRow));
  qc.setQueryData(["admin-section-permissions"], SNAPSHOT);
  for (const person of PEOPLE) {
    qc.setQueryData(["admin-user-permissions", person.id], personPermissions(person));
  }
  return qc;
}

/** Bezpiecznik: nawet kliknięcie „podgląd jako” albo „Zapisz” nie wyśle żądania. */
function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(new Error("Harness /preview/permissions nie wysyła zapytań."), {
          isAxiosError: true,
          code: "ERR_PREVIEW_OFFLINE",
        }),
      ),
    ),
  );
  useEffect(() => () => api.interceptors.request.eject(interceptorId), [interceptorId]);
}

function PermissionsPreview() {
  useNetworkBlocked();
  const params = useSearchParams();
  const showUsers = params?.get("tab") === "users" || params?.has("modal");
  const [qc] = useState(seededClient);
  const [ready, setReady] = useState(false);
  const [modalOpen, setModalOpen] = useState(() => params?.has("modal") ?? false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    // Ekran jest tylko dla administratora i czyta go z produkcyjnego store'a.
    useAuthStore.setState({
      user: {
        id: 1,
        email: "konto1@example.com",
        name: "Aniela Administrująca",
        role: "admin",
        roles: ["admin"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      },
      hydrated: true,
    });
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  const modalPerson = PEOPLE.find((person) => person.id === MODAL_PERSON_ID);
  return (
    <ToastProvider>
      <QueryClientProvider client={qc}>
        <main className="mx-auto max-w-7xl space-y-6 bg-background p-4 sm:p-6">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Osoby i role</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Dodaj osobę, zmień jej rolę i dostęp albo wyłącz konto.
            </p>
          </div>
          <AdminUsersTab embedded defaultSubTab={showUsers ? "users" : "permissions"} />
          {modalOpen && modalPerson ? (
            <UserModal
              initial={accountRow(modalPerson)}
              onClose={() => setModalOpen(false)}
              onSave={() => setNote("Podgląd nie zapisuje zmian.")}
              loading={false}
              error={note}
            />
          ) : null}
        </main>
      </QueryClientProvider>
    </ToastProvider>
  );
}

export default function PermissionsPreviewPage() {
  return (
    <Suspense fallback={null}>
      <PermissionsPreview />
    </Suspense>
  );
}
