"use client";

// Finanse → Rozliczenia → „Do faktury dla klienta” (roadmapa E5.1, E5.2):
// pozycje jak dziś w KSeF do skopiowania, marża i paczka RCP. NEXUS nie
// wystawia faktury; wystawiona wraca z KSeF i zmienia stan na „Wystawiona”.
import { Copy, Download } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import {
  fetchAttachmentsZip,
  useClientInvoiceMonth,
  type ClientInvoicePosition,
  type ClientInvoiceRow,
} from "@/lib/api/client-settlements";

import { CLIENT_INVOICE, mdText, monthLabel, pctText, pln } from "./format";

function plain(value: string | null): string {
  return value == null ? "" : value.replace(".", ",");
}

/** Pozycje do wklejenia w program do faktur: kolumny rozdzielone tabulatorem. */
export function positionsText(rows: ClientInvoiceRow[]): string {
  return rows
    .filter((r) => r.state === "ready")
    .flatMap((r) => r.positions)
    .map((p) => [p.name, plain(p.quantity), p.unit, plain(p.unit_price), plain(p.net)].join("\t"))
    .join("\n");
}

function PositionLine({ p }: { p: ClientInvoicePosition }) {
  return (
    <li className="break-words font-mono text-[11.5px] leading-[17px]">
      {p.name} · {mdText(p.quantity)} {p.unit}
      {p.unit_price != null ? ` × ${pln(p.unit_price)} = ${pln(p.net)}` : ""}
    </li>
  );
}

export function ClientInvoiceView({ clientId, month }: { clientId: number; month: string }) {
  const query = useClientInvoiceMonth(clientId, month);
  const { showSuccess, showError } = useToast();

  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać pozycji faktury do klienta.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const data = query.data;
  const rows = data.rows.filter((r) => r.kind != null);
  const ready = rows.filter((r) => r.state === "ready");
  const waiting = data.rows.length - rows.length;

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(positionsText(rows));
      showSuccess(`Skopiowano pozycje ${ready.length} osób.`);
    } catch {
      showError("Nie udało się skopiować pozycji. Zaznacz je ręcznie.");
    }
  }

  async function onZip(row?: ClientInvoiceRow) {
    try {
      const blob = await fetchAttachmentsZip(
        clientId,
        month,
        row ? { contractId: row.contract_id } : { issuedOnly: true },
      );
      const name = row ? `rcp-${row.ksef_number ?? row.order_number ?? row.contract_id}-${month}.zip` : `rcp-wystawione-${month}.zip`;
      downloadBlob(blob, name);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać plików RCP."));
    }
  }
  const issued = rows.filter((r) => r.state === "issued").length;

  return (
    <div className="space-y-3">
      <section className="rounded-xl border border-primary/25 bg-primary/[0.04] p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">
              Faktura do {data.client_name} za {monthLabel(month)}
            </h2>
            <p className="max-w-[70ch] text-xs text-muted-foreground">
              {ready.length} do wystawienia, {rows.length - ready.length} wystawione, {waiting} czeka na przyjęcie RCP. Pozycje mają
              nazwy z ostatniej faktury za to zamówienie; wklej je do programu do faktur. Wystawiona faktura wróci z KSeF sama, a jej RCP
              dostaje nazwę z numeru KSeF.
            </p>
          </div>
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" disabled={ready.length === 0} onClick={onCopy}>
              <Copy aria-hidden className="size-3.5" /> Kopiuj pozycje
            </Button>
            <Button size="sm" variant="outline" disabled={issued === 0} onClick={() => onZip()}>
              <Download aria-hidden className="size-3.5" /> Pobierz RCP wystawionych ({issued})
            </Button>
          </div>
        </div>
      </section>
      {rows.length === 0 ? (
        <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
          W tym miesiącu nie ma jeszcze przyjętego RCP.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <table className="w-full min-w-[880px] table-fixed text-[13px]">
            <colgroup>
              <col className="w-[18%]" />
              <col className="w-[14%]" />
              <col />
              {data.can_see_amounts ? <col className="w-[11%]" /> : null}
              {data.can_see_amounts ? <col className="w-[10%]" /> : null}
            </colgroup>
            <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 font-medium">Osoba</th>
                <th className="px-2 py-1.5 font-medium">Faktura</th>
                <th className="px-2 py-1.5 font-medium">Pozycje</th>
                {data.can_see_amounts ? <th className="px-2 py-1.5 text-right font-medium">Netto</th> : null}
                {data.can_see_amounts ? <th className="px-3 py-1.5 text-right font-medium">Marża</th> : null}
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => (
                <tr key={r.contract_id} className="align-top">
                  <td className="px-3 py-1.5">
                    <span className="block truncate font-medium">{r.person}</span>
                    <span className="block truncate text-[11px] text-muted-foreground">
                      {[r.order_number, r.kind === "estimate" ? "z planu" : null].filter(Boolean).join(" · ")}
                    </span>
                  </td>
                  <td className="px-2 py-1.5">
                    <StatusDot tone={CLIENT_INVOICE[r.state].tone}>{CLIENT_INVOICE[r.state].label}</StatusDot>
                    {r.invoice_number ? <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">{r.invoice_number}</span> : null}
                    <button
                      type="button"
                      onClick={() => onZip(r)}
                      className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
                      aria-label={`Pobierz RCP: ${r.person}`}
                    >
                      <Download aria-hidden className="size-3" /> RCP
                    </button>
                  </td>
                  <td className="px-2 py-1.5">
                    <ul className="grid gap-0.5">
                      {r.positions.map((p) => (
                        <PositionLine key={`${p.kind}-${p.name}`} p={p} />
                      ))}
                    </ul>
                    {!r.template ? (
                      <p className="mt-0.5 text-[11px] text-warning-muted-foreground">Bez poprzedniej faktury: nazwa zastępcza, sprawdź opis.</p>
                    ) : null}
                  </td>
                  {data.can_see_amounts ? <td className="px-2 py-1.5 text-right tabular-nums">{pln(r.net)}</td> : null}
                  {data.can_see_amounts ? (
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {pln(r.margin)}
                      <span className="block text-[11px] text-muted-foreground">{pctText(r.margin_pct)}</span>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
