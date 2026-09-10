import type { OrderExtractionResult } from "@/lib/api/dlPortal";

export type ExtractedConsultantRows = NonNullable<OrderExtractionResult["consultant_rows"]>;

const UNIT_LABEL: Record<string, string> = { hour: "zł/h", day: "zł/MD", month: "zł/mc" };

export function ExtractedConsultants({
  rows,
  openEnded = false,
}: {
  rows: ExtractedConsultantRows;
  /** Reguła klienta mówi „bezterminowo" (BIK) — brak daty końca to nie brak odczytu. */
  openEnded?: boolean;
}) {
  if (!rows.length) return null;
  return (
    <div className="rounded-lg border border-border p-3 text-sm">
      <p className="mb-2 font-medium">Konsultanci odczytani z PDF</p>
      <ul className="space-y-2">
        {rows.map((row, i) => (
          <li key={`${row.consultant_name}-${i}`}>
            {row.consultant_name ? (
              <span className="font-medium">{row.consultant_name}</span>
            ) : (
              <span className="font-medium text-destructive">Nie odczytano imienia i nazwiska</span>
            )}
            {row.md_total != null && (
              <span> · limit {Number(row.md_total).toLocaleString("pl-PL")} MD</span>
            )}
            {row.rate_client != null && (
              <span>
                {" "}
                · {Number(row.rate_client).toLocaleString("pl-PL")}{" "}
                {UNIT_LABEL[row.rate_unit ?? ""] ?? "zł/h"}
              </span>
            )}
            <span className="block text-xs text-muted-foreground">
              {row.start_date ?? "—"} – {row.end_date ?? (openEnded ? "bezterminowo" : "—")}
            </span>
            {row.uncertain_reason ? (
              <span className="block text-xs text-destructive">{row.uncertain_reason}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
