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
 */
export function TechMapHeatmap({
  data,
  maxSkills = 40,
}: {
  data: CortexTechMap;
  maxSkills?: number;
}) {
  const skills = data.skills.slice(0, maxSkills);
  const matrix: Record<string, Record<string, number>> = {};
  for (const cell of data.cells) {
    matrix[cell.skill] ??= {};
    matrix[cell.skill][cell.seniority] = cell.count;
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
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
            const rowMax = Math.max(
              1,
              ...data.seniorities.map((s) => row[s] ?? 0)
            );
            return (
              <tr key={skill} className="border-t border-border">
                <td className="px-2 py-1 font-medium sticky left-0 bg-card dark:bg-muted whitespace-nowrap">
                  {skill}
                </td>
                {data.seniorities.map((s) => {
                  const cnt = row[s] ?? 0;
                  const intensity = cnt / rowMax;
                  return (
                    <td
                      key={s}
                      className="px-2 py-1 text-center tabular-nums"
                      style={{
                        backgroundColor:
                          cnt > 0
                            ? `rgba(37, 99, 235, ${0.1 + intensity * 0.4})`
                            : undefined,
                      }}
                    >
                      {cnt || "·"}
                    </td>
                  );
                })}
                <td className="px-2 py-1 text-center font-medium tabular-nums">
                  {rowSum}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {data.skills.length > maxSkills ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Pokazano top {maxSkills} z {data.skills.length} technologii (sort wg
          liczby kandydatów).
        </p>
      ) : null}
    </div>
  );
}
