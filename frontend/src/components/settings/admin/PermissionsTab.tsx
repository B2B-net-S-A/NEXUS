"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Save } from "lucide-react";

import { useToast } from "@/components/Toast";
import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  changedRows,
  changesCountLabel,
  grantableRoles,
  grantedPermissions,
  isStalePolicyError,
  logoutSentence,
  peopleCountLabel,
  quotedPermissionLabels,
  requiredByCaption,
  rolePermissionChanges,
  rolePermissionGroups,
  snapshotIsUsable,
  togglePermission,
  type AdminPermissionsSnapshot,
  type AdminRolePermissions,
  type PermissionRow,
  type PermissionRowGroup,
} from "@/lib/admin-permissions";
import { adminApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { Permission } from "@/lib/permissions";
import { pluralPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import type { UserRole } from "@/store/auth";
import { ROLE_LABELS } from "./types";

/** Wspólne pytanie przy porzucaniu niezapisanych przełączników (rola, zakładka). */
export const DISCARD_PERMISSION_CHANGES = {
  title: "Masz niezapisane zmiany uprawnień. Odrzucić je i przejść dalej?",
  confirmLabel: "Odrzuć zmiany",
  variant: "destructive",
} as const;

interface RoleDraft {
  role: UserRole;
  revision: number;
  granted: Set<Permission>;
}

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

/**
 * Na szerokim ekranie grupy stoją w dwóch kolumnach — wtedy dziewięć
 * przełączników i pasek zapisu mieszczą się w oknie 1280 × 720 bez przewijania.
 * Pierwsza kolumna bierze grupy, dopóki nie ma połowy wierszy.
 */
function splitIntoColumns(
  groups: PermissionRowGroup[],
): [PermissionRowGroup[], PermissionRowGroup[]] {
  const total = groups.reduce((sum, group) => sum + group.rows.length, 0);
  const left: PermissionRowGroup[] = [];
  let taken = 0;
  for (const group of groups) {
    if (left.length > 0 && taken * 2 >= total) break;
    left.push(group);
    taken += group.rows.length;
  }
  return [left, groups.slice(left.length)];
}

function PermissionSwitchRow({
  row,
  role,
  onToggle,
}: {
  row: PermissionRow;
  role: string;
  onToggle: (key: Permission) => void;
}) {
  const id = useId();
  const locked = row.requiredBy.length > 0;
  return (
    <li>
      <label
        htmlFor={id}
        className={cn(
          "flex min-h-9 items-center justify-between gap-4 px-4 py-1.5 pointer-coarse:min-h-11",
          locked ? "cursor-not-allowed" : "cursor-pointer hover:bg-muted/50",
          row.changed && "bg-warning-muted hover:bg-warning-muted",
        )}
      >
        <span className="min-w-0">
          <span className="text-sm text-foreground">{row.label}</span>
          {row.changed ? (
            <span className="ml-2 whitespace-nowrap text-xs font-semibold text-warning-muted-foreground">
              zmiana · dziś: {row.onToday ? "tak" : "nie"}
            </span>
          ) : null}
          {locked ? (
            <span id={`${id}-why`} className="block text-xs text-muted-foreground">
              {requiredByCaption(row.requiredBy)}
            </span>
          ) : null}
        </span>
        <Switch
          id={id}
          checked={row.on}
          disabled={locked}
          onCheckedChange={() => onToggle(row.key)}
          aria-label={`${role}: ${row.label}`}
          aria-describedby={locked ? `${id}-why` : undefined}
        />
      </label>
    </li>
  );
}

function PermissionGroupList({
  groups,
  role,
  onToggle,
}: {
  groups: PermissionRowGroup[];
  role: string;
  onToggle: (key: Permission) => void;
}) {
  return (
    <div className="min-w-0 pb-2">
      {groups.map((group) => (
        <section key={group.key} aria-label={group.label}>
          <h4 className="px-4 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {group.label}
          </h4>
          <ul>
            {group.rows.map((row) => (
              <PermissionSwitchRow
                key={row.key}
                row={row}
                role={role}
                onToggle={onToggle}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function ChangeSummary({
  role,
  rows,
  granted,
}: {
  role: AdminRolePermissions;
  rows: PermissionRow[];
  granted: ReadonlySet<Permission>;
}) {
  const label = roleLabel(role.role);
  const gained = rows.filter((row) => row.on);
  const lost = rows.filter((row) => !row.on);
  return (
    <div className="space-y-3 text-sm text-foreground">
      {gained.length > 0 ? (
        <div>
          <p className="font-medium">Rola {label} dostanie:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {gained.map((row) => (
              <li key={row.key}>
                {row.label}
                {granted.has(row.key) ? null : (
                  <span className="text-muted-foreground">
                    {" — wymagane przez "}
                    {quotedPermissionLabels(row.requiredBy)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {lost.length > 0 ? (
        <div>
          <p className="font-medium">Rola {label} straci:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {lost.map((row) => (
              <li key={row.key}>
                {row.label}
                {role.named?.[row.key]?.granted ? null : (
                  <span className="text-muted-foreground">
                    {" — nie będzie już wymagane"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-muted-foreground">
        {logoutSentence(role.users_count, label)}
      </p>
    </div>
  );
}

function RolePermissionsEditor({
  snapshot,
  onDirtyChange,
}: {
  snapshot: AdminPermissionsSnapshot;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const roles = useMemo(() => grantableRoles(snapshot), [snapshot]);
  const [selectedRole, setSelectedRole] = useState<UserRole>(roles[0].role);
  const [draft, setDraft] = useState<RoleDraft | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [conflict, setConflict] = useState(false);

  const role = roles.find((entry) => entry.role === selectedRole) ?? roles[0];
  const label = roleLabel(role.role);
  const granted = useMemo(
    () =>
      draft && draft.role === role.role ? draft.granted : grantedPermissions(role),
    [draft, role],
  );
  const groups = useMemo(
    () => rolePermissionGroups(snapshot, role, granted),
    [snapshot, role, granted],
  );
  const changed = useMemo(() => changedRows(groups), [groups]);
  const changes = useMemo(
    () => rolePermissionChanges(role, granted),
    [role, granted],
  );
  const dirty = changes.length > 0;
  const [leftGroups, rightGroups] = useMemo(() => splitIntoColumns(groups), [groups]);

  useEffect(() => {
    if (!draft || draft.revision === snapshot.revision) return;
    // Szkic powstał na starszej wersji zasad. Nie przenosimy go po cichu na
    // nową i nie zostawiamy otwartego potwierdzenia, które by go wysłało.
    setConfirmOpen(false);
    setDraft(null);
    setConflict((current) => current || dirty);
  }, [dirty, draft, snapshot.revision]);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  const mutation = useMutation({
    mutationFn: () =>
      adminApi.updateRoleSectionPermissions(
        draft?.revision ?? snapshot.revision,
        [],
        changes,
      ),
    onSuccess: async (response) => {
      setConfirmOpen(false);
      setConflict(false);
      const loggedOut = response.data.invalidated_users;
      showSuccess(
        loggedOut > 0
          ? `Zapisano uprawnienia roli ${label}. ${loggedOut} ${pluralPl(loggedOut, "osoba zaloguje", "osoby zalogują", "osób zaloguje")} się ponownie.`
          : `Zapisano uprawnienia roli ${label}.`,
      );
      // Szkic znika razem z nową wersją z serwera — wcześniej przełączniki
      // na chwilę wróciłyby do stanu sprzed zapisu.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["admin-section-permissions"] }),
        queryClient.invalidateQueries({ queryKey: ["admin-user-permissions"] }),
        queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
      ]);
      setDraft(null);
    },
    onError: async (error) => {
      setConfirmOpen(false);
      if (isStalePolicyError(error)) {
        setConflict(true);
        await queryClient.invalidateQueries({
          queryKey: ["admin-section-permissions"],
        });
        showError(
          "Ktoś zmienił uprawnienia w międzyczasie. Wczytano aktualną wersję — sprawdź zmiany ponownie.",
        );
        return;
      }
      showError(apiErrorMessage(error, "Nie udało się zapisać uprawnień."));
    },
  });

  const toggle = (key: Permission) => {
    setConflict(false);
    setDraft({
      role: role.role,
      revision: snapshot.revision,
      granted: togglePermission(granted, key),
    });
  };

  const resetDraft = () => {
    setDraft(null);
    setConflict(false);
  };

  const selectRole = (next: UserRole) => {
    if (next === role.role) return;
    const go = () => {
      resetDraft();
      setSelectedRole(next);
    };
    if (!dirty) {
      go();
      return;
    }
    void askConfirm(DISCARD_PERMISSION_CHANGES).then((ok) => {
      if (ok) go();
    });
  };

  return (
    <div className="space-y-4">
      {confirmDialog}
      {conflict ? (
        <Alert
          variant="warning"
          title="Wczytano nowszą wersję zasad"
          description="Poprzedni zapis nie został wykonany. Sprawdź przełączniki przed ponowną edycją."
        />
      ) : null}

      <section className="rounded-xl border border-border bg-card">
        <div
          role="group"
          aria-label="Rola"
          className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3"
        >
          <span className="text-sm text-muted-foreground">Rola:</span>
          {roles.map((entry) => {
            const selected = entry.role === role.role;
            return (
              <button
                key={entry.role}
                type="button"
                aria-pressed={selected}
                onClick={() => selectRole(entry.role)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors pointer-coarse:min-h-10",
                  "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                  selected
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground",
                )}
              >
                {roleLabel(entry.role)}
              </button>
            );
          })}
        </div>

        <p className="border-b border-border px-4 py-2.5 text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">{label}</span>
          {" · "}
          {peopleCountLabel(role.users_count)}. Każda rola może pracować
          z kandydatami, prowadzić rekrutacje i generować umowy B2B.
          {role.role === "delivery_lead"
            ? " Delivery Lead robi wszystko poniżej tylko u swoich klientów."
            : ""}{" "}
          Administrator ma wszystkie uprawnienia.
        </p>

        {/* Kontener zapytań tylko wokół listy — pasek zapisu niżej jest
            przyklejony do okna, a zawieranie układu mogłoby mu to odebrać. */}
        <div className="@container">
          <div className="grid divide-border @4xl:grid-cols-2 @4xl:divide-x">
            <PermissionGroupList groups={leftGroups} role={label} onToggle={toggle} />
            {rightGroups.length > 0 ? (
              <PermissionGroupList groups={rightGroups} role={label} onToggle={toggle} />
            ) : null}
          </div>
        </div>

        <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-b-xl border-t border-border bg-card px-4 py-3">
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {changesCountLabel(changed.length)}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={resetDraft}
              disabled={!dirty || mutation.isPending}
            >
              <RotateCcw className="size-4" aria-hidden /> Cofnij
            </Button>
            <Button
              onClick={() => setConfirmOpen(true)}
              disabled={!dirty}
              loading={mutation.isPending}
            >
              <Save className="size-4" aria-hidden /> Zapisz zmiany
            </Button>
          </div>
        </div>
      </section>

      <AppModal
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`Potwierdź zmianę uprawnień roli ${label}`}
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Anuluj
            </Button>
            <Button
              onClick={() => mutation.mutate()}
              disabled={!dirty}
              loading={mutation.isPending}
            >
              Potwierdź i zapisz
            </Button>
          </>
        }
      >
        <ChangeSummary role={role} rows={changed} granted={granted} />
      </AppModal>
    </div>
  );
}

export interface PermissionsTabProps {
  /** Rodzic pyta o niezapisane zmiany, zanim przełączy zakładkę. */
  onDirtyChange?: (dirty: boolean) => void;
}

export function PermissionsTab({ onDirtyChange }: PermissionsTabProps = {}) {
  const policyQuery = useQuery({
    queryKey: ["admin-section-permissions"],
    queryFn: () =>
      adminApi.getSectionPermissions().then((response) => response.data),
  });

  if (policyQuery.isPending) {
    return (
      <div
        role="status"
        className="flex min-h-64 items-center justify-center rounded-xl border border-border bg-card text-sm text-muted-foreground"
      >
        Wczytywanie uprawnień…
      </div>
    );
  }
  // Odpowiedź bez listy uprawnień albo bez ról do nadania to awaria odczytu —
  // nie pokazujemy jej jako pustego ekranu ani jako roli bez uprawnień.
  if (policyQuery.isError || !snapshotIsUsable(policyQuery.data)) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się pobrać uprawnień ról."
        onRetry={() => policyQuery.refetch()}
      />
    );
  }
  return (
    <RolePermissionsEditor
      snapshot={policyQuery.data}
      onDirtyChange={onDirtyChange}
    />
  );
}

export default PermissionsTab;
