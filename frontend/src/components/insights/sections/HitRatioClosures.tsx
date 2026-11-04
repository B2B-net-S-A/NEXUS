"use client";

/**
 * Raport „Zamknięcia i hit ratio” (decyzja Artura 21.10.2026, makieta 4).
 *
 * Przegraną jest tylko rekrutacja, którą wzięła inna firma; „Nie liczy się”
 * wymaga uzasadnienia, a kontrola jest po fakcie — tu widać każde wyłączenie
 * z uzasadnieniem i osobą oraz zamknięcia bez powodu, które do przeglądu liczą
 * się jak przegrane. „Zmień powód” = to samo okno co na stronie rekrutacji.
 */

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { JobCloseWithReasonDialog } from "@/components/v2/jobs/JobCloseWithReasonDialog";
import { formatIsoDatePl } from "@/lib/date-pl";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type HitRatioClosureRow,
} from "@/lib/insights-api";
import { closeReasonLabel } from "@/lib/job-close-reasons";
import { hasPermission } from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";

import { LoadingSpinner, SectionError } from "./_shared";

const TILE_TONE = {
  won: "text-info-muted-foreground",
  lost: "text-warning-muted-foreground",
  neutral: "text-foreground",
  unreviewed: "text-warning-muted-foreground",
} as const;

export function HitRatioClosures() {
  const queryClient = useQueryClient();
  // PATCH /close-reason wymaga „recruitment_manage” — bez niego raport jest
  // tylko do odczytu (Rada nadzorcza, Finanse; audyt 22.10.2026).
  const canChangeReason = hasPermission(
    useAuthStore((s) => s.user),
    "recruitment_manage",
  );
  const [editing, setEditing] = useState<HitRatioClosureRow | null>(null);
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.hitRatioClosures(),
    queryFn: insightsBoardApi.hitRatioClosures,
  });

  if (isPending) return <LoadingSpinner />;
  if (isError || !isSuccess) {
    return (
      <SectionError label="Zamknięcia i hit ratio" error={error} onRetry={() => void refetch()} />
    );
  }

  const { counts } = data;
  const tiles = [
    {
      key: "hit",
      label: "Hit ratio",
      value: data.hit_ratio === null ? "—" : `${String(data.hit_ratio).replace(".", ",")}%`,
      hint: `${counts.won} wygranych z ${counts.won + counts.lost + counts.unreviewed} liczonych`,
      tone: "text-foreground",
    },
    { key: "won", label: "Wygrane", value: String(counts.won), hint: "z zatrudnieniem od nas", tone: TILE_TONE.won },
    {
      key: "lost",
      label: "Przegrane",
      value: String(counts.lost + counts.unreviewed),
      hint: counts.unreviewed
        ? `w tym ${counts.unreviewed} do przejrzenia`
        : "wzięła inna firma",
      tone: TILE_TONE.lost,
    },
    {
      key: "neutral",
      label: "Nie liczą się",
      value: String(counts.neutral),
      hint: "duplikaty, wewnętrzne, anulowane…",
      tone: TILE_TONE.neutral,
    },
  ];

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">
        Zamknięte od {formatIsoDatePl(data.since)}. Przegraną jest tylko rekrutacja, którą wzięła
        inna firma.
      </p>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.key} className="rounded-xl border border-border bg-card p-4">
            <div className="text-xs text-muted-foreground">{t.label}</div>
            <div className={`text-2xl font-semibold ${t.tone}`}>{t.value}</div>
            <div className="text-xs text-muted-foreground">{t.hint}</div>
          </div>
        ))}
      </div>

      <ClosureTable
        title="Do przejrzenia"
        lede="Zamknięte z powodem „Inny” albo bez powodu. Do przeglądu liczą się jak przegrane — wybierz, jak się skończyły."
        rows={data.unreviewed}
        empty="Nic nie czeka na przegląd."
        onEdit={canChangeReason ? setEditing : null}
        testId="closures-unreviewed"
      />
      <ClosureTable
        title="Zamknięte poza hit ratio"
        lede="Kto i dlaczego wyłączył rekrutację. Zmiana powodu zostaje w historii rekrutacji."
        rows={data.neutral}
        empty="Żadna rekrutacja nie została wyłączona z hit ratio."
        onEdit={canChangeReason ? setEditing : null}
        testId="closures-neutral"
      />

      {editing && canChangeReason ? (
        <JobCloseWithReasonDialog
          mode="change"
          open
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          jobId={editing.job_id}
          jobTitle={editing.title}
          clientId={editing.client_id}
          initial={{
            reason: editing.close_reason,
            notes: editing.close_notes,
            duplicateOfJobId: editing.duplicate_of_job_id,
          }}
          onClosed={() =>
            void queryClient.invalidateQueries({ queryKey: insightsQueryKeys.hitRatioClosures() })
          }
        />
      ) : null}
    </div>
  );
}

function ClosureTable({
  title,
  lede,
  rows,
  empty,
  onEdit,
  testId,
}: {
  title: string;
  lede: string;
  rows: HitRatioClosureRow[];
  empty: string;
  onEdit: ((row: HitRatioClosureRow) => void) | null;
  testId: string;
}) {
  return (
    <section className="space-y-2" data-testid={testId}>
      <div>
        <h3 className="text-base font-semibold text-foreground">
          {title} <span className="text-muted-foreground">· {rows.length}</span>
        </h3>
        <p className="text-sm text-muted-foreground">{lede}</p>
      </div>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          {empty}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full min-w-[56rem] text-sm">
            <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Rekrutacja</th>
                <th className="px-3 py-2 font-medium">Klient</th>
                <th className="px-3 py-2 font-medium">Powód</th>
                <th className="px-3 py-2 font-medium">Uzasadnienie</th>
                <th className="px-3 py-2 font-medium">Zamknął(a)</th>
                <th className="px-3 py-2 font-medium">Zamknięta</th>
                {onEdit ? <th className="px-3 py-2" aria-label="Akcje" /> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.job_id} className="border-t border-border align-top">
                  <td className="px-3 py-2">
                    <Link href={`/jobs/${row.job_id}`} className="font-medium text-primary hover:underline">
                      {row.title}
                    </Link>
                  </td>
                  <td className="px-3 py-2">{row.client_name ?? "—"}</td>
                  <td className="px-3 py-2">{closeReasonLabel(row.close_reason)}</td>
                  <td className="max-w-[22rem] px-3 py-2 text-muted-foreground">
                    {row.close_notes ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {/* Brak wpisu w historii (zamknięcie sprzed 0048) = „—”, nie DL —
                        kolumna mówi, kto zamknął. */}
                    {row.closed_by_name ?? "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {formatIsoDatePl(row.closed_at)}
                  </td>
                  {onEdit ? (
                    <td className="px-3 py-2 text-right">
                      <Button type="button" size="sm" variant="outline" onClick={() => onEdit(row)}>
                        Zmień powód
                      </Button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
