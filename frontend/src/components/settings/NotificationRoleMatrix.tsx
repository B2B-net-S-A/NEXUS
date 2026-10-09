"use client";

// Ustawienia → Powiadomienia → „Kto co dostaje”: tabela kategoria × rola.
// Przełączniki zmieniają lokalny SZKIC; zapis idzie jednym żądaniem po
// potwierdzeniu, tylko ze zmienionymi komórkami i z wersją, na której szkic
// powstał (409 = ktoś zapisał wcześniej → wczytujemy od nowa, bez szkicu).

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Lock, RotateCcw, Save } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import { notificationPreferencesQueryKey } from "@/lib/api/notificationPreferences";
import {
  isStaleNotificationRolesError,
  notificationRolesApi,
  notificationRolesQueryKey,
  useNotificationRoles,
} from "@/lib/api/notificationRoles";
import {
  EMPTY_ROLE_MATRIX_DRAFT,
  accountsLabel,
  categoryReceived,
  categoryState,
  changeSummary,
  changedCells,
  formatCount,
  groupReceived,
  initiallyExpanded,
  isCellChanged,
  isGroupMuted,
  perPersonAverage,
  toggleCategory,
  toggleGroup,
  viewIsUsable,
  type NotificationRoleCategory,
  type NotificationRoleColumn,
  type NotificationRolesView,
  type RoleMatrixDraft,
} from "@/lib/notification-role-matrix";
import { hasSectionAccess } from "@/lib/section-access";
import { cn } from "@/lib/utils";
import { isForbiddenError } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

const STALE_FALLBACK =
  "Ktoś zmienił te ustawienia w międzyczasie. Wczytano aktualną wersję — wprowadź zmiany ponownie.";

interface Draft {
  /** Wersja tabeli, na której szkic powstał — idzie w `PUT`. */
  revision: number;
  cells: RoleMatrixDraft;
}

type Notice =
  | { kind: "saved" }
  | { kind: "stale"; message: string }
  | { kind: "error"; message: string };

function formatDateTime(value: string): string | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString("pl-PL");
}

function countLabel(count: number): string {
  return count > 0 ? formatCount(count) : "–";
}

/** Pierwsza kolumna jest przyklejona — tabela przewija się pod nią w poziomie. */
const STICKY_FIRST = "sticky left-0 z-10 bg-card";

function RoleHeader({
  role,
  average,
  savedAverage,
}: {
  role: NotificationRoleColumn;
  average: number | null;
  savedAverage: number | null;
}) {
  return (
    <th scope="col" className="min-w-28 px-3 py-2.5 text-center align-bottom font-normal">
      <span className="block text-xs font-semibold text-foreground">{role.label}</span>
      <span className="block text-[11px] text-muted-foreground">
        {accountsLabel(role.accounts)}
      </span>
      <span className="mt-1 block text-[11px] font-semibold tabular-nums text-foreground">
        {average === null ? "—" : `${formatCount(average)} na osobę`}
      </span>
      {average !== savedAverage && savedAverage !== null ? (
        <s className="block text-[11px] tabular-nums text-muted-foreground">
          było {formatCount(savedAverage)}
        </s>
      ) : null}
    </th>
  );
}

function SwitchCell({
  label,
  checked,
  mixed = false,
  changed,
  count,
  disabled,
  onToggle,
}: {
  label: string;
  checked: boolean;
  /** Kategoria z częścią grup wyłączonych — przełącznik stoi na „wyłączone”. */
  mixed?: boolean;
  changed: boolean;
  count: number;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <td className={cn("px-3 py-2 text-center", changed && "bg-warning-muted")}>
      <span className="flex flex-col items-center gap-1">
        <Switch
          className="hit-area"
          checked={checked}
          disabled={disabled}
          onCheckedChange={onToggle}
          aria-label={label}
        />
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {mixed ? "część · " : ""}
          {countLabel(count)}
        </span>
      </span>
    </td>
  );
}

function LockedCell({ count }: { count: number }) {
  return (
    <td className="px-3 py-2 text-center">
      <span className="flex flex-col items-center gap-1">
        <span className="inline-flex h-5 items-center gap-1 text-[11px] text-muted-foreground">
          <Lock className="h-3 w-3" aria-hidden />
          zawsze
        </span>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {countLabel(count)}
        </span>
      </span>
    </td>
  );
}

function CategoryRows({
  category,
  roles,
  cells,
  expanded,
  disabled,
  onExpand,
  onToggleCategory,
  onToggleGroup,
}: {
  category: NotificationRoleCategory;
  roles: NotificationRoleColumn[];
  cells: RoleMatrixDraft;
  expanded: boolean;
  disabled: boolean;
  onExpand: () => void;
  onToggleCategory: (role: string) => void;
  onToggleGroup: (role: string, group: string) => void;
}) {
  const split = category.groups.length > 1;
  return (
    <>
      <tr className="border-t border-border/60 align-top">
        <th scope="row" className={cn(STICKY_FIRST, "min-w-40 max-w-72 sm:min-w-52 px-4 py-2 text-left font-normal")}>
          <span className="block text-sm font-medium text-foreground">{category.label}</span>
          <span className="block text-xs text-muted-foreground">{category.description}</span>
          {split ? (
            <button
              type="button"
              aria-expanded={expanded}
              onClick={onExpand}
              className="mt-1 inline-flex items-center gap-1 rounded-md text-xs font-medium text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-10"
            >
              {expanded ? (
                <ChevronDown className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" aria-hidden />
              )}
              {expanded ? "Zwiń" : `Rozwiń (${category.groups.length})`}
              <span className="sr-only">: {category.label}</span>
            </button>
          ) : null}
        </th>
        {roles.map((role) => {
          const received = categoryReceived(category, role.key);
          if (category.mandatory) return <LockedCell key={role.key} count={received} />;
          const state = categoryState(category, role.key, cells);
          return (
            <SwitchCell
              key={role.key}
              label={`${category.label} — ${role.label}`}
              checked={state === "on"}
              mixed={state === "mixed"}
              changed={category.groups.some((group) =>
                isCellChanged(group, role.key, cells),
              )}
              count={received}
              disabled={disabled}
              onToggle={() => onToggleCategory(role.key)}
            />
          );
        })}
      </tr>
      {split && expanded
        ? category.groups.map((group) => (
            <tr key={group.key} className="border-t border-border/40 align-top">
              <th
                scope="row"
                className={cn(
                  STICKY_FIRST,
                  "min-w-40 max-w-72 sm:min-w-52 py-2 pl-8 pr-4 text-left text-sm font-normal text-muted-foreground",
                )}
              >
                {group.label}
              </th>
              {roles.map((role) =>
                category.mandatory ? (
                  <LockedCell key={role.key} count={groupReceived(group, role.key)} />
                ) : (
                  <SwitchCell
                    key={role.key}
                    label={`${group.label} — ${role.label}`}
                    checked={!isGroupMuted(group, role.key, cells)}
                    changed={isCellChanged(group, role.key, cells)}
                    count={groupReceived(group, role.key)}
                    disabled={disabled}
                    onToggle={() => onToggleGroup(role.key, group.key)}
                  />
                ),
              )}
            </tr>
          ))
        : null}
    </>
  );
}

function RoleMatrixEditor({
  view,
  canWrite,
}: {
  view: NotificationRolesView;
  canWrite: boolean;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(
    () => new Set(initiallyExpanded(view)),
  );
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  // Szkic ze starszej wersji tabeli nie jest przenoszony na nową po cichu.
  const cells =
    draft && draft.revision === view.revision ? draft.cells : EMPTY_ROLE_MATRIX_DRAFT;
  const changes = useMemo(() => changedCells(view, cells), [view, cells]);
  const summary = useMemo(() => changeSummary(view, cells), [view, cells]);
  const dirty = changes.length > 0;

  useEffect(() => {
    if (!draft || draft.revision === view.revision) return;
    // Tabela odświeżyła się pod szkicem (inna karta, inny administrator):
    // szkic i otwarte potwierdzenie znikają, a ekran mówi dlaczego.
    const lost = Object.keys(draft.cells).length > 0;
    setConfirmOpen(false);
    setDraft(null);
    if (lost) setNotice({ kind: "stale", message: STALE_FALLBACK });
  }, [draft, view.revision]);

  const mutation = useMutation({
    mutationFn: () => notificationRolesApi.update(view.revision, changes),
    onSuccess: (data) => {
      // Najpierw szkic, potem nowa tabela — w odwrotnej kolejności efekt
      // wyżej uznałby własny zapis za cudzą zmianę.
      setDraft(null);
      setConfirmOpen(false);
      setNotice({ kind: "saved" });
      queryClient.setQueryData(notificationRolesQueryKey, data);
      // Wyłączenie kategorii roli administratora dotyczy też jego konta.
      void queryClient.invalidateQueries({ queryKey: notificationPreferencesQueryKey });
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (error) => {
      setConfirmOpen(false);
      if (isStaleNotificationRolesError(error)) {
        setDraft(null);
        setNotice({ kind: "stale", message: apiErrorMessage(error, STALE_FALLBACK) });
        void queryClient.invalidateQueries({ queryKey: notificationRolesQueryKey });
        return;
      }
      setNotice({
        kind: "error",
        message: apiErrorMessage(error, "Nie udało się zapisać zmian."),
      });
    },
  });
  // Do odpowiedzi serwera przełączniki czekają — zmiana zrobiona w trakcie
  // zapisu znikłaby bez słowa razem ze szkicem.
  const saving = mutation.isPending;
  const disabled = !canWrite || saving;

  const edit = (next: RoleMatrixDraft) => {
    setNotice(null);
    setDraft({ revision: view.revision, cells: next });
  };
  const resetDraft = () => {
    setDraft(null);
    setNotice(null);
  };
  const toggleExpanded = (key: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const updatedAt = view.updated_at ? formatDateTime(view.updated_at) : null;

  return (
    <div className="space-y-3">
      {notice?.kind === "stale" ? (
        <Alert
          variant="warning"
          role="alert"
          title="Wczytano nowszą wersję ustawień"
          description={notice.message}
        />
      ) : null}
      {notice?.kind === "error" ? (
        <Alert variant="error" role="alert" title="Zmiany nie zostały zapisane" description={notice.message} />
      ) : null}

      <section
        className="rounded-xl border border-border bg-card"
        aria-labelledby="notification-roles-heading"
      >
        <div className="border-b border-border px-4 py-3">
          <h2 id="notification-roles-heading" className="font-semibold text-foreground">
            Kto co dostaje
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Wyłącz kategorię dla całej roli. Osoba z tej roli przestaje ją
            dostawać w dzwonku; resztę każdy doprecyzuje sobie w zakładce
            „Moje”. Kategorii z kłódką nie da się wyłączyć, bo ktoś czeka w nich
            na konkretną osobę.
          </p>
          {!canWrite ? (
            <p className="mt-2 text-sm text-muted-foreground">Masz dostęp tylko do odczytu.</p>
          ) : null}
        </div>

        {/* `relative`: pola trafienia przełączników (`hit-area`) i tekst dla
            czytników zostają w polu przewijania zamiast poszerzać stronę. */}
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[880px] border-collapse text-sm">
            <thead>
              <tr>
                <th
                  scope="col"
                  className={cn(
                    STICKY_FIRST,
                    "px-4 py-2.5 text-left align-bottom text-[11px] font-semibold uppercase tracking-wide text-muted-foreground",
                  )}
                >
                  Kategoria
                </th>
                {view.roles.map((role) => (
                  <RoleHeader
                    key={role.key}
                    role={role}
                    average={perPersonAverage(view, role, cells)}
                    savedAverage={perPersonAverage(view, role)}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {view.categories.map((category) => (
                <CategoryRows
                  key={category.key}
                  category={category}
                  roles={view.roles}
                  cells={cells}
                  expanded={expanded.has(category.key)}
                  disabled={disabled}
                  onExpand={() => toggleExpanded(category.key)}
                  onToggleCategory={(role) =>
                    edit(toggleCategory(view, cells, role, category.key))
                  }
                  onToggleGroup={(role, group) =>
                    edit(toggleGroup(view, cells, role, group))
                  }
                />
              ))}
            </tbody>
          </table>
        </div>

        <div className="sticky bottom-0 z-20 flex flex-wrap items-center justify-between gap-3 rounded-b-xl border-t border-border bg-card px-4 py-3">
          <p className="text-sm text-muted-foreground" aria-live="polite">
            Zmiany: {changes.length}
            {notice?.kind === "saved" && !dirty ? " · Zapisano." : ""}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={resetDraft} disabled={!dirty || saving}>
              <RotateCcw className="size-4" aria-hidden /> Cofnij
            </Button>
            <Button
              onClick={() => setConfirmOpen(true)}
              disabled={!dirty || !canWrite}
              loading={saving}
            >
              <Save className="size-4" aria-hidden /> Zapisz zmiany
            </Button>
          </div>
        </div>
      </section>

      {updatedAt ? (
        <p className="text-xs text-muted-foreground">
          Ostatnia zmiana: {updatedAt}
          {view.updated_by_name ? ` · ${view.updated_by_name}` : ""}
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Liczba = powiadomienia do wszystkich osób z tej roli w {view.window_days} dni.
        Konto z kilkoma rolami przestaje dostawać grupę dopiero, gdy jest
        wyłączona we wszystkich jego rolach.
      </p>

      <AppModal
        open={confirmOpen}
        onOpenChange={(open) => {
          // Esc, „×” i kliknięcie obok nie zamykają okna w trakcie zapisu.
          if (!saving) setConfirmOpen(open);
        }}
        title="Potwierdź zmianę powiadomień ról"
        description="Zmiana działa od razu dla wszystkich kont z tych ról. Nikt nie zostanie wylogowany."
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={saving}>
              Anuluj
            </Button>
            <Button onClick={() => mutation.mutate()} disabled={!dirty} loading={saving}>
              Potwierdź i zapisz
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-foreground">
          {summary.map(({ role, off, on }) => (
            <div key={role.key}>
              <p className="font-medium">
                {role.label} ({accountsLabel(role.accounts)})
              </p>
              {off.length > 0 ? (
                <>
                  <p className="mt-1 text-muted-foreground">Przestanie dostawać:</p>
                  <ul className="list-disc space-y-0.5 pl-5">
                    {off.map((label) => (
                      <li key={label}>{label}</li>
                    ))}
                  </ul>
                </>
              ) : null}
              {on.length > 0 ? (
                <>
                  <p className="mt-1 text-muted-foreground">Zacznie znowu dostawać:</p>
                  <ul className="list-disc space-y-0.5 pl-5">
                    {on.map((label) => (
                      <li key={label}>{label}</li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          ))}
        </div>
      </AppModal>
    </div>
  );
}

export function NotificationRoleMatrix() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);
  const canRead = hasRole(user, "admin") && hasSectionAccess(user, "system_admin", "read");
  const canWrite = canRead && hasSectionAccess(user, "system_admin", "write");
  const query = useNotificationRoles(hydrated && canRead);

  if (!hydrated) return <p role="status">Ładowanie ustawień…</p>;
  if (!canRead) return <QueryStateNotice state="forbidden" />;
  if (query.isPending) {
    return (
      <div
        role="status"
        className="flex min-h-64 items-center justify-center rounded-xl border border-border bg-card text-sm text-muted-foreground"
      >
        Wczytywanie tabeli powiadomień…
      </div>
    );
  }
  // Brak odpowiedzi albo odpowiedź bez ról i kategorii to awaria odczytu —
  // nie pusta tabela („nikt nic nie dostaje”).
  if (!viewIsUsable(query.data)) {
    return (
      <QueryStateNotice
        state={query.isError && isForbiddenError(query.error) ? "forbidden" : "error"}
        description={
          query.isError && isForbiddenError(query.error)
            ? undefined
            : "Nie udało się pobrać tabeli powiadomień ról."
        }
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  return (
    <div className="space-y-3">
      {/* Nieudane odświeżenie w tle nie zdejmuje tabeli — razem z nią
          przepadłyby niezapisane przełączniki. */}
      {query.isError ? (
        <Alert
          variant="warning"
          title="Nie udało się odświeżyć tabeli"
          description="Widzisz ostatnio wczytaną wersję. Odśwież stronę, zanim coś zapiszesz."
        />
      ) : null}
      <RoleMatrixEditor view={query.data} canWrite={canWrite} />
    </div>
  );
}

export default NotificationRoleMatrix;
