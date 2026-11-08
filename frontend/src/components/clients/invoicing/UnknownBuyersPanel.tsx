"use client";

import { useState } from "react";

import { ClientSinglePicker, type ClientRef } from "@/components/clients/ClientSinglePicker";
import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAssignUnknownBuyer,
  useSkipUnknownBuyer,
  useUnknownBuyers,
  type UnknownBuyer,
} from "@/lib/api/client-invoicing";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

import { totalsText } from "./invoicing-format";

const invoiceWord = (count: number) => countPl(count, "faktura", "faktury", "faktur");

const numberLabel = (buyer: UnknownBuyer) =>
  buyer.number
    ? `${buyer.kind === "vat_ue" ? "VAT UE" : "NIP"} ${buyer.number}`
    : "bez numeru";

const assignedMessage = (retried: number, matched: number) =>
  `Numer dopisany do klienta. Faktury tego nabywcy (${retried}) są już u tego klienta, z zamówieniem: ${matched}.`;

/** Finanse → „Nieznani nabywcy”: faktury bez klienta po numerze nabywcy, ze wszystkich miesięcy. */
export function UnknownBuyersPanel() {
  const { showToast } = useToast();
  const query = useUnknownBuyers();
  const assign = useAssignUnknownBuyer();
  const [picking, setPicking] = useState<UnknownBuyer | null>(null);
  const [skipping, setSkipping] = useState<UnknownBuyer | null>(null);
  const { askConfirm, confirmDialog } = useConfirmV2();

  const assignTo = (buyer: UnknownBuyer, clientId: number, onDone?: () => void) => {
    if (!buyer.number) return;
    assign.mutate(
      { number: buyer.number, clientId },
      {
        onSuccess: ({ buyer_number: saved }) => {
          showToast(assignedMessage(saved.retried, saved.matched), "success");
          onDone?.();
        },
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się przypisać nabywcy."), "error"),
      },
    );
  };

  const confirmSuggestion = async (buyer: UnknownBuyer) => {
    if (!buyer.suggestion) return;
    const ok = await askConfirm({
      title: `Przypisać do klienta ${buyer.suggestion.client_name}?`,
      description: `${numberLabel(buyer)} trafi do klienta, a ${invoiceWord(buyer.invoices)} tego nabywcy dopasują się od razu.`,
      confirmLabel: "Przypisz",
    });
    if (ok) assignTo(buyer, buyer.suggestion.client_id);
  };

  if (query.isLoading) {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie nabywców…</p>;
  }
  if (query.isError) {
    return <QueryStateNotice state="error" onRetry={() => query.refetch()} />;
  }
  if (query.isSuccess && query.data.buyers.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        Wszyscy nabywcy z KSeF są przypisani do klientów.
      </div>
    );
  }

  const data = query.data;
  if (!data) return null;
  const { summary } = data;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {invoiceWord(summary.invoices)} · {countPl(summary.buyers, "nabywca", "nabywców", "nabywców")} ·{" "}
        {summary.with_suggestion} z podpowiedzią
        {!summary.totals_hidden && summary.totals.length > 0
          ? ` · ${totalsText(summary.totals)} netto`
          : ""}
      </p>
      <div className="rounded-lg border border-border bg-card">
        <Table density="compact" className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className={`${CALM_HEAD} w-[24%]`}>Nabywca</TableHead>
              <TableHead className={`${CALM_HEAD} w-[6%] text-right`}>Faktur</TableHead>
              <TableHead className={`${CALM_HEAD} w-[14%] text-right`}>Netto razem</TableHead>
              <TableHead className={`${CALM_HEAD} w-[17%]`}>Podpowiedź klienta</TableHead>
              <TableHead className={`${CALM_HEAD} w-[11%]`}>Daty</TableHead>
              <TableHead className={`${CALM_HEAD} w-[28%] text-right`}>
                <span className="sr-only">Akcje</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.buyers.map((buyer) => (
              <TableRow
                key={buyer.number ?? "bez-numeru"}
                className={`${CALM_ROW} align-top`}
                data-testid={`unknown-buyer-${buyer.number ?? "none"}`}
              >
                <TableCell className="min-w-0">
                  <span className="block truncate" title={buyer.buyer_name ?? undefined}>
                    {buyer.buyer_name ?? "bez nazwy"}
                  </span>
                  <span className={CALM_SUBLINE}>{numberLabel(buyer)}</span>
                </TableCell>
                <TableCell className={CALM_AMOUNT}>{buyer.invoices}</TableCell>
                <TableCell className={CALM_AMOUNT}>
                  {buyer.totals.map((total) => (
                    <span key={total.currency} className="block">
                      {formatMoney(total.amount, total.currency)}
                    </span>
                  ))}
                </TableCell>
                <TableCell className="min-w-0 text-sm">
                  {buyer.suggestion ? (
                    <>
                      <span className="block truncate">{buyer.suggestion.client_name}</span>
                      {buyer.suggestion.state === "differs" ? (
                        <span className={CALM_SUBLINE}>klient ma już inny numer</span>
                      ) : null}
                    </>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground tabular-nums">
                  {formatIsoDatePl(buyer.first_date)}
                  {buyer.first_date !== buyer.last_date
                    ? `–${formatIsoDatePl(buyer.last_date)}`
                    : ""}
                </TableCell>
                <TableCell className="text-right">
                  {buyer.assignable ? (
                    <div className="flex flex-nowrap justify-end gap-1">
                      {buyer.suggestion?.state === "add" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={assign.isPending}
                          onClick={() => void confirmSuggestion(buyer)}
                        >
                          Przypisz
                        </Button>
                      ) : null}
                      <Button
                        size="sm"
                        variant={buyer.suggestion?.state === "add" ? "ghost" : "outline"}
                        onClick={() => setPicking(buyer)}
                      >
                        Przypisz do…
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setSkipping(buyer)}>
                        Pomiń
                      </Button>
                    </div>
                  ) : (
                    <span className={CALM_SUBLINE}>
                      {buyer.number ? "numer ucięty" : "przypisz w „Faktury z KSeF”"}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {picking ? (
        <PickClientDialog
          key={picking.number}
          buyer={picking}
          pending={assign.isPending}
          onAssign={(clientId) => assignTo(picking, clientId, () => setPicking(null))}
          onClose={() => setPicking(null)}
        />
      ) : null}
      {skipping ? (
        <SkipBuyerDialog key={skipping.number} buyer={skipping} onClose={() => setSkipping(null)} />
      ) : null}
      {confirmDialog}
    </div>
  );
}

function PickClientDialog({
  buyer,
  pending,
  onAssign,
  onClose,
}: {
  buyer: UnknownBuyer;
  pending: boolean;
  onAssign: (clientId: number) => void;
  onClose: () => void;
}) {
  const [client, setClient] = useState<ClientRef | null>(null);
  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`Przypisz nabywcę · ${buyer.buyer_name ?? numberLabel(buyer)}`}
      description={`${numberLabel(buyer)} trafi do wskazanego klienta, a ${invoiceWord(buyer.invoices)} dopasują się od razu.`}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={!client || pending} onClick={() => client && onAssign(client.id)}>
            {pending ? "Zapisywanie…" : "Przypisz"}
          </Button>
        </>
      }
    >
      <ClientSinglePicker value={client} onChange={setClient} queryKey="unknown-buyer-assign-clients" />
    </AppModal>
  );
}

function SkipBuyerDialog({ buyer, onClose }: { buyer: UnknownBuyer; onClose: () => void }) {
  const { showToast } = useToast();
  const skip = useSkipUnknownBuyer();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (!buyer.number) return;
    if (reason.trim().length < 3) {
      setError("Napisz powód (co najmniej 3 znaki).");
      return;
    }
    skip.mutate(
      { number: buyer.number, reason: reason.trim() },
      {
        onSuccess: ({ skipped }) => {
          showToast(`Pominięto: ${invoiceWord(skipped)}`, "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się pominąć faktur.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`Pomiń nabywcę · ${buyer.buyer_name ?? numberLabel(buyer)}`}
      description={`${invoiceWord(buyer.invoices)} zniknie z kolejki. Decyzję można cofnąć w „Faktury z KSeF”, przy każdej fakturze osobno.`}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={skip.isPending}>
            {skip.isPending ? "Zapisywanie…" : "Pomiń"}
          </Button>
        </>
      }
    >
      <FormField label="Powód" htmlFor="unknown-buyer-skip-reason">
        <Textarea
          id="unknown-buyer-skip-reason"
          value={reason}
          maxLength={500}
          rows={3}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Np. sprzedaż sprzętu albo osoba prywatna spoza zamówień."
        />
      </FormField>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
