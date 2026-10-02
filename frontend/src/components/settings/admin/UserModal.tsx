"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import {
  extraPermissionRows,
  legacyLimits,
  permissionsOfRoles,
  requiredByCaption,
  rolesAcceptGrants,
  snapshotIsUsable,
  togglePermission,
  userPermissionsSave,
  type ExtraPermissionRow,
  type UserPermissionsSave,
} from "@/lib/admin-permissions";
import { adminApi } from "@/lib/api";
import { isPermission, type Permission } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import {
  AdminUser,
  UserFormData,
  ROLES,
  ROLE_LABELS,
  isExclusiveRole,
} from "./types";

interface GrantDraft {
  revision: number;
  granted: Set<Permission>;
}

type ExtraPermissionsState =
  | { status: "hidden" }
  | { status: "loading" }
  | { status: "error"; retry: () => void }
  | {
      status: "ready";
      rows: ExtraPermissionRow[];
      /** Stare wyjątki osoby nazwane słowami (pusto = nie ma czego usuwać). */
      legacy: string[];
      removeLegacy: boolean;
      /** Szkic przepadł, bo zasady zmieniły się, gdy okno było otwarte. */
      refreshed: boolean;
      /** Drugie żądanie zapisu albo `null`, gdy uprawnienia się nie zmieniają. */
      save: UserPermissionsSave | null;
      toggle: (key: Permission) => void;
      setRemoveLegacy: (remove: boolean) => void;
    };

/**
 * „Dodatkowe uprawnienia” jednej osoby. Lista idzie za rolami WYBRANYMI
 * w formularzu, nie zapisanymi — zmiana roli w tym samym oknie od razu
 * pokazuje, czego nowa rola nie daje.
 */
function useExtraPermissions(
  userId: number | null,
  roles: string[],
): ExtraPermissionsState {
  const enabled = userId !== null;
  const snapshotQuery = useQuery({
    queryKey: ["admin-section-permissions"],
    queryFn: () =>
      adminApi.getSectionPermissions().then((response) => response.data),
    enabled,
  });
  const personQuery = useQuery({
    queryKey: ["admin-user-permissions", userId],
    queryFn: () =>
      adminApi.getUserPermissions(userId as number).then((response) => response.data),
    enabled,
    // Okno startuje od bieżących nadań i bieżącej wersji zasad, nie z cache.
    staleTime: 0,
  });
  const [draft, setDraft] = useState<GrantDraft | null>(null);
  const [removeLegacy, setRemoveLegacy] = useState(false);
  const [refreshed, setRefreshed] = useState(false);

  const snapshot = snapshotIsUsable(snapshotQuery.data) ? snapshotQuery.data : null;
  const person = personQuery.data ?? null;
  const revision = person?.revision;

  useEffect(() => {
    if (!draft || revision === undefined || draft.revision === revision) return;
    // Zaznaczenia powstały na starszej wersji zasad — nie przenosimy ich po
    // cichu na nową (role mogą dawać już co innego).
    setDraft(null);
    setRefreshed(true);
  }, [draft, revision]);

  const stored = useMemo(
    () => new Set((person?.user.grants ?? []).filter(isPermission)),
    [person],
  );
  const granted = draft && draft.revision === revision ? draft.granted : stored;
  const roleGiven = useMemo(
    () => (snapshot ? permissionsOfRoles(snapshot, roles) : new Set<Permission>()),
    [snapshot, roles],
  );

  if (!enabled) return { status: "hidden" };
  if (snapshotQuery.isPending || personQuery.isPending) return { status: "loading" };
  if (snapshotQuery.isError || personQuery.isError || !snapshot || !person) {
    return {
      status: "error",
      retry: () => {
        void snapshotQuery.refetch();
        void personQuery.refetch();
      },
    };
  }
  if (!rolesAcceptGrants(snapshot, roles)) return { status: "hidden" };

  const savedRoles = new Set<string>(person.user.roles);
  const rolesChanged =
    savedRoles.size !== new Set(roles).size ||
    roles.some((role) => !savedRoles.has(role));
  return {
    status: "ready",
    rows: extraPermissionRows(snapshot, roleGiven, granted),
    legacy: legacyLimits(person.user),
    removeLegacy,
    refreshed,
    save: userPermissionsSave({
      response: person,
      draft: granted,
      roleGiven,
      rolesChanged,
      removeLegacy,
    }),
    toggle: (key) => {
      setRefreshed(false);
      setDraft({ revision: person.revision, granted: togglePermission(granted, key) });
    },
    setRemoveLegacy,
  };
}

function rolesPhrase(roles: string[]): string {
  const labels = roles.map((role) => ROLE_LABELS[role] ?? role);
  return labels.length === 1
    ? `rola ${labels[0]} nie daje`
    : `role ${labels.join(", ")} nie dają`;
}

function ExtraPermissionRowField({
  row,
  onToggle,
}: {
  row: ExtraPermissionRow;
  onToggle: (key: Permission) => void;
}) {
  const captionId = useId();
  const locked = row.requiredBy.length > 0;
  return (
    <div>
      <label
        className={cn(
          "flex items-start gap-2 py-0.5 text-sm pointer-coarse:min-h-10 pointer-coarse:items-center",
          row.checked && "font-medium",
        )}
      >
        <input
          type="checkbox"
          checked={row.checked}
          disabled={locked}
          onChange={() => onToggle(row.key)}
          aria-describedby={locked ? captionId : undefined}
          className="mt-0.5 shrink-0 rounded border-border pointer-coarse:mt-0"
        />
        <span>{row.label}</span>
      </label>
      {locked ? (
        <p id={captionId} className="ml-6 text-xs text-muted-foreground">
          {requiredByCaption(row.requiredBy)}
        </p>
      ) : null}
    </div>
  );
}

function ExtraPermissionsSection({
  state,
  roles,
}: {
  state: ExtraPermissionsState;
  roles: string[];
}) {
  const headingId = useId();
  if (state.status === "hidden") return null;
  return (
    <div role="group" aria-labelledby={headingId}>
      <p id={headingId} className="block text-sm font-medium text-foreground mb-1">
        Dodatkowe uprawnienia
      </p>
      {state.status === "loading" ? (
        <p role="status" className="text-sm text-muted-foreground">
          Wczytywanie uprawnień…
        </p>
      ) : state.status === "error" ? (
        <div
          role="alert"
          className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          Nie udało się wczytać uprawnień tej osoby. Zapis zmieni tylko dane konta.{" "}
          <button
            type="button"
            onClick={state.retry}
            className="hit-area font-medium underline underline-offset-2"
          >
            Ponów
          </button>
        </div>
      ) : (
        <>
          <div className="border border-border rounded-lg px-3 py-2 space-y-1">
            {state.rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Role tej osoby dają już wszystkie uprawnienia.
              </p>
            ) : (
              state.rows.map((row) => (
                <ExtraPermissionRowField key={row.key} row={row} onToggle={state.toggle} />
              ))
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Lista pokazuje tylko to, czego {rolesPhrase(roles)}. Zaznaczone działa
            wyłącznie dla tej osoby.
          </p>
          {state.refreshed ? (
            <p className="text-xs text-warning-muted-foreground mt-1">
              Zasady uprawnień zmieniły się w międzyczasie — wczytaliśmy aktualne.
              Zaznacz uprawnienia jeszcze raz.
            </p>
          ) : null}
          {state.legacy.length > 0 ? (
            <p className="text-xs text-muted-foreground mt-1">
              {state.removeLegacy
                ? "Stare ograniczenia tej osoby zostaną usunięte po zapisaniu."
                : `Stare ograniczenia tej osoby: ${state.legacy.join("; ")}.`}{" "}
              <button
                type="button"
                onClick={() => state.setRemoveLegacy(!state.removeLegacy)}
                className="hit-area font-medium text-foreground underline underline-offset-2"
              >
                {state.removeLegacy ? "Zostaw ograniczenia" : "Usuń ograniczenia"}
              </button>
            </p>
          ) : null}
          {state.save ? (
            <p className="text-xs font-medium text-warning-muted-foreground mt-1">
              Po zapisaniu ta osoba zostanie wylogowana.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

interface UserModalProps {
  initial?: Partial<AdminUser> | null;
  onClose: () => void;
  onSave: (data: UserFormData) => void;
  loading: boolean;
  /** Odmowa serwera (np. domena spoza firmy, duplikat adresu) — UAT M11-B10.
   *  Bez niej nieudany zapis zostawiał formularz otwarty bez słowa. */
  error?: string | null;
}

export function UserModal({ initial, onClose, onSave, loading, error }: UserModalProps) {
  const isEdit = !!initial?.id;
  const initialPrimary = initial?.role ?? "recruiter";
  const rawInitialRoles =
    initial?.roles && initial.roles.length > 0
      ? initial.roles
      : initial?.role
        ? [initial.role]
        : ["recruiter"];
  const initialRoles = isExclusiveRole(initialPrimary)
    ? [initialPrimary]
    : Array.from(
        new Set([
          initialPrimary,
          ...rawInitialRoles.filter((role) => !isExclusiveRole(role)),
        ]),
      );
  const [form, setForm] = useState<UserFormData>({
    name: initial?.name ?? "",
    email: initial?.email ?? "",
    password: "",
    role: initialPrimary,
    roles: initialRoles,
    can_delete_clients: initial?.can_delete_clients ?? false,
    clear_microsoft_identity: false,
  });

  const set = <K extends keyof UserFormData>(field: K, value: UserFormData[K]) =>
    setForm((f) => ({ ...f, [field]: value }));

  const setPrimaryRole = (role: string) => {
    setForm((f) => {
      if (isExclusiveRole(role)) {
        return { ...f, role, roles: [role] };
      }
      const withoutExclusive = f.roles.filter(
        (value) => !isExclusiveRole(value),
      );
      return {
        ...f,
        role,
        roles: withoutExclusive.includes(role)
          ? withoutExclusive
          : [role, ...withoutExclusive],
      };
    });
  };

  const toggleSecondaryRole = (role: string) => {
    setForm((f) => {
      if (isExclusiveRole(f.role) || isExclusiveRole(role)) {
        return f;
      }
      const has = f.roles.includes(role);
      const next = has ? f.roles.filter((r) => r !== role) : [...f.roles, role];
      if (!next.includes(f.role)) next.unshift(f.role);
      return { ...f, roles: next };
    });
  };

  useEffect(() => {
    setForm((f) => {
      if (f.roles.includes(f.role)) return f;
      return { ...f, roles: [f.role, ...f.roles] };
    });
  }, [form.role]);

  const extraPermissions = useExtraPermissions(
    isEdit ? (initial?.id as number) : null,
    form.roles,
  );
  // Uprawnienia jadą obok danych konta — rodzic zapisuje je drugim żądaniem.
  const handleSave = () =>
    onSave(
      extraPermissions.status === "ready"
        ? { ...form, permissions: extraPermissions.save }
        : form,
    );

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-card rounded-xl shadow-2xl w-full max-w-md p-4 sm:p-6 space-y-5 max-h-[90dvh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {isEdit ? "Edytuj użytkownika" : "Dodaj użytkownika"}
          </h2>
          <button onClick={onClose} aria-label="Zamknij" className="hit-area text-muted-foreground hover:text-muted-foreground dark:text-muted-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Imię i nazwisko</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              placeholder="Jan Kowalski"
            />
          </div>

          {!isEdit && (
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
                placeholder="jan@example.com"
              />
            </div>
          )}

          {!isEdit && (
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Hasło</label>
              <input
                type="password"
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
                minLength={8}
                maxLength={128}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
                placeholder="min. 8 znaków"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Rola podstawowa</label>
            <select
              value={form.role}
              onChange={(e) => setPrimaryRole(e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            >
              {ROLES.filter((r) => r !== "user").map((r) => (
                <option key={r} value={r}>{ROLE_LABELS[r] ?? r}</option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground mt-1">
              Określa domyślny widok dashboardu i wpisana jest do tokenu JWT.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Dodatkowe role</label>
            <div className="space-y-1.5 border border-border rounded-lg px-3 py-2 max-h-44 overflow-y-auto">
              {ROLES.filter((r) => r !== "user" || r === form.role).map((r) => {
                const isPrimary = r === form.role;
                const checked = form.roles.includes(r);
                const primaryIsExclusive = isExclusiveRole(form.role);
                const roleIsExclusive = isExclusiveRole(r);
                const exclusiveConflict =
                  (primaryIsExclusive && r !== form.role) ||
                  (!primaryIsExclusive && roleIsExclusive);
                return (
                  <label
                    key={r}
                    className={cn(
                      "flex items-center gap-2 text-sm",
                      isPrimary && "text-muted-foreground italic"
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked || isPrimary}
                      disabled={isPrimary || exclusiveConflict}
                      onChange={() => toggleSecondaryRole(r)}
                      className="rounded border-border"
                    />
                    <span>{ROLE_LABELS[r] ?? r}</span>
                    {isPrimary && <span className="text-xs">(podstawowa)</span>}
                  </label>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Osobom z kilkoma rolami (np. DL+TAC) zaznacz obie. Rola podstawowa
              jest zawsze wybrana. Finanse, Praktykant i Viewer (legacy) są rolami
              wyłącznymi i nie mogą być łączone z innymi; Viewer nie jest
              dostępny jako rola dodatkowa.
            </p>
          </div>

          <ExtraPermissionsSection state={extraPermissions} roles={form.roles} />

          {isEdit && (
            <div className="border border-border rounded-lg px-3 py-2">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                <input
                  type="checkbox"
                  checked={form.can_delete_clients}
                  onChange={(e) => set("can_delete_clients", e.target.checked)}
                  className="rounded border-border"
                />
                Może usuwać klientów
              </label>
              <p className="text-xs text-muted-foreground mt-1">
                Uprawnienie imienne — nie wynika z roli (także administrator go
                nie ma bez zaznaczenia). Nadanie i odebranie trafia do Historii
                zdarzeń.
              </p>
            </div>
          )}

          {isEdit && (
            <div className="border border-border rounded-lg px-3 py-2">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                <input
                  type="checkbox"
                  checked={form.clear_microsoft_identity}
                  onChange={(e) =>
                    set("clear_microsoft_identity", e.target.checked)
                  }
                  className="rounded border-border"
                />
                Odepnij tożsamość Microsoft
              </label>
              <p className="text-xs text-muted-foreground mt-1">
                Tylko gdy logowanie kończy się błędem „przypisane do innej
                tożsamości Microsoft” (np. konto odtworzone w Entra). Następne
                logowanie przypnie konto Microsoft osoby, która się zaloguje —
                upewnij się, że to właściwa osoba.
              </p>
            </div>
          )}
        </div>

        {error && (
          <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-foreground border border-border rounded-lg hover:bg-muted dark:bg-card transition-colors"
          >
            Anuluj
          </button>
          <button
            onClick={handleSave}
            disabled={loading}
            className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg transition-colors disabled:opacity-50"
          >
            {loading ? "Zapisywanie..." : "Zapisz"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default UserModal;
