"use client";

import { useEffect, useState } from "react";
import { History, RotateCcw } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  describeKpiEvent,
  parseTargetInput,
  useKpiTargetHistory,
  useKpiTargets,
  useSaveRoleDefault,
  useSaveUserTarget,
  type KpiTargetKpi,
  type KpiTargetRole,
  type KpiTargetsMatrix,
} from "@/lib/api/kpiTargets";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { isForbiddenError } from "@/lib/view-state";

/**
 * Ustawienia → Rekrutacja → Cele KPI (plan PR3, 23.09.2026).
 *
 * Admin i Head of Recruitment zmieniają cele bez deployu. Pole puste =
 * „przywróć" (katalog dla roli, cel z ról dla osoby). Zapis idzie przy
 * opuszczeniu pola albo Enterze — tylko wtedy, gdy wartość się zmieniła.
 */

interface CellProps {
  label: string;
  /** Zapisane odstępstwo; `null` = obowiązuje wartość domyślna. */
  value: number | null;
  /** Wartość, która obowiązuje bez odstępstwa (placeholder). */
  fallback: number;
  disabled?: boolean;
  onSave: (value: number | null) => Promise<void>;
}

function TargetCell({ label, value, fallback, disabled, onSave }: CellProps) {
  const [draft, setDraft] = useState(value === null ? "" : String(value));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(value === null ? "" : String(value));
  }, [value]);

  async function commit() {
    const parsed = parseTargetInput(draft);
    if (parsed === "invalid") {
      setError("Wpisz liczbę całkowitą od 0 do 100 000.");
      return;
    }
    setError(null);
    if (parsed === value) return;
    try {
      await onSave(parsed);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zapisać celu."));
      setDraft(value === null ? "" : String(value));
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1">
        <input
          type="text"
          inputMode="numeric"
          aria-label={label}
          aria-invalid={error ? true : undefined}
          disabled={disabled}
          value={draft}
          placeholder={String(fallback)}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => void commit()}
          onKeyDown={(event) => {
            if (event.key === "Enter") (event.target as HTMLInputElement).blur();
          }}
          className={cn(
            "h-8 w-20 rounded-md border border-input bg-background px-2 text-sm tabular-nums",
            value !== null && "border-primary font-semibold text-primary",
            error && "border-destructive",
          )}
        />
        {value !== null && !disabled ? (
          <button
            type="button"
            onClick={() => {
              setDraft("");
              void onSave(null).catch((err) => {
                setError(apiErrorMessage(err, "Nie udało się przywrócić celu."));
                setDraft(value === null ? "" : String(value));
              });
            }}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label={`Przywróć: ${label}`}
            title="Przywróć wartość domyślną"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
      {error ? (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      ) : null}
    </div>
  );
}

function KpiHeader({ kpi }: { kpi: KpiTargetKpi }) {
  return (
    <div>
      <div className="font-medium text-foreground">{kpi.title}</div>
      <div className="text-xs text-muted-foreground">{kpi.period_label}</div>
    </div>
  );
}

/** Cel roli jako kafelki (20.10.2026) — jedna rola od 0411, więc tabela
 *  wskaźnik × rola miała jedną kolumnę. */
export function KpiRoleTiles({
  data,
  busy,
  onSave,
}: {
  data: KpiTargetsMatrix;
  busy: boolean;
  onSave: (role: string, kpiId: string, value: number | null) => Promise<void>;
}) {
  return (
    <div className="space-y-4">
      {data.roles.map((role) => (
        <div key={role.role} className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">
            Cel roli: {role.label}
            <span className="ml-2 font-normal text-muted-foreground">
              obowiązuje każdego, kto nie ma wyjątku
            </span>
          </h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {data.kpis.map((kpi) => {
              const cell = role.targets[kpi.kpi_id];
              return (
                <div
                  key={kpi.kpi_id}
                  className="flex flex-col gap-2 rounded-xl border border-border bg-card p-3"
                >
                  <KpiHeader kpi={kpi} />
                  <TargetCell
                    label={`${kpi.title} — ${role.label}`}
                    value={cell.override}
                    fallback={cell.catalog_default}
                    disabled={busy}
                    onSave={(value) => onSave(role.role, kpi.kpi_id, value)}
                  />
                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    <span>katalog: {cell.catalog_default}</span>
                    {kpi.race_threshold ? (
                      <span className="rounded-full bg-warning-muted px-2 py-0.5 font-medium text-warning-muted-foreground">
                        próg wyścigu
                      </span>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Cel, który osoba miałaby bez wyjątku: maksimum z jej ról (`services/kpi_targets.py`). */
function roleTargetFor(data: KpiTargetsMatrix, roles: string[], kpiId: string): number | null {
  const values = data.roles
    .filter((role) => roles.includes(role.role))
    .map((role) => role.targets[kpiId]?.effective)
    .filter((value): value is number => typeof value === "number");
  return values.length ? Math.max(...values) : null;
}

/** Wyjątki zamiast tabeli wszystkich osób (20.10.2026): widać tylko osoby
 *  z osobistym celem, a nowy wyjątek dodaje się formularzem. */
export function KpiExceptions({
  data,
  busy,
  onSave,
}: {
  data: KpiTargetsMatrix;
  busy: boolean;
  onSave: (userId: number, kpiId: string, value: number | null) => Promise<void>;
}) {
  const rows = data.users.flatMap((user) =>
    data.kpis
      .filter((kpi) => user.targets[kpi.kpi_id]?.override != null)
      .map((kpi) => ({ user, kpi, cell: user.targets[kpi.kpi_id] })),
  );
  const people = new Set(rows.map((row) => row.user.user_id)).size;
  return (
    <div className="space-y-3">
      <AddException data={data} busy={busy} onSave={onSave} />
      <div className="relative overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <caption className="sr-only">Wyjątki od celu roli ({people})</caption>
          <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2">Osoba</th>
              <th className="px-3 py-2">Wskaźnik</th>
              <th className="px-3 py-2">Cel osoby</th>
              <th className="px-3 py-2">Cel roli</th>
              <th className="px-3 py-2">
                <span className="sr-only">Akcje</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-center text-muted-foreground">
                  {data.users.length === 0
                    ? "Nikt nie ma dziś roli rekrutera."
                    : "Nikt nie ma wyjątku — wszystkich obowiązuje cel roli."}
                </td>
              </tr>
            ) : null}
            {rows.map(({ user, kpi, cell }) => {
              const label = `${kpi.title} — ${user.name}`;
              return (
                <tr key={`${user.user_id}-${kpi.kpi_id}`} className="border-t border-border align-top">
                  <td className="px-3 py-2 font-medium text-foreground">{user.name}</td>
                  <td className="px-3 py-2">
                    <KpiHeader kpi={kpi} />
                  </td>
                  <td className="px-3 py-2">
                    <TargetCell
                      label={label}
                      value={cell.override}
                      fallback={roleTargetFor(data, user.roles, kpi.kpi_id) ?? cell.effective}
                      disabled={busy}
                      onSave={(value) => onSave(user.user_id, kpi.kpi_id, value)}
                    />
                  </td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">
                    {roleTargetFor(data, user.roles, kpi.kpi_id) ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <RemoveException
                      label={label}
                      disabled={busy}
                      onRemove={() => onSave(user.user_id, kpi.kpi_id, null)}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** „Usuń” wyjątku — błąd zapisu zostaje w wierszu, jak w polu celu. */
function RemoveException({
  label,
  disabled,
  onRemove,
}: {
  label: string;
  disabled: boolean;
  onRemove: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          setError(null);
          void onRemove().catch((err) =>
            setError(apiErrorMessage(err, "Nie udało się usunąć wyjątku.")),
          );
        }}
        aria-label={`Usuń wyjątek: ${label}`}
        className="text-xs font-semibold text-primary hover:underline disabled:opacity-50"
      >
        Usuń
      </button>
      {error ? (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      ) : null}
    </div>
  );
}

function AddException({
  data,
  busy,
  onSave,
}: {
  data: KpiTargetsMatrix;
  busy: boolean;
  onSave: (userId: number, kpiId: string, value: number | null) => Promise<void>;
}) {
  const [userId, setUserId] = useState("");
  const [kpiId, setKpiId] = useState(data.kpis[0]?.kpi_id ?? "");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const user = data.users.find((u) => String(u.user_id) === userId);
  const roleTarget = user ? roleTargetFor(data, user.roles, kpiId) : null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const parsed = parseTargetInput(value);
    if (!user) {
      setError("Wybierz osobę.");
      return;
    }
    if (parsed === null || parsed === "invalid") {
      setError("Wpisz liczbę całkowitą od 0 do 100 000.");
      return;
    }
    setError(null);
    try {
      await onSave(user.user_id, kpiId, parsed);
      setValue("");
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się dodać wyjątku."));
    }
  }

  const field = "h-9 rounded-md border border-input bg-background px-2 text-sm";
  return (
    <form
      onSubmit={(event) => void submit(event)}
      aria-label="Dodaj wyjątek"
      className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-muted/30 p-3"
    >
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        Osoba
        <select value={userId} onChange={(e) => setUserId(e.target.value)} className={cn(field, "min-w-48")}>
          <option value="">Wybierz osobę…</option>
          {data.users.map((u) => (
            <option key={u.user_id} value={u.user_id}>
              {u.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        Wskaźnik
        <select value={kpiId} onChange={(e) => setKpiId(e.target.value)} className={field}>
          {data.kpis.map((kpi) => (
            <option key={kpi.kpi_id} value={kpi.kpi_id}>
              {kpi.title}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        Cel osoby
        <input
          type="text"
          inputMode="numeric"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={roleTarget === null ? "" : String(roleTarget)}
          className={cn(field, "w-24 tabular-nums")}
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        className="h-9 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        Dodaj wyjątek
      </button>
      {error ? (
        <span role="alert" className="basis-full text-xs text-destructive">
          {error}
        </span>
      ) : null}
    </form>
  );
}

function KpiHistory() {
  const history = useKpiTargetHistory();
  if (history.isError) {
    return (
      <QueryStateNotice
        state="error"
        onRetry={() => void history.refetch()}
        description="Nie udało się pobrać historii zmian celów."
      />
    );
  }
  if (!history.isSuccess) {
    return <p role="status" className="text-sm text-muted-foreground">Ładowanie historii…</p>;
  }
  if (history.data.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Nikt jeszcze nie zmienił celów w aplikacji — obowiązuje katalog.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border text-sm">
      {history.data.map((event) => (
        <li key={event.id} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
          <span className="text-foreground">{describeKpiEvent(event)}</span>
          <span className="text-xs text-muted-foreground">
            {event.actor_name ?? "—"}
            {event.created_at
              ? ` · ${new Date(event.created_at).toLocaleString("pl-PL")}`
              : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function KpiTargetsSettings() {
  const query = useKpiTargets();
  const saveRole = useSaveRoleDefault();
  const saveUser = useSaveUserTarget();
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  if (query.isError) {
    return (
      <QueryStateNotice
        state={isForbiddenError(query.error) ? "forbidden" : "error"}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (!query.isSuccess) {
    return <p role="status">Ładowanie celów KPI…</p>;
  }
  const busy = saveRole.isPending || saveUser.isPending;
  const exceptions = query.data.users.filter((user) =>
    Object.values(user.targets).some((cell) => cell.override != null),
  ).length;

  return (
    <div className="space-y-8">
      <p role="status" aria-live="polite" className="text-xs text-muted-foreground">
        {busy
          ? "Zapisywanie…"
          : savedAt
            ? `Zapisano ${savedAt.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}`
            : "Zmiana zapisuje się po wyjściu z pola albo Enterze."}
      </p>

      <section className="space-y-3">
        <KpiRoleTiles
          data={query.data}
          busy={busy}
          onSave={async (role, kpiId, value) => {
            await saveRole.mutateAsync({
              role: role as KpiTargetRole,
              kpi_id: kpiId,
              target_value: value,
            });
            setSavedAt(new Date());
          }}
        />
        <p role="note" className="text-xs text-muted-foreground">
          „Próg wyścigu” to też próg Wyścigu Rekomendacji (1 500 zł) — tam zmiana
          działa od następnego miesiąca, trwający wyścig liczy się po staremu.
          Minimum placementów w Wyścigu Placementów ustawia administrator
          w punktacji Insights. Puste pole = wartość z katalogu.
        </p>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">
            Wyjątki <span className="font-normal text-muted-foreground">({exceptions})</span>
          </h2>
          <p className="text-sm text-muted-foreground">
            Osoba z wyjątkiem ma swój cel zamiast celu roli. Usuń wyjątek, żeby wróciła do celu roli.
          </p>
        </div>
        <KpiExceptions
          data={query.data}
          busy={busy}
          onSave={async (userId, kpiId, value) => {
            await saveUser.mutateAsync({
              user_id: userId,
              kpi_id: kpiId,
              target_value: value,
            });
            setSavedAt(new Date());
          }}
        />
      </section>

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <History className="h-4 w-4" aria-hidden /> Historia zmian
        </h2>
        <KpiHistory />
      </section>
    </div>
  );
}
