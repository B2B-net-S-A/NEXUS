"use client";

/**
 * „Kto ilu dodał” — tabela w okienku „Zespół rekrutacji” (decyzja Artura
 * z 16.11.2026, wariant C). Liczby: `lib/board-added-summary.ts`; zasady:
 * docs/claude/rekrutacja-tablica/kto-ilu-dodal-w-zespole-rekrutacji.md
 */
import { Bot } from "lucide-react";

import type { AddedSummary } from "@/lib/board-added-summary";
import { cn } from "@/lib/utils";
import { RecruiterAvatar } from "./RecruiterChips";

function shortName(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : name;
}

function cell(value: number): string {
  return value > 0 ? String(value) : "—";
}

export interface AddedToJobTableProps {
  summary: AddedSummary;
  viewerId: number | null;
}

export function AddedToJobTable({ summary, viewerId }: AddedToJobTableProps) {
  const { rows, total, byPeople } = summary;
  return (
    <section className="space-y-1.5 border-t border-border pt-2" data-testid="added-to-job-table">
      <p className="text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground">
        Kto ilu dodał
      </p>
      <p className="text-xs text-muted-foreground">
        Od otwarcia rekrutacji, także odrzuceni: razem{" "}
        <span className="font-semibold tabular-nums text-foreground">{total}</span>, ludzie{" "}
        <span className="font-semibold tabular-nums text-foreground">{byPeople}</span>.
      </p>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">Nikt jeszcze nikogo nie dodał.</p>
      ) : (
        <table className="w-full text-xs tabular-nums">
          <thead>
            <tr className="whitespace-nowrap text-left text-[11px] text-muted-foreground">
              <th className="py-1 pr-2 font-medium">Osoba</th>
              <th className="px-1 text-right font-medium" title="Dodał do tej rekrutacji od otwarcia">
                Dodał
              </th>
              <th className="px-1 text-right font-medium" title="Dziś i sześć poprzednich dni">
                7 dni
              </th>
              <th className="px-1 text-right font-medium" title="Nadal w toku na Tablicy">
                W toku
              </th>
              <th className="px-1 text-right font-medium" title="W toku od „Przygotowania CV” w prawo">
                Zweryf.+
              </th>
              <th className="pl-1 text-right font-medium" title="W toku od „CV wysłane” w prawo">
                U klienta
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.key}
                className={cn("border-t border-border", row.kind !== "user" && "text-muted-foreground")}
                data-testid={`added-to-job-row-${row.key}`}
              >
                <td className="max-w-[140px] py-1 pr-2">
                  <span className="flex min-w-0 items-center gap-1.5">
                    {row.kind === "user" ? (
                      <RecruiterAvatar name={row.name} className="h-5 w-5 shrink-0" />
                    ) : (
                      <Bot className="h-4 w-4 shrink-0" aria-hidden="true" />
                    )}
                    <span className="truncate" title={row.name}>
                      {row.kind !== "user"
                        ? row.name
                        : row.userId === viewerId
                          ? "Ty"
                          : shortName(row.name)}
                    </span>
                  </span>
                </td>
                <td
                  className={cn(
                    "px-1 text-right font-semibold",
                    row.added === 0 && "text-warning-muted-foreground",
                  )}
                >
                  {row.added}
                </td>
                <td className="px-1 text-right">{cell(row.last7)}</td>
                <td className="px-1 text-right">{cell(row.inProgress)}</td>
                <td className="px-1 text-right">{cell(row.pastScreening)}</td>
                <td className="pl-1 text-right">{cell(row.atClient)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
