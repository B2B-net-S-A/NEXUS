"use client";

import { Loader2, Video } from "lucide-react";
import { SectionError } from "@/components/insights/sections/_shared";
import {
  PREP_QUALITY_DEFAULT_DAYS,
  formatTalkShare,
  usePrepQuality,
  type Prep2SkipRow,
  type PrepQualityRow,
} from "@/lib/api/prepQuality";
import { PREP2_SKIP_REASON_LABELS, type Prep2SkipReason } from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";

const LABEL = "Jakość prepów";

function n(value: number): string {
  return value.toLocaleString("pl-PL");
}

/**
 * „Jakość prepów" (0370) — prepy z kandydatem przed rozmową u klienta,
 * założone z NEXUSA w Teams, per organizator. Tylko admin i Head of
 * Recruitment (serwer odmawia reszcie 403; rozdział w ogóle nie montuje sekcji
 * innym rolom). Okno jest stałe (90 dni) i NIE zależy od paska okresu —
 * prepów jest za mało, żeby miesiąc coś mówił.
 *
 * Ocena (dobry / OK / słaby) i udział kandydata w rozmowie pochodzą
 * z transkryptu; prep bez nagrania nie ma oceny.
 */
export function PrepQualitySection() {
  const { data, isPending, isSuccess, isError, error, refetch } =
    usePrepQuality(PREP_QUALITY_DEFAULT_DAYS);
  const rows = data?.rows ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: rows.length === 0,
  });

  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-foreground">
        <Video className="h-5 w-5 text-primary" />
        {LABEL}
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          Ostatnie {data?.days ?? PREP_QUALITY_DEFAULT_DAYS} dni · prepy z Teams
        </span>
      </h2>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-8">
          <Loader2
            className="h-5 w-5 animate-spin text-muted-foreground"
            aria-label="Wczytywanie"
          />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label={LABEL}
          error={error}
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          {data ? (
            <p className="mb-4 text-sm text-foreground">
              Rozmowy u klienta z dwoma prepami:{" "}
              <span className="font-semibold tabular-nums">
                {n(data.interviews_with_two_preps)} z {n(data.interviews)}
              </span>
              {/* Rozmowy zapisane po fakcie nie miały szansy na prepy w NEXUSIE (F28). */}
              {data.interviews_after_the_fact ? (
                <span className="text-muted-foreground">
                  {" "}
                  · bez rozmów zapisanych po fakcie: {n(data.interviews_after_the_fact)}
                </span>
              ) : null}
            </p>
          ) : null}
          {viewState === "empty" ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              W tym okresie nie było prepów założonych z NEXUSA.
            </p>
          ) : (
            <PrepQualityTable rows={rows} />
          )}
          {data?.skip_rows && data.skip_rows.length > 0 ? (
            <Prep2SkipTable
              rows={data.skip_rows}
              days={data.skip_days ?? 30}
              threshold={data.skip_threshold ?? 0.2}
            />
          ) : null}
        </>
      )}
    </section>
  );
}

function PrepQualityTable({ rows }: { rows: PrepQualityRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th scope="col" className="py-2 pr-3 font-medium">
              Prowadzący
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Prepy
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Z nagraniem
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Bez nagrania
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Dobry / OK / Słaby
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              Śr. udział kandydata
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.organizer.id}
              data-testid={`prep-quality-row-${row.organizer.id}`}
              className="border-b border-border last:border-0"
            >
              <td className="py-1.5 pr-3 font-medium text-foreground">
                {row.organizer.name}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-foreground">
                {n(row.preps)}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-foreground">
                {n(row.recorded)}
              </td>
              <td
                className={`py-1.5 pr-3 text-right tabular-nums ${
                  row.unrecorded > 0
                    ? "text-warning-muted-foreground"
                    : "text-foreground"
                }`}
              >
                {n(row.unrecorded)}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-foreground">
                <span className="text-success">{n(row.good)}</span>
                {" / "}
                {n(row.ok)}
                {" / "}
                <span className={row.weak > 0 ? "text-destructive" : undefined}>
                  {n(row.weak)}
                </span>
              </td>
              <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                {formatTalkShare(row.avg_talk_share)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function reasonsLine(reasons: Record<string, number>): string {
  return Object.entries(reasons)
    .sort((a, b) => b[1] - a[1])
    .map(([key, count]) => `${PREP2_SKIP_REASON_LABELS[key as Prep2SkipReason] ?? key} ×${count}`)
    .join(", ");
}

/**
 * Rozmowy bez Prepu 2 (0482, decyzja Artura 20.10.2026): hamulcem na „zawsze
 * nie ma czasu” jest pomiar, nie blokada. Osoba ponad progiem (i z co najmniej
 * dwiema rozmowami) świeci się na pomarańczowo.
 */
export function Prep2SkipTable({
  rows,
  days,
  threshold,
}: {
  rows: Prep2SkipRow[];
  days: number;
  threshold: number;
}) {
  return (
    <div className="mt-6" data-testid="prep2-skip-table">
      <h3 className="mb-1 text-sm font-semibold text-foreground">
        Rozmowy bez Prepu 2 · ostatnie {days} dni
      </h3>
      <p className="mb-3 text-xs text-muted-foreground">
        „Z powodem” — rekruter zapisał powód i zadzwonił do kandydata przed rozmową. „Bez słowa” —
        rozmowa się odbyła, prepów było mniej niż dwa i nikt nie zapisał dlaczego. „Zapisane po
        fakcie” — rozmowę wpisano do NEXUSA dopiero po niej (pytania z datą wstecz, import z
        notatek), więc nie dało się zaplanować prepów ani zapisać powodu. Próg: powyżej{" "}
        {pct(threshold)} rozmów z powodem.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th scope="col" className="py-2 pr-3 font-medium">
                Osoba
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Rozmowy u klienta
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Bez Prepu 2 (z powodem)
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Pominięte bez słowa
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Zapisane po fakcie
              </th>
              <th scope="col" className="py-2 font-medium">
                Powody
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.person.id}
                data-testid={`prep2-skip-row-${row.person.id}`}
                data-over={row.over_threshold ? "true" : undefined}
                className={cn(
                  "border-b border-border last:border-0",
                  row.over_threshold && "bg-warning-muted/60",
                )}
              >
                <td className="py-1.5 pr-3 font-medium text-foreground">
                  {row.person.name}
                  {row.over_threshold ? (
                    <span className="ml-2 rounded-full bg-warning-muted px-2 py-0.5 text-xs font-semibold text-warning-muted-foreground">
                      powyżej progu
                    </span>
                  ) : null}
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-foreground">
                  {n(row.interviews)}
                </td>
                <td
                  className={cn(
                    "py-1.5 pr-3 text-right tabular-nums",
                    row.over_threshold
                      ? "font-semibold text-warning-muted-foreground"
                      : "text-foreground",
                  )}
                >
                  {n(row.with_reason)}
                  {row.with_reason > 0 ? ` · ${pct(row.share)}` : ""}
                </td>
                <td
                  className={cn(
                    "py-1.5 pr-3 text-right tabular-nums",
                    row.silent > 0 ? "font-semibold text-destructive" : "text-foreground",
                  )}
                >
                  {n(row.silent)}
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-muted-foreground">
                  {n(row.after_the_fact ?? 0)}
                </td>
                <td className="py-1.5 text-xs text-muted-foreground">
                  {reasonsLine(row.reasons) || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
