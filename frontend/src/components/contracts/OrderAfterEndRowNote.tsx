"use client";
// Notka pod nazwiskiem na liście kontraktów: klient zamówił okres po końcu
// współpracy (decyzja Artura 19.11.2026). Konflikt liczy serwer
// (`order_after_end` w wierszu, `services/contract_order_after_end.py`).

export interface OrderAfterEndSummary {
  contract_id: number;
  order_id: number;
  status: string;
  start_date: string | null;
  end_date: string | null;
  count: number;
}

function datePl(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

/** Krótko, bo kolumna osoby ma przy 1280 px ok. 110 px: „po końcu · 01.12”. */
export function orderAfterEndNoteText(summary: OrderAfterEndSummary): string {
  const start = summary.start_date ? ` · ${datePl(summary.start_date).slice(0, 5)}` : "";
  const text = `po końcu${start}`;
  return summary.count > 1 ? `${text} (+${summary.count - 1})` : text;
}

/** Pełne zdanie w podpowiedzi. */
export function orderAfterEndNoteTitle(summary: OrderAfterEndSummary): string {
  const what = summary.status === "draft" ? "szkic zamówienia" : "zamówienie";
  const period = summary.start_date
    ? summary.end_date
      ? `${datePl(summary.start_date)} – ${datePl(summary.end_date)}`
      : `od ${datePl(summary.start_date)} bez daty końca`
    : "bez dat";
  const more = summary.count > 1 ? ` (i ${summary.count - 1} kolejne)` : "";
  return `Klient zamówił okres po zakończeniu współpracy: ${what} ${period}${more}. Decyzja na karcie kontraktu.`;
}

export function OrderAfterEndRowNote({ summary }: { summary?: OrderAfterEndSummary | null }) {
  if (!summary) return null;
  return (
    <span
      data-testid="order-after-end-row-note"
      title={orderAfterEndNoteTitle(summary)}
      className="mt-0.5 inline-block max-w-full truncate rounded border border-destructive/40 bg-destructive/10 px-1.5 text-[11px] font-medium leading-4 text-destructive"
    >
      {orderAfterEndNoteText(summary)}
    </span>
  );
}
