"use client";

import {
  useEffect,
  useMemo,
  useState,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LockKeyhole,
  RotateCcw,
  Save,
  ShieldCheck,
  UserRoundCog,
  UsersRound,
} from "lucide-react";

import { useToast } from "@/components/Toast";
import { AppModal } from "@/components/ds/AppModal";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { Alert } from "@/components/ui/alert";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { adminApi, extractErrorMsg } from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import {
  ALL_USER_ROLES,
  PRODUCT_SECTIONS,
  type ProductSection,
  type RoleSectionPermissionChange,
  type RoleSectionPermissions,
  type SectionAccess,
  type SectionPermissionsResponse,
  type UserSectionOverrideAccess,
  type UserSectionPermissionChange,
  type UserSectionPermissions,
} from "@/lib/section-access";
import type { UserRole } from "@/store/auth";
import { ROLE_LABELS } from "./types";

type PermissionsView = "roles" | "users";
type RoleDraft = Record<string, Partial<Record<ProductSection, SectionAccess>>>;
type UserDraft = Record<ProductSection, UserSectionOverrideAccess>;
type UserDraftState = {
  key: string;
  revision: number;
  values: UserDraft;
} | null;

const SECTION_LABELS: Record<
  ProductSection,
  { label: string; short: string; description: string }
> = {
  sourcing: {
    label: "Sourcing",
    short: "Sourcing",
    description: "Kandydaci, talenty i narzędzia sourcingowe",
  },
  pipeline: {
    label: "Pipeline",
    short: "Pipeline",
    description: "Rekrutacje i kalendarz",
  },
  delivery: {
    label: "Delivery",
    short: "Delivery",
    description: "Klienci, kontrakty i realizacja",
  },
  insights: {
    label: "Insights",
    short: "Insights",
    description: "Raporty i analityka",
  },
  finance: {
    label: "Finanse",
    short: "Finanse",
    description: "Wyniki, rozliczenia i stawki",
  },
  system_admin: {
    label: "Administracja techniczna",
    short: "System",
    description: "Konfiguracja i narzędzia administratora",
  },
};

const ACCESS_LABELS: Record<SectionAccess, string> = {
  none: "Brak",
  read: "Odczyt",
  write: "Odczyt i zapis",
};

const OVERRIDE_LABELS: Record<UserSectionOverrideAccess, string> = {
  inherit: "Dziedzicz z roli",
  ...ACCESS_LABELS,
};

const ACCESS_BADGE_VARIANTS: Record<SectionAccess, BadgeProps["variant"]> = {
  none: "neutral",
  read: "info",
  write: "success",
};

function responseStatus(error: unknown): number | null {
  const status = (error as { response?: { status?: unknown } })?.response?.status;
  return typeof status === "number" ? status : null;
}

function emptyUserDraft(
  user: UserSectionPermissions,
): UserDraft {
  return Object.fromEntries(
    PRODUCT_SECTIONS.map((section) => [
      section,
      user.overrides[section] ?? "inherit",
    ]),
  ) as UserDraft;
}

function roleDraftFromPolicy(policy: SectionPermissionsResponse): RoleDraft {
  return Object.fromEntries(
    policy.roles.map((entry) => [entry.role, { ...entry.permissions }]),
  );
}

function policyByRole(
  policy: SectionPermissionsResponse,
): Map<UserRole, RoleSectionPermissions> {
  return new Map(policy.roles.map((entry) => [entry.role, entry]));
}

function inheritedAccess(
  policy: SectionPermissionsResponse,
  user: UserSectionPermissions,
  section: ProductSection,
): SectionAccess {
  const rank: Record<SectionAccess, number> = { none: 0, read: 1, write: 2 };
  const byRole = policyByRole(policy);
  const roles = new Set<UserRole>([user.role, ...(user.roles ?? [])]);
  let effective: SectionAccess = "none";
  for (const role of roles) {
    const candidate = byRole.get(role)?.permissions[section] ?? "none";
    if (rank[candidate] > rank[effective]) effective = candidate;
  }
  return effective;
}

function AccessBadge({ access }: { access: SectionAccess }) {
  return (
    <Badge variant={ACCESS_BADGE_VARIANTS[access]}>
      {ACCESS_LABELS[access]}
    </Badge>
  );
}

interface AccessSelectProps {
  value: SectionAccess;
  onChange: (value: SectionAccess) => void;
  disabled?: boolean;
  ariaLabel: string;
}

function AccessSelect({ value, onChange, disabled, ariaLabel }: AccessSelectProps) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value as SectionAccess)}
      disabled={disabled}
      aria-label={ariaLabel}
      className="h-9 w-full min-w-32 rounded-md border border-input bg-background px-2 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
    >
      <option value="none">Brak</option>
      <option value="read">Odczyt</option>
      <option value="write">Odczyt i zapis</option>
    </select>
  );
}

interface OverrideSelectProps {
  value: UserSectionOverrideAccess;
  onChange: (value: UserSectionOverrideAccess) => void;
  disabled?: boolean;
  ariaLabel: string;
}

function OverrideSelect({
  value,
  onChange,
  disabled,
  ariaLabel,
}: OverrideSelectProps) {
  return (
    <select
      value={value}
      onChange={(event) =>
        onChange(event.target.value as UserSectionOverrideAccess)
      }
      disabled={disabled}
      aria-label={ariaLabel}
      className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
    >
      <option value="inherit">Dziedzicz z roli</option>
      <option value="none">Brak</option>
      <option value="read">Odczyt</option>
      <option value="write">Odczyt i zapis</option>
    </select>
  );
}

function ChangeList({
  changes,
}: {
  changes: Array<{ key: string; title: string; before: string; after: string }>;
}) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {changes.map((change) => (
        <li key={change.key} className="px-3 py-2.5 text-sm">
          <p className="font-medium text-foreground">{change.title}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {change.before} <span aria-hidden>→</span> {change.after}
          </p>
        </li>
      ))}
    </ul>
  );
}

function RolePermissionsEditor({
  policy,
}: {
  policy: SectionPermissionsResponse;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [draft, setDraft] = useState<RoleDraft>(() =>
    roleDraftFromPolicy(policy),
  );
  const [draftRevision, setDraftRevision] = useState(policy.revision);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [conflict, setConflict] = useState(false);

  const orderedRoles = useMemo(() => {
    const order = new Map(ALL_USER_ROLES.map((role, index) => [role, index]));
    return [...policy.roles].sort(
      (a, b) => (order.get(a.role) ?? 999) - (order.get(b.role) ?? 999),
    );
  }, [policy.roles]);

  const changes = useMemo<RoleSectionPermissionChange[]>(() => {
    const result: RoleSectionPermissionChange[] = [];
    for (const rolePolicy of policy.roles) {
      for (const section of PRODUCT_SECTIONS) {
        const next = draft[rolePolicy.role]?.[section];
        if (next && next !== rolePolicy.permissions[section]) {
          result.push({ role: rolePolicy.role, section, access: next });
        }
      }
    }
    return result;
  }, [draft, policy.roles]);

  useEffect(() => {
    if (draftRevision === policy.revision) return;

    // This draft belongs to an older snapshot. Never silently rebase it onto
    // the new revision or leave an open confirmation modal able to submit it.
    const staleDraftDiffersFromCurrentPolicy = changes.length > 0;
    setConfirmOpen(false);
    setDraft(roleDraftFromPolicy(policy));
    setDraftRevision(policy.revision);
    setConflict((current) => current || staleDraftDiffersFromCurrentPolicy);
  }, [changes.length, draftRevision, policy]);

  const mutation = useMutation({
    mutationFn: () =>
      adminApi.updateRoleSectionPermissions(draftRevision, changes),
    onSuccess: async (response) => {
      setConfirmOpen(false);
      setConflict(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["admin-section-permissions"] }),
        queryClient.invalidateQueries({
          queryKey: ["admin-user-section-permissions"],
        }),
      ]);
      showSuccess(
        response.data.invalidated_users > 0
          ? `Zapisano uprawnienia ról. ${response.data.invalidated_users} użytkowników zaloguje się ponownie.`
          : "Zapisano uprawnienia ról.",
      );
    },
    onError: async (error) => {
      setConfirmOpen(false);
      if (responseStatus(error) === 409) {
        setConflict(true);
        await queryClient.invalidateQueries({
          queryKey: ["admin-section-permissions"],
        });
        showError(
          "Ktoś zmienił uprawnienia w międzyczasie. Wczytano aktualną wersję — sprawdź zmiany ponownie.",
        );
        return;
      }
      showError(extractErrorMsg(error));
    },
  });

  const resetDraft = () => {
    setDraft(roleDraftFromPolicy(policy));
    setDraftRevision(policy.revision);
    setConflict(false);
  };

  const setAccess = (
    role: UserRole,
    section: ProductSection,
    access: SectionAccess,
  ) => {
    setDraft((current) => ({
      ...current,
      [role]: { ...current[role], [section]: access },
    }));
  };

  const confirmationChanges = changes.map((change) => {
    const previous = policyByRole(policy).get(change.role)?.permissions[
      change.section
    ] ?? "none";
    return {
      key: `${change.role}:${change.section}`,
      title: `${ROLE_LABELS[change.role] ?? change.role} · ${SECTION_LABELS[change.section].label}`,
      before: ACCESS_LABELS[previous],
      after: ACCESS_LABELS[change.access],
    };
  });

  return (
    <div className="space-y-4">
      {conflict ? (
        <Alert
          variant="warning"
          title="Wczytano nowszą wersję zasad"
          description="Poprzedni zapis nie został wykonany. Sprawdź aktualną macierz przed ponowną edycją."
        />
      ) : null}

      <div className="hidden md:block">
        <Table density="compact" className="min-w-[920px]">
          <TableHeader>
            <TableRow>
              <TableHead className="sticky left-0 z-10 min-w-52 bg-background">
                Rola
              </TableHead>
              {PRODUCT_SECTIONS.map((section) => (
                <TableHead key={section} className="min-w-36 normal-case tracking-normal">
                  <span className="text-xs text-foreground">
                    {SECTION_LABELS[section].short}
                  </span>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {orderedRoles.map((rolePolicy) => {
              const rowLocked = rolePolicy.locked || rolePolicy.role === "admin";
              return (
                <TableRow key={rolePolicy.role}>
                  <TableCell className="sticky left-0 z-10 bg-card">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">
                        {ROLE_LABELS[rolePolicy.role] ?? rolePolicy.role}
                      </span>
                      {rowLocked ? (
                        <LockKeyhole
                          className="size-3.5 text-muted-foreground"
                          aria-label="Rola chroniona"
                        />
                      ) : null}
                    </div>
                  </TableCell>
                  {PRODUCT_SECTIONS.map((section) => {
                    const locked = rowLocked || section === "system_admin";
                    return (
                      <TableCell key={section}>
                        <AccessSelect
                          value={
                            draft[rolePolicy.role]?.[section] ??
                            rolePolicy.permissions[section]
                          }
                          onChange={(access) =>
                            setAccess(rolePolicy.role, section, access)
                          }
                          disabled={locked}
                          ariaLabel={`${ROLE_LABELS[rolePolicy.role] ?? rolePolicy.role}: ${SECTION_LABELS[section].label}`}
                        />
                      </TableCell>
                    );
                  })}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="space-y-3 md:hidden">
        {orderedRoles.map((rolePolicy) => {
          const rowLocked = rolePolicy.locked || rolePolicy.role === "admin";
          return (
            <section
              key={rolePolicy.role}
              className="rounded-xl border border-border bg-card p-4"
            >
              <div className="mb-3 flex items-center gap-2">
                <h3 className="font-semibold text-foreground">
                  {ROLE_LABELS[rolePolicy.role] ?? rolePolicy.role}
                </h3>
                {rowLocked ? (
                  <Badge variant="neutral">
                    <LockKeyhole className="size-3" aria-hidden /> Chroniona
                  </Badge>
                ) : null}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {PRODUCT_SECTIONS.map((section) => (
                  <label key={section} className="space-y-1.5">
                    <span className="text-xs font-medium text-muted-foreground">
                      {SECTION_LABELS[section].label}
                    </span>
                    <AccessSelect
                      value={
                        draft[rolePolicy.role]?.[section] ??
                        rolePolicy.permissions[section]
                      }
                      onChange={(access) =>
                        setAccess(rolePolicy.role, section, access)
                      }
                      disabled={rowLocked || section === "system_admin"}
                      ariaLabel={`${ROLE_LABELS[rolePolicy.role] ?? rolePolicy.role}: ${SECTION_LABELS[section].label}`}
                    />
                  </label>
                ))}
              </div>
            </section>
          );
        })}
      </div>

      <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card/95 p-3 shadow-sm backdrop-blur-sm">
        <p className="text-sm text-muted-foreground">
          {changes.length === 0
            ? "Brak niezapisanych zmian"
            : `${changes.length} ${changes.length === 1 ? "zmiana" : "zmian"} do zapisania`}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={resetDraft}
            disabled={changes.length === 0 || mutation.isPending}
          >
            <RotateCcw className="size-4" aria-hidden /> Cofnij
          </Button>
          <Button
            onClick={() => setConfirmOpen(true)}
            disabled={changes.length === 0}
            loading={mutation.isPending}
          >
            <Save className="size-4" aria-hidden /> Zapisz zmiany
          </Button>
        </div>
      </div>

      <AppModal
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Potwierdź zmianę uprawnień ról"
        description="Zmiana wpłynie na wszystkich aktywnych użytkowników posiadających te role. Ich bieżące sesje zostaną zakończone, więc zalogują się ponownie."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Anuluj
            </Button>
            <Button
              onClick={() => mutation.mutate()}
              loading={mutation.isPending}
            >
              Potwierdź i zapisz
            </Button>
          </>
        }
      >
        <ChangeList changes={confirmationChanges} />
      </AppModal>
    </div>
  );
}

function UserPermissionsEditor({
  policy,
  active,
}: {
  policy: SectionPermissionsResponse;
  active: boolean;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search.trim(), 300);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [draftState, setDraftState] = useState<UserDraftState>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [conflict, setConflict] = useState(false);

  const usersQuery = useQuery({
    queryKey: ["admin-user-section-permissions", debouncedSearch],
    queryFn: () =>
      adminApi
        .searchUserSectionPermissions(debouncedSearch)
        .then((response) => response.data),
    enabled: active,
  });

  const users = usersQuery.data?.users ?? [];
  const selectedUser =
    users.find((entry) => entry.user_id === selectedUserId) ?? users[0] ?? null;
  const selectedDraftKey = selectedUser
    ? `${selectedUser.user_id}:${usersQuery.data?.revision ?? policy.revision}`
    : null;
  const draft = selectedUser
    ? draftState?.key === selectedDraftKey
      ? draftState.values
      : emptyUserDraft(selectedUser)
    : null;

  const changes = useMemo<UserSectionPermissionChange[]>(() => {
    if (!selectedUser || !draft) return [];
    return PRODUCT_SECTIONS.flatMap((section) => {
      const before = selectedUser.overrides[section] ?? "inherit";
      const after = draft[section];
      return before === after ? [] : [{ section, access: after }];
    });
  }, [draft, selectedUser]);

  const revision = usersQuery.data?.revision ?? policy.revision;
  useEffect(() => {
    if (
      !draftState ||
      !selectedDraftKey ||
      draftState.key === selectedDraftKey
    ) {
      return;
    }

    // The list query advanced while this user's confirmation was open. Drop
    // the stale editor state instead of allowing the modal to submit an empty
    // diff against the new global revision.
    setConfirmOpen(false);
    setDraftState(null);
    setConflict(true);
  }, [draftState, selectedDraftKey]);

  const mutation = useMutation({
    mutationFn: () => {
      if (
        !selectedUser ||
        !draftState ||
        draftState.key !== selectedDraftKey ||
        changes.length === 0
      ) {
        throw new Error("Uprawnienia zostały odświeżone. Sprawdź zmiany ponownie.");
      }
      return adminApi.updateUserSectionPermissions(
        selectedUser.user_id,
        draftState.revision,
        changes,
      );
    },
    onSuccess: async (response) => {
      setConfirmOpen(false);
      setDraftState(null);
      setConflict(false);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["admin-user-section-permissions"],
        }),
        queryClient.invalidateQueries({ queryKey: ["admin-section-permissions"] }),
      ]);
      showSuccess(
        response.data.invalidated_users > 0
          ? "Zapisano indywidualne uprawnienia. Użytkownik zaloguje się ponownie."
          : "Zapisano indywidualne uprawnienia użytkownika.",
      );
    },
    onError: async (error) => {
      setConfirmOpen(false);
      if (responseStatus(error) === 409) {
        setConflict(true);
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: ["admin-user-section-permissions"],
          }),
          queryClient.invalidateQueries({ queryKey: ["admin-section-permissions"] }),
        ]);
        showError(
          "Ktoś zmienił uprawnienia w międzyczasie. Wczytano aktualną wersję — sprawdź wyjątek ponownie.",
        );
        return;
      }
      showError(extractErrorMsg(error));
    },
  });

  const resetDraft = () => {
    setDraftState(null);
    setConflict(false);
  };

  const discardDraft = (): boolean =>
    changes.length === 0 ||
    window.confirm(
      "Masz niezapisane zmiany uprawnień. Odrzucić je i przejść dalej?",
    );

  const confirmationChanges = selectedUser
    ? changes.map((change) => ({
        key: change.section,
        title: SECTION_LABELS[change.section].label,
        before:
          OVERRIDE_LABELS[selectedUser.overrides[change.section] ?? "inherit"],
        after: OVERRIDE_LABELS[change.access],
      }))
    : [];

  return (
    <div className="space-y-4">
      <FilterBar
        variant="surface"
        search={{
          value: search,
          onChange: (value) => {
            if (!discardDraft()) return;
            resetDraft();
            setSearch(value);
          },
          onClear: () => {
            if (!discardDraft()) return;
            resetDraft();
            setSearch("");
          },
          placeholder: "Szukaj po imieniu lub e-mailu…",
          ariaLabel: "Szukaj użytkownika",
        }}
        resultCount={usersQuery.data?.total ?? users.length}
        resultLabel={`${usersQuery.data?.total ?? users.length} użytkowników`}
      />

      {conflict ? (
        <Alert
          variant="warning"
          title="Wczytano nowszą wersję zasad"
          description="Poprzedni zapis nie został wykonany. Sprawdź aktualny wyjątek przed ponowną edycją."
        />
      ) : null}

      {usersQuery.isLoading ? (
        <div className="flex min-h-64 items-center justify-center rounded-xl border border-border bg-card text-sm text-muted-foreground">
          Ładowanie użytkowników…
        </div>
      ) : usersQuery.isError ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się pobrać indywidualnych uprawnień."
          onRetry={() => usersQuery.refetch()}
        />
      ) : users.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border px-6 py-12 text-center">
          <UsersRound className="mx-auto size-8 text-muted-foreground" aria-hidden />
          <p className="mt-3 text-sm font-medium text-foreground">
            Nie znaleziono użytkowników
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Zmień wyszukiwaną frazę i spróbuj ponownie.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(16rem,0.7fr)_minmax(0,1.3fr)]">
          <div className="max-h-[38rem] overflow-y-auto rounded-xl border border-border bg-card p-2">
            <div className="space-y-1" aria-label="Użytkownicy">
              {users.map((entry) => {
                const selected = entry.user_id === selectedUser?.user_id;
                const overridesCount = Object.keys(entry.overrides).length;
                return (
                  <button
                    key={entry.user_id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => {
                      if (entry.user_id !== selectedUser?.user_id && !discardDraft()) {
                        return;
                      }
                      setSelectedUserId(entry.user_id);
                      setDraftState(null);
                      setConflict(false);
                    }}
                    className={`w-full rounded-lg px-3 py-2.5 text-left transition-colors focus:outline-hidden focus:ring-2 focus:ring-ring ${
                      selected
                        ? "bg-primary/10 text-foreground"
                        : "text-foreground hover:bg-muted"
                    }`}
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">
                          {entry.name}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {entry.email}
                        </span>
                      </span>
                      {overridesCount > 0 ? (
                        <Badge variant="soft" className="shrink-0">
                          {overridesCount}
                        </Badge>
                      ) : null}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {selectedUser && draft ? (
            <section className="rounded-xl border border-border bg-card">
              <header className="border-b border-border px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex size-9 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <UserRoundCog className="size-4" aria-hidden />
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-semibold text-foreground">
                      {selectedUser.name}
                    </h3>
                    <p className="text-xs text-muted-foreground">
                      {(selectedUser.roles ?? [selectedUser.role])
                        .map((role) => ROLE_LABELS[role] ?? role)
                        .join(" · ")}
                    </p>
                  </div>
                  {selectedUser.locked ? (
                    <Badge variant="neutral" className="ml-auto">
                      <LockKeyhole className="size-3" aria-hidden /> Konto chronione
                    </Badge>
                  ) : null}
                </div>
                {selectedUser.scope_summary ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Zakres danych: {selectedUser.scope_summary}
                  </p>
                ) : null}
              </header>

              <div className="divide-y divide-border">
                {PRODUCT_SECTIONS.map((section) => {
                  const override = draft[section];
                  const effective =
                    override === "inherit"
                      ? inheritedAccess(policy, selectedUser, section)
                      : override;
                  const locked =
                    selectedUser.locked || section === "system_admin";
                  return (
                    <div
                      key={section}
                      className="grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(12rem,0.8fr)] sm:items-center"
                    >
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-foreground">
                            {SECTION_LABELS[section].label}
                          </p>
                          <AccessBadge access={effective} />
                          <span className="text-[11px] text-muted-foreground">
                            {override === "inherit" ? "z roli" : "wyjątek"}
                          </span>
                        </div>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {SECTION_LABELS[section].description}
                        </p>
                      </div>
                      <OverrideSelect
                        value={override}
                        onChange={(access) =>
                          selectedDraftKey &&
                          setDraftState({
                            key: selectedDraftKey,
                            revision,
                            values: { ...draft, [section]: access },
                          })
                        }
                        disabled={locked}
                        ariaLabel={`${selectedUser.name}: ${SECTION_LABELS[section].label}`}
                      />
                    </div>
                  );
                })}
              </div>

              <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
                <p className="text-sm text-muted-foreground">
                  {changes.length === 0
                    ? "Brak niezapisanych zmian"
                    : `${changes.length} ${changes.length === 1 ? "zmiana" : "zmian"} do zapisania`}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    onClick={resetDraft}
                    disabled={changes.length === 0 || mutation.isPending}
                  >
                    <RotateCcw className="size-4" aria-hidden /> Cofnij
                  </Button>
                  <Button
                    onClick={() => setConfirmOpen(true)}
                    disabled={changes.length === 0}
                    loading={mutation.isPending}
                  >
                    <Save className="size-4" aria-hidden /> Zapisz wyjątek
                  </Button>
                </div>
              </footer>
            </section>
          ) : null}
        </div>
      )}

      <AppModal
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Potwierdź indywidualny wyjątek"
        description={
          selectedUser
            ? `Zmiana dotyczy wyłącznie konta ${selectedUser.name}. Jego bieżąca sesja zostanie zakończona, więc zaloguje się ponownie.`
            : undefined
        }
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Anuluj
            </Button>
            <Button
              onClick={() => mutation.mutate()}
              disabled={
                changes.length === 0 ||
                !draftState ||
                draftState.key !== selectedDraftKey
              }
              loading={mutation.isPending}
            >
              Potwierdź i zapisz
            </Button>
          </>
        }
      >
        <ChangeList changes={confirmationChanges} />
      </AppModal>
    </div>
  );
}

export function PermissionsTab() {
  const [view, setView] = useState<PermissionsView>("roles");
  const policyQuery = useQuery({
    queryKey: ["admin-section-permissions"],
    queryFn: () =>
      adminApi.getSectionPermissions().then((response) => response.data),
  });

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border bg-card p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <ShieldCheck className="size-5" aria-hidden />
          </div>
          <div>
            <h3 className="font-semibold text-foreground">Dostęp do sekcji NEXUS</h3>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
              Ustaw domyślny poziom dla roli albo nadpisz go dla jednej osoby.
              Indywidualny wyjątek zastępuje wynik wszystkich ról użytkownika.
            </p>
          </div>
        </div>
      </div>

      <Alert
        variant="info"
        title="Zakres danych i reguły operacyjne pozostają aktywne"
        description="Ten ekran steruje wejściem do sekcji. Na przykład Delivery Lead nadal widzi wyłącznie przypisanych klientów, a dostęp do konkretnej akcji może wymagać dodatkowego uprawnienia. Administracja techniczna pozostaje tylko dla Administratora."
      />

      <TabbedNav
        tabs={[
          { value: "roles", label: "Role", icon: UsersRound },
          { value: "users", label: "Wyjątki użytkowników", icon: UserRoundCog },
        ]}
        value={view}
        onValueChange={(next) => setView(next as PermissionsView)}
        ariaLabel="Sposób przypisania uprawnień"
        overflow="scroll"
      />

      {policyQuery.isLoading ? (
        <div className="flex min-h-64 items-center justify-center rounded-xl border border-border bg-card text-sm text-muted-foreground">
          Ładowanie polityki uprawnień…
        </div>
      ) : policyQuery.isError || !policyQuery.data ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się pobrać zasad dostępu do sekcji."
          onRetry={() => policyQuery.refetch()}
        />
      ) : (
        <>
          <div className={view === "roles" ? undefined : "hidden"}>
            <RolePermissionsEditor policy={policyQuery.data} />
          </div>
          <div className={view === "users" ? undefined : "hidden"}>
            <UserPermissionsEditor
              policy={policyQuery.data}
              active={view === "users"}
            />
          </div>
        </>
      )}
    </div>
  );
}

export default PermissionsTab;
