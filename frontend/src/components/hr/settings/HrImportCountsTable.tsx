"use client";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  HR_IMPORT_ACTION_LABELS,
  type HrImportAction,
  type HrImportModule,
  type HrImportModuleReport,
} from "@/lib/api/hr-import";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";

const ACTIONS: HrImportAction[] = ["create", "update", "unchanged", "conflict", "skip"];

function Count({ value }: { value: number }) {
  return value === 0 ? <span className={CALM_EMPTY}>0</span> : <>{value}</>;
}

/**
 * Liczby per moduł: na sucho (`dry_run`) albo plan przeliczony przy zapisie
 * (`applied`). Z `onToggle` pierwsza kolumna wybiera moduły do zapisu.
 */
export function HrImportCountsTable({
  modules,
  source,
  selected,
  onToggle,
}: {
  modules: HrImportModuleReport[];
  source: "dry_run" | "applied";
  selected?: HrImportModule[];
  onToggle?: (module: HrImportModule, next: boolean) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact">
        <TableHeader>
          <TableRow>
            {onToggle ? <TableHead className={`${CALM_HEAD} w-10`}>Zapis</TableHead> : null}
            <TableHead className={CALM_HEAD}>Moduł</TableHead>
            {ACTIONS.map((action) => (
              <TableHead key={action} className={`${CALM_HEAD} text-right`}>
                {HR_IMPORT_ACTION_LABELS[action]}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {modules.map((module) => {
            const counts =
              source === "applied" && module.applied ? module.applied.counts : module.counts;
            return (
              <TableRow key={module.module} className={CALM_ROW}>
                {onToggle ? (
                  <TableCell>
                    <Checkbox
                      aria-label={`Zapisz: ${module.label}`}
                      checked={selected?.includes(module.module) ?? false}
                      disabled={module.error !== null}
                      onCheckedChange={(next) => onToggle(module.module, next === true)}
                    />
                  </TableCell>
                ) : null}
                <TableCell>
                  {module.label}
                  {module.error ? (
                    <span className={`${CALM_SUBLINE} text-destructive`}>{module.error}</span>
                  ) : null}
                </TableCell>
                {ACTIONS.map((action) => (
                  <TableCell key={action} className={CALM_AMOUNT}>
                    <Count value={counts[action] ?? 0} />
                  </TableCell>
                ))}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
