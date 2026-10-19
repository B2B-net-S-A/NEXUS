"use client";

import type { EquipmentCategory, EquipmentSummary } from "@/lib/api/equipment";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";
import { countPl } from "@/lib/plural-pl";

import { CATEGORY_PLURAL, TILE_CATEGORIES, daysSince } from "./equipment-format";
import { CategoryIcon } from "./equipment-visuals";

interface StockTilesProps {
  summary: EquipmentSummary;
  category: EquipmentCategory | "";
  onCategory: (category: EquipmentCategory | "") => void;
  onOpenProtocols: () => void;
  onOpenImport: () => void;
}

const TILE = "flex min-w-0 flex-col gap-1.5 rounded-lg border bg-card px-3 py-2.5 text-left";

/**
 * Kafle stanu „Ewidencji”: wolne per kategoria z paskiem wydane / wolne / serwis
 * (klik = filtr kategorii, drugi klik zdejmuje), „Czeka na podpis” i „Z importu”.
 */
export function StockTiles({
  summary,
  category,
  onCategory,
  onOpenProtocols,
  onOpenImport,
}: StockTilesProps) {
  const oldest = daysSince(summary.oldest_waiting_on, warsawToday());
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {TILE_CATEGORIES.map((key) => {
          const counts = summary.by_category?.[key];
          const free = summary.free_by_category[key] ?? 0;
          const issued = counts?.wydany ?? 0;
          const service = counts?.serwis ?? 0;
          const total = counts
            ? counts.na_stanie + counts.wydany + counts.serwis
            : null;
          const active = category === key;
          const share = (value: number) => (total ? `${(value / total) * 100}%` : "0%");
          return (
            <button
              key={key}
              type="button"
              aria-pressed={active}
              onClick={() => onCategory(active ? "" : key)}
              className={cn(
                TILE,
                "transition-colors hover:border-primary/40",
                active ? "border-primary/50 bg-primary/5" : "border-border",
              )}
            >
              <span
                className={cn(
                  "flex items-center gap-2 text-sm font-medium",
                  active ? "text-primary" : "text-foreground",
                )}
              >
                <CategoryIcon size="sm" category={key} />
                {CATEGORY_PLURAL[key]}
              </span>
              <span>
                <span className="text-xl font-semibold tabular-nums">{free}</span>{" "}
                <span className="text-xs text-muted-foreground">
                  {total != null ? `wolnych z ${total}` : "wolnych"}
                </span>
              </span>
              {total ? (
                <span
                  className="flex h-1.5 overflow-hidden rounded-full bg-muted"
                  title={`wydane ${issued} · wolne ${free} · w serwisie ${service}`}
                  aria-label={`wydane ${issued}, wolne ${free}, w serwisie ${service}`}
                  role="img"
                >
                  <span className="bg-primary" style={{ width: share(issued) }} />
                  <span className="bg-success" style={{ width: share(counts?.na_stanie ?? 0) }} />
                  <span className="bg-warning" style={{ width: share(service) }} />
                </span>
              ) : null}
            </button>
          );
        })}
        <section
          aria-label="Czeka na podpis"
          className={cn(
            TILE,
            summary.protocols_waiting > 0
              ? "border-warning/40 bg-warning-muted/40"
              : "border-border",
          )}
        >
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Czeka na podpis
          </span>
          <span>
            <span className="text-xl font-semibold tabular-nums">{summary.protocols_waiting}</span>{" "}
            <span className="text-xs text-muted-foreground">
              {summary.protocols_waiting > 0 && oldest != null
                ? `najstarszy ${countPl(oldest, "dzień", "dni", "dni")}`
                : "protokołów"}
            </span>
          </span>
          <button
            type="button"
            onClick={onOpenProtocols}
            className="self-start text-xs font-medium text-primary hover:underline"
          >
            Pokaż protokoły →
          </button>
        </section>
        <section aria-label="Z importu" className={cn(TILE, "border-border")}>
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Z importu
          </span>
          <span>
            <span className="text-xl font-semibold tabular-nums">{summary.import_unresolved}</span>{" "}
            <span className="text-xs text-muted-foreground">do wyjaśnienia</span>
          </span>
          <button
            type="button"
            onClick={onOpenImport}
            className="self-start text-xs font-medium text-primary hover:underline"
          >
            Wyjaśnij →
          </button>
        </section>
      </div>
      {/* Legenda paska — na niskim laptopie dopiero od 2xl (podpowiedź jest na pasku). */}
      <p className="hidden gap-4 text-xs text-muted-foreground 2xl:flex">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-primary" aria-hidden />
          wydane
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-success" aria-hidden />
          wolne
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-warning" aria-hidden />
          w serwisie
        </span>
      </p>
    </div>
  );
}
