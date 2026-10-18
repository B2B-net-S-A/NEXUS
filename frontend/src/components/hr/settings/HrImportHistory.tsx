"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  HR_IMPORT_STATUS_LABELS,
  useHrImportBatches,
  type HrImportAction,
  type HrImportStatus,
  type HrImportUpload,
} from "@/lib/api/hr-import";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDateTimePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

const TONES: Record<HrImportStatus, StatusDotTone> = {
  dry_run: "info",
  applied: "success",
  expired: "neutral",
  superseded: "neutral",
};

function total(upload: HrImportUpload, action: HrImportAction): number {
  return upload.modules.reduce((sum, module) => sum + (module.counts[action] ?? 0), 0);
}

/** Historia partii importu: kto, kiedy, stan, SHA-256 i liczby na sucho. */
export function HrImportHistory() {
  const batches = useHrImportBatches();
  const rows = batches.data ?? [];
  const state = resolveViewState({
    isLoading: batches.isLoading,
    error: batches.error,
    isSuccess: batches.isSuccess,
    isEmpty: rows.length === 0,
  });

  return (
    <Card className="space-y-3 p-5">
      <h2 className="text-base font-semibold text-foreground">Historia partii</h2>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => batches.refetch()} />
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">Nie było jeszcze żadnego importu.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <Table density="compact">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Sprawdzona</TableHead>
                <TableHead className={CALM_HEAD}>Stan</TableHead>
                <TableHead className={CALM_HEAD}>SHA-256</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Nowe</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Zmienione</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Do wyjaśnienia</TableHead>
                <TableHead className={CALM_HEAD}>Zapis</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((upload) => (
                <TableRow key={upload.id} className={CALM_ROW}>
                  <TableCell className="whitespace-nowrap">
                    {formatDateTimePl(upload.created_at)}
                    <span className={CALM_SUBLINE}>
                      #{upload.id} · {upload.created_by_name ?? "—"}
                    </span>
                  </TableCell>
                  <TableCell>
                    <StatusDot tone={TONES[upload.status]}>
                      {HR_IMPORT_STATUS_LABELS[upload.status]}
                    </StatusDot>
                  </TableCell>
                  <TableCell className="font-mono text-xs" title={upload.bundle_sha256}>
                    {upload.bundle_sha256.slice(0, 12)}…
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>{total(upload, "create")}</TableCell>
                  <TableCell className={CALM_AMOUNT}>{total(upload, "update")}</TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {total(upload, "skip") + total(upload, "conflict")}
                  </TableCell>
                  <TableCell>
                    {upload.applied_at ? (
                      <>
                        {formatDateTimePl(upload.applied_at)}
                        <span className={CALM_SUBLINE}>
                          {upload.applied_by_name ?? "—"} ·{" "}
                          {upload.modules
                            .filter((m) => upload.applied_modules.includes(m.module))
                            .map((m) => m.label)
                            .join(", ")}
                        </span>
                      </>
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </Card>
  );
}
