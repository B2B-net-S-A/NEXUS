"use client";

import { Loader2, Video } from "lucide-react";
import { SectionError } from "@/components/insights/sections/_shared";
import {
  PREP_QUALITY_DEFAULT_DAYS,
  formatTalkShare,
  usePrepQuality,
  type PrepQualityRow,
} from "@/lib/api/prepQuality";
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
            </p>
          ) : null}
          {viewState === "empty" ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              W tym okresie nie było prepów założonych z NEXUSA.
            </p>
          ) : (
            <PrepQualityTable rows={rows} />
          )}
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
