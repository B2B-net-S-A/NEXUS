"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, History, RotateCcw } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  describeKpiEvent,
  parseTargetInput,
  useKpiTargetHistory,
  useKpiTargets,
  useSaveRoleDefault,
  useSaveUserTarget,
  type KpiTargetKpi,
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
              void onSave(null).catch((err) =>
                setError(apiErrorMessage(err, "Nie udało się przywrócić celu.")),
              );
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
      <div className="text-xs text-muted-foreground">
        {kpi.period_label}
        {kpi.race_threshold ? " · próg wyścigu" : ""}
      </div>
    </div>
  );
}

export function KpiRoleTable({
  data,
  busy,
  onSave,
}: {
  data: KpiTargetsMatrix;
  busy: boolean;
  onSave: (role: string, kpiId: string, value: number | null) => Promise<void>;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Wskaźnik</th>
            {data.roles.map((role) => (
              <th key={role.role} className="px-3 py-2">
                {role.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.kpis.map((kpi) => (
            <tr key={kpi.kpi_id} className="border-t border-border align-top">
              <td className="px-3 py-2">
                <KpiHeader kpi={kpi} />
              </td>
              {data.roles.map((role) => {
                const cell = role.targets[kpi.kpi_id];
                return (
                  <td key={role.role} className="px-3 py-2">
                    <TargetCell
                      label={`${kpi.title} — ${role.label}`}
                      value={cell.override}
                      fallback={cell.catalog_default}
                      disabled={busy}
                      onSave={(value) => onSave(role.role, kpi.kpi_id, value)}
                    />
                    <span className="text-xs text-muted-foreground">
                      katalog: {cell.catalog_default}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function KpiUserTable({
  data,
  busy,
  onSave,
}: {
  data: KpiTargetsMatrix;
  busy: boolean;
  onSave: (userId: number, kpiId: string, value: number | null) => Promise<void>;
}) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const users = needle
    ? data.users.filter((user) => user.name.toLowerCase().includes(needle))
    : data.users;
  return (
    <div className="space-y-2">
      <input
        type="search"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        placeholder="Szukaj osoby…"
        aria-label="Szukaj osoby"
        className="h-8 w-full max-w-xs rounded-md border border-input bg-background px-2 text-sm"
      />
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2">Osoba</th>
              {data.kpis.map((kpi) => (
                <th key={kpi.kpi_id} className="px-3 py-2 normal-case">
                  <KpiHeader kpi={kpi} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.length === 0 ? (
              <tr>
                <td
                  colSpan={data.kpis.length + 1}
                  className="px-3 py-4 text-center text-muted-foreground"
                >
                  {data.users.length === 0
                    ? "Nikt nie ma dziś roli rekrutera, sourcera ani TAC."
                    : "Żadna osoba nie pasuje do wyszukiwania."}
                </td>
              </tr>
            ) : null}
            {users.map((user) => (
              <tr key={user.user_id} className="border-t border-border align-top">
                <td className="px-3 py-2">
                  <div className="font-medium text-foreground">{user.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {user.roles.join(", ")}
                  </div>
                </td>
                {data.kpis.map((kpi) => {
                  const cell = user.targets[kpi.kpi_id];
                  return (
                    <td key={kpi.kpi_id} className="px-3 py-2">
                      <TargetCell
                        label={`${kpi.title} — ${user.name}`}
                        value={cell.override}
                        fallback={cell.effective}
                        disabled={busy}
                        onSave={(value) => onSave(user.user_id, kpi.kpi_id, value)}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
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

  return (
    <div className="space-y-8">
      <div
        role="note"
        className="flex gap-3 rounded-lg border border-warning/40 bg-warning-muted p-3 text-sm text-warning-muted-foreground"
      >
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <p>
          Cele roli dla wskaźników oznaczonych „próg wyścigu” są też progiem
          Wyścigu Rekomendacji (nagroda 1 500 zł). W wyścigu zmiana obowiązuje
          od następnego miesiąca — progi bieżącego miesiąca są zapisane na jego
          początku, więc edycja celu nie przestawia trwającego wyścigu. Minimum
          placementów w Wyścigu Placementów ustawia administrator w punktacji
          Insights.
        </p>
      </div>

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">Cele ról</h2>
          <p className="text-sm text-muted-foreground">
            Puste pole = wartość z katalogu. Osoba z kilkoma rolami dostaje
            najwyższy cel ze swoich ról.
          </p>
        </div>
        <KpiRoleTable
          data={query.data}
          busy={busy}
          onSave={async (role, kpiId, value) => {
            await saveRole.mutateAsync({
              role: role as "recruiter" | "sourcer" | "tac",
              kpi_id: kpiId,
              target_value: value,
            });
          }}
        />
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">Cele osobiste</h2>
          <p className="text-sm text-muted-foreground">
            Osobisty cel wygrywa z celem ról. Szary placeholder to cel, który
            obowiązuje tę osobę dziś.
          </p>
        </div>
        <KpiUserTable
          data={query.data}
          busy={busy}
          onSave={async (userId, kpiId, value) => {
            await saveUser.mutateAsync({
              user_id: userId,
              kpi_id: kpiId,
              target_value: value,
            });
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
