"use client";

import { useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { HeatCell, HeatRow, MapDepartment } from "@/lib/api/care";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { cellLetters, cellTitle, heatLevel } from "./care-format";
import { candidatesHref } from "./tech-gaps";

/** Wierszy widocznych od razu; reszta pod „Pokaż wszystkie”. */
export const HEATMAP_VISIBLE = 12;

const LEVEL_CLASS = [
  "bg-muted/40",
  "bg-primary/10 text-foreground",
  "bg-primary/30 text-foreground",
  "bg-primary/70 text-primary-foreground",
] as const;

function Cell({ cell, title }: { cell: HeatCell | null; title: string }) {
  const level = heatLevel(cell);
  const letters = cellLetters(cell);
  return (
    <td className="p-0.5">
      <div
        title={title}
        className={cn(
          "flex h-8 items-center justify-center gap-1 rounded-md text-[11px] font-semibold tracking-wide",
          LEVEL_CLASS[level],
          cell?.open_jobs ? "ring-2 ring-inset ring-warning" : null,
        )}
      >
        {letters.map((letter) => (
          <span key={letter} aria-hidden>
            {letter}
          </span>
        ))}
        <span className="sr-only">{title}</span>
      </div>
    </td>
  );
}

function DepartmentHead({ dept }: { dept: MapDepartment }) {
  const manager = dept.managers[0];
  const href = candidatesHref(dept.base.skills);
  return (
    <th
      scope="col"
      className={cn(
        "rounded-md px-2 py-1.5 text-left align-top font-normal",
        dept.has_fresh_source ? "bg-muted/50" : "bg-warning-muted",
      )}
    >
      <span className="block text-[13px] font-semibold">{dept.area.name}</span>
      {!dept.has_fresh_source ? (
        <span className="block text-[11.5px] text-warning-muted-foreground">
          brak źródła 18 mies.
        </span>
      ) : null}
      <span className="block truncate text-[11.5px] text-muted-foreground" title={manager?.position ?? undefined}>
        {manager ? manager.name : "menedżer: —"}
        {dept.managers.length > 1 ? ` +${dept.managers.length - 1}` : ""}
      </span>
      <span className="flex flex-wrap justify-between gap-x-2 text-[11.5px]">
        <span className="whitespace-nowrap">nasi {dept.consultants}</span>
        {href && dept.base.count != null ? (
          <Link
            href={href}
            className="whitespace-nowrap text-primary hover:underline"
            title={`Osoby w bazie z: ${dept.base.skills.join(" i ")}`}
          >
            w bazie {dept.base.count}
          </Link>
        ) : (
          <span className="whitespace-nowrap text-muted-foreground">w bazie —</span>
        )}
      </span>
    </th>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
      <span>siła sygnału:</span>
      <span className="inline-flex gap-0.5" aria-hidden>
        {[1, 2, 3].map((level) => (
          <span key={level} className={cn("h-3 w-4 rounded-sm", LEVEL_CLASS[level])} />
        ))}
      </span>
      <span>1 · 2 · 3+ źródła</span>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-3.5 rounded-sm ring-2 ring-inset ring-warning" />
        otwarta rekrutacja
      </span>
    </div>
  );
}

interface TechHeatmapProps {
  departments: MapDepartment[];
  rows: HeatRow[];
  rowsTotal: number;
}

/**
 * Mapa cieplna technologia × dział (makieta „Klient · Technologie”,
 * 19.10.2026). Siła koloru = liczba rodzajów źródeł (T · R · K · N) w dziale,
 * obramowanie = otwarta rekrutacja działu z tą technologią. Dane w całości
 * z serwera (`heatmap` mapy) — ekran nic nie przelicza.
 */
export function TechHeatmap({ departments, rows, rowsTotal }: TechHeatmapProps) {
  const [all, setAll] = useState(false);
  const visible = all ? rows : rows.slice(0, HEATMAP_VISIBLE);
  const unassigned = rows.some((row) => row.unassigned);
  const hidden = rowsTotal - rows.length;
  return (
    <section className="space-y-2.5 rounded-lg border border-border bg-card p-4" aria-labelledby="care-heatmap">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="care-heatmap" className="text-sm font-semibold">
          Mapa technologii · dział × technologia
        </h3>
        <Legend />
      </div>
      <div className="relative overflow-x-auto">
        <table
          className="w-full table-fixed border-separate border-spacing-0.5 text-sm"
          style={{ minWidth: 300 + departments.length * 110 }}
          aria-label="Technologie klienta po działach"
        >
          <thead>
            <tr>
              <th scope="col" className="w-40 text-left">
                <span className="sr-only">Technologia</span>
              </th>
              {departments.map((dept) => (
                <DepartmentHead key={dept.area.id} dept={dept} />
              ))}
              {unassigned ? (
                <th scope="col" className="w-20 px-2 pb-1.5 text-left align-bottom text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  bez działu
                </th>
              ) : null}
              <th scope="col" className="w-12 px-1 pb-1.5 text-right align-bottom text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                nasi
              </th>
              <th scope="col" className="w-16 px-1 pb-1.5 text-right align-bottom text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                ostatnio
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.skill_id} className={cn(row.stale && "opacity-60")}>
                <th scope="row" className="px-1 py-0.5 text-left font-normal">
                  <span className="block font-semibold leading-tight">{row.name}</span>
                  {row.must_jobs ? (
                    <span className="block text-[11.5px] text-muted-foreground">
                      „musi” w {row.must_jobs} rekrut.
                    </span>
                  ) : null}
                </th>
                {row.cells.map((cell, index) => (
                  <Cell
                    key={departments[index]?.area.id ?? index}
                    cell={cell}
                    title={cellTitle(departments[index]?.area.name ?? "Dział", row.name, cell)}
                  />
                ))}
                {unassigned ? (
                  <Cell cell={row.unassigned} title={cellTitle("Bez działu", row.name, row.unassigned)} />
                ) : null}
                <td className="px-1 text-right font-semibold tabular-nums">
                  {row.consultants || <span className="font-normal text-muted-foreground">—</span>}
                </td>
                <td className="px-1 text-right text-xs tabular-nums text-muted-foreground">
                  {row.last_seen ? formatDayMonthPl(row.last_seen) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          T — rozmowy (karty technologiczne) · R — rekrutacje klienta z 12 miesięcy · K — nasi
          konsultanci u klienta · N — notatki o stacku. Najechanie na komórkę pokazuje źródła;
          wyszarzone — brak źródła z 18 miesięcy.
          {hidden > 0 ? ` Pokazujemy ${rows.length} najmocniejszych z ${rowsTotal}.` : ""}
        </p>
        {rows.length > HEATMAP_VISIBLE ? (
          <Button size="sm" variant="ghost" onClick={() => setAll((v) => !v)}>
            {all ? "Pokaż mniej" : `Pokaż wszystkie (${rows.length})`}
          </Button>
        ) : null}
      </div>
    </section>
  );
}
