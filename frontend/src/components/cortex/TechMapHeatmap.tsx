"use client";

import type { CortexTechMap } from "@/lib/api";

const SENIORITY_LABELS: Record<string, string> = {
  junior: "Junior",
  mid: "Mid",
  senior: "Senior",
  unknown: "Nieznane",
};

/**
 * Czysto prezentacyjna heatmapa skill × seniority (wzorzec rgba-table z
 * contracts/analytics). Osobny komponent, żeby /preview/cortex mógł ją
 * renderować na mockach bez react-query.
 *
 * `onCellClick` (opcjonalny) domyka pętlę do akcji: klik/Enter na komórce
 * otwiera drill-down dla danego skilla (z preselekcją seniority); klik w nazwę
 * technologii (nagłówek wiersza) woła go bez seniority (drill-down bez filtra).
 */
export function TechMapHeatmap({
  data,
  maxSkills = 40,
  onCellClick,
}: {
  data: CortexTechMap;
  maxSkills?: number;
  onCellClick?: (skillName: string, seniority?: string) => void;
}) {
  const interactive = typeof onCellClick === "function";
  const skills = data.skills.slice(0, maxSkills);
  const matrix: Record<string, Record<string, number>> = {};
  for (const cell of data.cells) {
    matrix[cell.skill] ??= {};
    matrix[cell.skill][cell.seniority] = cell.count;
  }

  // GLOBAL color scale: one max across every cell (not per-row) so a cell's
  // shade is comparable between skills. Intensity maps 0→light, max→dark on the
  // theme `--primary` token (theme-aware, follows the active accent palette).
  const globalMax = Math.max(1, ...data.cells.map((c) => c.count));
  const fillFor = (count: number) =>
    count > 0
      ? `hsl(var(--primary) / ${0.12 + (count / globalMax) * 0.55})`
      : undefined;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <caption className="sr-only">
          Mapa kompetencji: liczba kandydatów wg technologii (wiersze) i poziomu
          doświadczenia / seniority (kolumny). Intensywność koloru komórki
          odpowiada liczbie kandydatów w skali globalnej (jaśniej = mniej,
          ciemniej = więcej). Kolumna Σ to prawdziwa łączna liczba kandydatów
          znających daną technologię.
        </caption>
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="px-2 py-1 sticky left-0 bg-card dark:bg-muted">
              Technologia
            </th>
            {data.seniorities.map((s) => (
              <th key={s} className="px-2 py-1 text-center whitespace-nowrap">
                {SENIORITY_LABELS[s] ?? s}
              </th>
            ))}
            <th className="px-2 py-1 text-center">Σ</th>
          </tr>
        </thead>
        <tbody>
          {skills.map((skill) => {
            const row = matrix[skill] ?? {};
            const rowSum = data.seniorities.reduce(
              (acc, s) => acc + (row[s] ?? 0),
              0
            );
            // TRUE per-skill total (distinct candidates), not filtered by
            // min_count and not the sum of visible cells. Fall back to the
            // visible-cell sum only if the backend omits this skill.
            const skillTotal = data.skill_totals[skill] ?? rowSum;
            return (
              <tr key={skill} className="border-t border-border">
                <th
                  scope="row"
                  className="px-2 py-1 font-medium text-left sticky left-0 bg-card dark:bg-muted whitespace-nowrap"
                >
                  {interactive ? (
                    <button
                      type="button"
                      onClick={() => onCellClick?.(skill)}
                      className="text-left hover:text-primary hover:underline underline-offset-2 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
                      title={`${skill}: pokaż wszystkich (${skillTotal})`}
                    >
                      {skill}
                    </button>
                  ) : (
                    skill
                  )}
                </th>
                {data.seniorities.map((s) => {
                  const cnt = row[s] ?? 0;
                  const seniorityLabel = SENIORITY_LABELS[s] ?? s;
                  const cellInteractive = interactive && cnt > 0;
                  return (
                    <td
                      key={s}
                      tabIndex={0}
                      role={cellInteractive ? "button" : undefined}
                      onClick={
                        cellInteractive
                          ? () => onCellClick?.(skill, s)
                          : undefined
                      }
                      onKeyDown={
                        cellInteractive
                          ? (e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                onCellClick?.(skill, s);
                              }
                            }
                          : undefined
                      }
                      title={
                        cellInteractive
                          ? `${skill} · ${seniorityLabel}: ${cnt} — kliknij, by zobaczyć osoby`
                          : `${skill} · ${seniorityLabel}: ${cnt}`
                      }
                      className={
                        cellInteractive
                          ? "px-2 py-1 text-center tabular-nums cursor-pointer hover:ring-2 hover:ring-inset hover:ring-primary/40 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                          : "px-2 py-1 text-center tabular-nums cursor-default"
                      }
                      style={{ backgroundColor: fillFor(cnt) }}
                    >
                      {cnt || "·"}
                    </td>
                  );
                })}
                <td className="px-2 py-1 text-center font-medium tabular-nums">
                  {skillTotal}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* Global color-scale legend: light → dark = few → many candidates. */}
      <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
        <span>mniej</span>
        <span
          className="h-2.5 w-28 rounded-full border border-border"
          style={{
            backgroundImage:
              "linear-gradient(to right, hsl(var(--primary) / 0.12), hsl(var(--primary) / 0.67))",
          }}
          aria-hidden="true"
        />
        <span>więcej</span>
        <span className="ml-1 tabular-nums">
          (max {globalMax.toLocaleString("pl-PL")} kandydatów / komórkę)
        </span>
      </div>

      {data.skills.length > maxSkills ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Pokazano top {maxSkills} z {data.skills.length} technologii (sort wg
          liczby kandydatów).
        </p>
      ) : null}
    </div>
  );
}
