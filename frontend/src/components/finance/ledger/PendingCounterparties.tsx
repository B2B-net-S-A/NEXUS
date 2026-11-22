"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  PENDING_FILE_PATH,
  usePendingCounterparties,
  type PendingCounterparty,
} from "@/lib/api/finance-ledger";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";

function address(row: PendingCounterparty): string {
  return (
    [row.street, [row.postal_code, row.city].filter(Boolean).join(" ")]
      .filter(Boolean)
      .join(", ") || ""
  );
}

/**
 * Finanse → Kontrahenci → „Czeka na Symfonię”: kto jest na fakturach, a nie ma
 * ID Symfonii. Księgowa zakłada ich w Symfonii FK, wpisuje ID w pobranym pliku
 * i odsyła go przyciskiem „Wgraj plik” (ten sam import co z eBI24).
 */
export function PendingCounterparties({ canWrite }: { canWrite: boolean }) {
  const pending = usePendingCounterparties();
  const { showToast } = useToast();
  const [downloading, setDownloading] = useState(false);
  const data = pending.data;

  const download = async () => {
    setDownloading(true);
    try {
      const file = await fetchAuthenticatedDownload(PENDING_FILE_PATH);
      downloadBlob(file.blob, file.filename ?? "kontrahenci-do-symfonii.csv");
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
    } finally {
      setDownloading(false);
    }
  };

  if (pending.isLoading) {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie listy…</p>;
  }
  if (pending.isError) {
    return <QueryStateNotice state="error" onRetry={() => pending.refetch()} />;
  }
  if (!data || data.total === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        Nikt nie czeka na założenie w Symfonii. Każdy kontrahent z faktur ma już ID Symfonii.
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {data.registered === 0 ? (
        <section className="rounded-lg border border-warning/25 bg-warning-muted px-3.5 py-2 text-sm text-warning-muted-foreground">
          Kartoteka nie ma jeszcze żadnego ID Symfonii. Zanim zaczniesz, wgraj plik
          „Partnerzy → Pobierz” z eBI24 (zakładka „Kartoteka”) — inaczej na liście są też
          kontrahenci, którzy już istnieją w Symfonii.
        </section>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm">
        <p className="min-w-0 flex-1">
          <b>{countPl(data.ready, "kontrahent", "kontrahentów", "kontrahentów")}</b> do założenia w
          Symfonii
          {data.without_address > 0 ? ` (bez adresu: ${data.without_address})` : ""}
          {data.with_problems > 0 ? (
            <>
              ,{" "}
              <b className="text-destructive">
                {data.with_problems} do poprawy — nie ma ich w pliku
              </b>
            </>
          ) : null}
          . Księgowa zakłada ich w Symfonii, wpisuje „ID Symfonii” w pliku i odsyła go
          przyciskiem „Wgraj plik”.
        </p>
        <Button
          size="sm"
          onClick={download}
          loading={downloading}
          disabled={data.ready === 0}
          className={canWrite ? undefined : "hidden"}
        >
          Pobierz plik dla księgowej
        </Button>
      </div>
      <div className="rounded-lg border border-border bg-card">
        <Table density="compact" className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className={`${CALM_HEAD} w-[28%]`}>Nazwa</TableHead>
              <TableHead className={`${CALM_HEAD} w-[15%]`}>Identyfikator</TableHead>
              <TableHead className={`${CALM_HEAD} w-[27%]`}>Adres</TableHead>
              <TableHead className={`${CALM_HEAD} w-[14%]`}>Konta po założeniu</TableHead>
              <TableHead className={`${CALM_HEAD} w-[16%]`}>Skąd</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((row) => (
              <TableRow key={row.key} className={`${CALM_ROW} align-top`}>
                <TableCell className="min-w-0">
                  <span className="block truncate">{row.name}</span>
                  {row.problems.length > 0 ? (
                    <span className="block truncate text-xs text-destructive">
                      {row.problems.join("; ")}
                    </span>
                  ) : null}
                </TableCell>
                <TableCell className="min-w-0">
                  {row.id_value ? (
                    <span className="font-mono text-[12.5px]">{row.id_value}</span>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                  <span className={CALM_SUBLINE}>{row.id_type_label ?? "bez numeru"}</span>
                </TableCell>
                <TableCell className="min-w-0">
                  {address(row) ? (
                    <span className="block truncate">{address(row)}</span>
                  ) : (
                    <Badge size="sm" variant="warning">
                      brak adresu
                    </Badge>
                  )}
                  <span className={CALM_SUBLINE}>{row.country ?? "—"}</span>
                </TableCell>
                <TableCell className="min-w-0 font-mono text-[12.5px]">
                  <span className="block">{row.receivable_prefix}-…</span>
                  <span className="block">{row.payable_prefix}-…</span>
                </TableCell>
                <TableCell className="min-w-0">
                  <span className="flex flex-wrap gap-1">
                    {row.sources.map((source) => (
                      <Badge key={source} size="sm" variant="neutral">
                        {source}
                      </Badge>
                    ))}
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
