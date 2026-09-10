import type { OrderExtractionResult } from "@/lib/api/dlPortal";

export type ExtractedConsultantRows = NonNullable<OrderExtractionResult["consultant_rows"]>;

export function ExtractedConsultants({ rows }: { rows: ExtractedConsultantRows }) {
  if (!rows.length) return null;
  return (
    <div className="rounded-lg border border-border p-3 text-sm">
      <p className="mb-2 font-medium">Konsultanci odczytani z PDF</p>
      <ul className="space-y-2">
        {rows.map((row, i) => (
          <li key={`${row.consultant_name}-${i}`}>
            <span className="font-medium">{row.consultant_name}</span>
            {row.rate_client != null && <span> · {Number(row.rate_client).toLocaleString("pl-PL")} zł/h</span>}
            <span className="block text-xs text-muted-foreground">{row.start_date ?? "—"} – {row.end_date ?? "—"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
