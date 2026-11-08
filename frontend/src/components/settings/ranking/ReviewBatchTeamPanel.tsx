"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useReviewBatchTeam, type ReviewBatchTeamRow } from "@/lib/api/reviewBatch";
import { cn } from "@/lib/utils";

const headCell = "px-2 py-1.5 text-left text-xs font-semibold text-muted-foreground";
const numberCell = "px-2 py-1.5 text-right tabular-nums";

function stuck(row: ReviewBatchTeamRow): boolean {
  return !row.absent && row.done_today < row.required && row.blocked_today > 0;
}

/**
 * Porcja zespołu dziś (audyt 08.11.2026, P8): kto ile zdecydował, kiedy zrobił
 * minimum i kto utknął na blokadzie. Liczona dopiero po rozwinięciu, bo trasa
 * przechodzi po wszystkich rekruterach.
 */
export function ReviewBatchTeamPanel() {
  const [open, setOpen] = useState(false);
  const team = useReviewBatchTeam(open);
  return (
    <div className="flex flex-col gap-2" data-testid="review-batch-team">
      <div>
        <Button size="sm" variant="outline" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? "Zwiń zespół" : "Zobacz zespół dziś"}
        </Button>
      </div>
      {open && team.isError ? (
        <p className="text-xs text-destructive" role="alert">
          {apiErrorMessage(team.error, "Nie udało się wczytać porcji zespołu.")}
        </p>
      ) : null}
      {open && team.isPending ? <p className="text-xs text-muted-foreground">Ładowanie zespołu…</p> : null}
      {open && team.isSuccess ? (
        <>
          {team.data.rows.length === 0 ? (
            <p className="text-xs text-muted-foreground">Nikt nie dostaje teraz porcji.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="border-b border-border">
                  <tr>
                    <th scope="col" className={headCell}>Osoba</th>
                    <th scope="col" className={cn(headCell, "text-right")}>Decyzje dziś</th>
                    <th scope="col" className={cn(headCell, "text-right")}>Wymagane</th>
                    <th scope="col" className={cn(headCell, "text-right")}>W porcji</th>
                    <th scope="col" className={cn(headCell, "text-right")}>Minimum o</th>
                    <th scope="col" className={cn(headCell, "text-right")}>S:O</th>
                    <th scope="col" className={cn(headCell, "text-right")}>Screeningi otwarte</th>
                    <th scope="col" className={cn(headCell, "text-right")} title="Jeden wpis na 10 minut">Blokady</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {team.data.rows.map((row) => (
                    <tr key={row.user_id} className={cn(stuck(row) && "bg-warning/10")}>
                      <td className="max-w-[200px] truncate px-2 py-1.5">
                        {row.name}
                        {row.absent ? <span className="ml-1 text-xs text-muted-foreground">nieobecność</span> : null}
                      </td>
                      <td className={numberCell}>{row.done_today}</td>
                      <td className={numberCell}>{row.required}</td>
                      <td className={numberCell}>{row.pending}</td>
                      <td className={numberCell}>{row.minimum_at ?? "—"}</td>
                      <td className={numberCell}>{row.screened}:{row.rejected}</td>
                      <td className={numberCell}>{row.open_screenings}</td>
                      <td className={numberCell}>{row.blocked_today}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {team.data.good_before_11} z {team.data.measured} zrobiło minimum przed 11:00.
            {team.data.enabled ? "" : " Porcja jest teraz wyłączona."}
          </p>
          <Streams data={team.data.streams} />
        </>
      ) : null}
    </div>
  );
}

function Streams({
  data,
}: {
  data: NonNullable<ReturnType<typeof useReviewBatchTeam>["data"]>["streams"];
}) {
  const base = data.baseline_week;
  return (
    <div className="flex flex-col gap-1 text-xs text-muted-foreground" data-testid="review-batch-streams">
      <p className="font-semibold text-foreground">
        Wysłane CV tygodniowo (baza: od systemu {base.system}, ręcznie {base.manual}, razem {base.all})
      </p>
      <ul className="tabular-nums">
        {data.weeks.map((week) => (
          <li key={week.start}>
            od {week.start}: od systemu {week.system} · ręcznie {week.manual} · razem {week.all}
            {week.complete ? "" : " (tydzień trwa)"}
          </li>
        ))}
      </ul>
      <p className={cn(data.stop && "font-semibold text-destructive")}>
        {data.stop
          ? `Kryterium zatrzymania spełnione: wysłane CV spadły o ponad ${data.stop_drop_percent}% przez ${data.stop_weeks} tygodnie.`
          : `Kryterium zatrzymania: spadek wszystkich wysłanych CV o ponad ${data.stop_drop_percent}% przez ${data.stop_weeks} pełne tygodnie.`}
      </p>
    </div>
  );
}
