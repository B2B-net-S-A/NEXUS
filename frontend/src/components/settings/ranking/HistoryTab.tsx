"use client";

import { useState } from "react";
import { AlertTriangle, Check, Loader2 } from "lucide-react";

import type {
  RankingChange,
  RankingMeasurement,
  RankingMetrics,
  RankingPanelState,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import {
  METRIC_LABELS,
  describeChange,
  formatDateTime,
  formatMetric,
  metricDelta,
} from "./rankingCopy";

const METRICS: (keyof RankingMetrics)[] = ["page1_hit", "median_first", "top50_share", "proposals"];
const MIN_REASON = 10;

export interface HistoryTabProps {
  state: RankingPanelState;
  canEdit: boolean;
  busy: boolean;
  actionError: string | null;
  onPublish: (reason: string | null) => void;
  onRetry: () => void;
  onRestore: (changeId: number) => void;
  onBackToWeights: () => void;
}

export function HistoryTab({
  state,
  canEdit,
  busy,
  actionError,
  onPublish,
  onRetry,
  onRestore,
  onBackToWeights,
}: HistoryTabProps) {
  return (
    <div className="space-y-5">
      <MeasurementCard
        state={state}
        canEdit={canEdit}
        busy={busy}
        actionError={actionError}
        onPublish={onPublish}
        onRetry={onRetry}
        onBackToWeights={onBackToWeights}
      />
      <HistoryTable history={state.history} canEdit={canEdit} busy={busy} onRestore={onRestore} />
    </div>
  );
}

function MeasurementCard({
  state,
  canEdit,
  busy,
  actionError,
  onPublish,
  onRetry,
  onBackToWeights,
}: Omit<HistoryTabProps, "onRestore">) {
  const measurement = state.measurement;
  const [reason, setReason] = useState("");
  const draft = state.draft;

  if (!draft) {
    return (
      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-base font-semibold text-foreground">Szkic wag</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Nie ma szkicu. Zmień wagi w zakładce „Wagi” i kliknij „Sprawdź na historii” — NEXUS
          sprawdzi je na zamkniętych rekrutacjach, zanim zobaczy je zespół.
        </p>
      </section>
    );
  }

  const title = `Szkic: ${describeChange(state.published.weights, draft.weights)}`;
  const fresh = measurement?.fresh ?? false;
  const running = measurement && (measurement.status === "queued" || measurement.status === "running");

  return (
    <section
      aria-labelledby="ranking-measurement"
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="ranking-measurement" className="flex-1 text-base font-semibold text-foreground">
          {title}
        </h2>
        {measurement?.status === "done" && fresh && measurement.result && (
          <span className="text-xs text-muted-foreground">
            {measurement.result.jobs} zamkniętych rekrutacji
            {measurement.result.duration_s ? ` · ${formatDuration(measurement.result.duration_s)}` : ""}
          </span>
        )}
      </div>

      {running && <Running measurement={measurement} />}

      {!running && (!measurement || !fresh) && measurement?.status !== "failed" && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="flex-1 text-sm text-muted-foreground">
            Ten szkic nie był jeszcze sprawdzony na historii. Publikacja wymaga pomiaru.
          </p>
          {canEdit && (
            <button
              type="button"
              onClick={onRetry}
              disabled={busy}
              className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Sprawdź na historii
            </button>
          )}
        </div>
      )}

      {!running && measurement?.status === "failed" && (
        <div
          role="alert"
          className="flex flex-wrap items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3.5 py-3"
        >
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden />
          <p className="flex-1 text-sm text-foreground">
            {measurement.error ?? "Pomiar nie powiódł się."}
          </p>
          {canEdit && (
            <button
              type="button"
              onClick={onRetry}
              disabled={busy}
              className="min-h-10 rounded-lg border border-border bg-card px-3 text-sm text-foreground hover:bg-muted disabled:opacity-50"
            >
              Uruchom ponownie
            </button>
          )}
        </div>
      )}

      {measurement?.status === "done" && fresh && measurement.result && (
        <>
          <Verdict measurement={measurement} />
          <MetricsTable result={measurement.result} />
          {measurement.result.biggest_changes.length > 0 && (
            <details className="rounded-lg border border-border px-3.5 py-2.5">
              <summary className="cursor-pointer text-sm font-semibold text-foreground">
                Gdzie zmiana jest największa ({measurement.result.biggest_changes.length}{" "}
                {measurement.result.biggest_changes.length === 1 ? "rekrutacja" : "rekrutacje"})
              </summary>
              <ul className="mt-2.5 list-disc space-y-1 pl-4 text-sm text-muted-foreground">
                {measurement.result.biggest_changes.map((change) => (
                  <li key={change.job_id}>
                    {change.title} · pierwsza właściwa osoba z {change.before}. na {change.after}.
                    miejsce
                  </li>
                ))}
              </ul>
            </details>
          )}
          {canEdit && (
            <form
              className="flex flex-wrap items-center justify-end gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                onPublish(reason.trim() || null);
              }}
            >
              <label className="flex min-w-64 flex-1 items-center gap-2 text-sm">
                <span className="text-muted-foreground">
                  Powód zmiany{measurement.result.needs_reason ? " (wymagany)" : ""}
                </span>
                <input
                  type="text"
                  value={reason}
                  maxLength={500}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="np. DL-e zgłaszają, że osoby z pełnym stackiem są nisko"
                  className="min-h-10 w-0 min-w-0 flex-1 rounded-lg border border-border bg-card px-2.5 text-sm text-foreground"
                />
              </label>
              <button
                type="button"
                onClick={onBackToWeights}
                className="min-h-11 rounded-lg border border-border bg-card px-3.5 text-sm text-foreground hover:bg-muted"
              >
                Wróć do wag
              </button>
              <button
                type="submit"
                disabled={
                  busy ||
                  (measurement.result.needs_reason && reason.trim().length < MIN_REASON)
                }
                className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {measurement.result.needs_reason
                  ? "Opublikuj mimo spadku"
                  : "Opublikuj dla wszystkich rekrutacji"}
              </button>
            </form>
          )}
          {actionError && (
            <p role="alert" className="text-right text-sm text-destructive">
              {actionError}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Gdy któraś miara spada o więcej niż 2 pkt, publikacja wymaga powodu. Po publikacji
            „Dop.” przelicza się przy następnym otwarciu listy, nocne propozycje — od
            najbliższej nocy.
          </p>
        </>
      )}
    </section>
  );
}

function Running({ measurement }: { measurement: RankingMeasurement }) {
  const done = measurement.progress?.done ?? 0;
  const target = measurement.progress?.target ?? 120;
  const pct = Math.min(100, Math.round((done * 100) / Math.max(target, 1)));
  return (
    <div role="status" className="space-y-2">
      <p className="flex items-center gap-2 text-sm text-foreground">
        <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
        Sprawdzam szkic na zamkniętych rekrutacjach: {done} z {target}. Możesz zamknąć tę
        stronę — pomiar trwa dalej.
      </p>
      <div className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
        <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Verdict({ measurement }: { measurement: RankingMeasurement }) {
  const result = measurement.result!;
  const better = (["page1_hit", "median_first", "top50_share"] as const).filter(
    (key) => metricDelta(key, result.before[key], result.after[key]).tone === "better",
  ).length;
  const blocked = result.needs_reason;
  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-3 rounded-lg border px-3.5 py-3",
        blocked ? "border-warning/30 bg-warning-muted" : "border-success/30 bg-success-muted",
      )}
    >
      {blocked ? (
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning-muted-foreground" aria-hidden />
      ) : (
        <Check className="mt-0.5 h-5 w-5 shrink-0 text-success-muted-foreground" aria-hidden />
      )}
      <div className="space-y-0.5">
        <p
          className={cn(
            "text-sm font-semibold",
            blocked ? "text-warning-muted-foreground" : "text-success-muted-foreground",
          )}
        >
          {blocked
            ? `Któraś miara spada o ${result.max_drop_pt.toLocaleString("pl-PL")} pkt`
            : `Lepiej w ${better} z 3 miar, żadna nie spadła o więcej niż 2 pkt`}
        </p>
        <p className="text-sm text-foreground">
          {blocked
            ? "Osoby, które zespół naprawdę wysłał do klienta, byłyby niżej na liście. Opublikować można, ale z powodem."
            : "Osoby, które zespół naprawdę wysłał do klienta, są co najmniej tak samo wysoko. Możesz opublikować."}
        </p>
      </div>
    </div>
  );
}

function MetricsTable({ result }: { result: NonNullable<RankingMeasurement["result"]> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th scope="col" className="border-b border-border px-2.5 py-2 font-semibold">Miara</th>
            <th scope="col" className="border-b border-border px-2.5 py-2 text-right font-semibold">Teraz</th>
            <th scope="col" className="border-b border-border px-2.5 py-2 text-right font-semibold">Szkic</th>
            <th scope="col" className="border-b border-border px-2.5 py-2 text-right font-semibold">Zmiana</th>
          </tr>
        </thead>
        <tbody>
          {METRICS.map((key) => {
            const delta = metricDelta(key, result.before[key], result.after[key]);
            return (
              <tr key={key} className="border-b border-border last:border-0">
                <td className="px-2.5 py-2.5 text-foreground">
                  {METRIC_LABELS[key].label}
                  {METRIC_LABELS[key].hint && (
                    <span className="block text-xs text-muted-foreground">{METRIC_LABELS[key].hint}</span>
                  )}
                </td>
                <td className="px-2.5 py-2.5 text-right tabular-nums text-muted-foreground">
                  {formatMetric(key, result.before[key])}
                </td>
                <td className="px-2.5 py-2.5 text-right font-bold tabular-nums text-foreground">
                  {formatMetric(key, result.after[key])}
                </td>
                <td
                  className={cn(
                    "px-2.5 py-2.5 text-right font-bold",
                    delta.tone === "better"
                      ? "text-success"
                      : delta.tone === "worse"
                        ? "text-warning-muted-foreground"
                        : "text-muted-foreground",
                  )}
                >
                  {delta.text}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HistoryTable({
  history,
  canEdit,
  busy,
  onRestore,
}: {
  history: RankingChange[];
  canEdit: boolean;
  busy: boolean;
  onRestore: (changeId: number) => void;
}) {
  const current = history.find((change) => change.kind === "publish")?.id;
  return (
    <section
      aria-labelledby="ranking-history"
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5"
    >
      <h2 id="ranking-history" className="text-base font-semibold text-foreground">
        Historia zmian
      </h2>
      {history.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground">
          Nikt jeszcze nie zmieniał wag w NEXUSIE — działają wagi wbudowane z 17.08.2026
          (podobieństwo CV 60, umiejętności 10, lokalizacja 5).
        </p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-sm">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th scope="col" className="border-b border-border px-2.5 py-2 font-semibold">Kiedy</th>
                <th scope="col" className="border-b border-border px-2.5 py-2 font-semibold">Kto</th>
                <th scope="col" className="border-b border-border px-2.5 py-2 font-semibold">Zmiana</th>
                <th scope="col" className="border-b border-border px-2.5 py-2 font-semibold">Wynik pomiaru</th>
                <th scope="col" className="border-b border-border px-2.5 py-2 font-semibold">
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {history.map((change) => (
                <tr key={change.id} className="border-b border-border align-top last:border-0">
                  <td className="whitespace-nowrap px-2.5 py-2.5 text-foreground">
                    {formatDateTime(change.created_at)}
                  </td>
                  <td className="px-2.5 py-2.5 text-foreground">{change.actor_name ?? "—"}</td>
                  <td className="px-2.5 py-2.5 text-foreground">
                    {changeText(change)}
                    {change.reason && (
                      <span className="block text-xs text-muted-foreground">„{change.reason}”</span>
                    )}
                  </td>
                  <td className="px-2.5 py-2.5">
                    {change.measurement ? (
                      <span className="text-foreground">
                        1. strona {formatMetric("page1_hit", change.measurement.before.page1_hit)} →{" "}
                        {formatMetric("page1_hit", change.measurement.after.page1_hit)}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">bez pomiaru</span>
                    )}
                  </td>
                  <td className="px-2.5 py-2.5 text-right">
                    {change.id === current ? (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                        obowiązuje
                      </span>
                    ) : (
                      canEdit &&
                      restorable(change) && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => onRestore(change.id)}
                          className="min-h-9 rounded-lg border border-border bg-card px-2.5 text-sm text-foreground hover:bg-muted disabled:opacity-50"
                        >
                          Przywróć
                        </button>
                      )
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        „Przywróć” tworzy nowy szkic z tamtymi wagami — też przechodzi pomiar przed publikacją.
      </p>
    </section>
  );
}

/** Lustro `ranking_publish.restore`: publikacja albo edycja admina wag ogólnych. */
export function restorable(change: RankingChange): boolean {
  if (change.after?.panel) return true;
  const after = change.after ?? {};
  return Boolean(
    after.weights &&
      Object.keys(after.weights).length > 0 &&
      after.user_id == null &&
      after.client_id == null &&
      after.active !== false,
  );
}

function changeText(change: RankingChange): string {
  if (change.kind === "publish") return describeChange(change.before.panel, change.after.panel);
  const name = change.after?.name ?? change.before?.name ?? "profil";
  if (!change.after || Object.keys(change.after).length === 0) {
    return `Usunięty profil „${name}” (administrator)`;
  }
  if (!change.before || Object.keys(change.before).length === 0) {
    return `Nowy profil „${name}” (administrator)`;
  }
  return `Profil „${name}” zmieniony przez administratora`;
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes} min ${rest} s` : `${rest} s`;
}
