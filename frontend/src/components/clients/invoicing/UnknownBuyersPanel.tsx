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
  useExtraBuyerNumbers,
  useRemoveExtraBuyerNumber,
  useSkipUnknownBuyer,
  useUnknownBuyers,
  type ExtraBuyerNumber,
  type UnknownBuyer,
} from "@/lib/api/client-invoicing";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

import { BUYER_NUMBER_LABELS, totalsText } from "./invoicing-format";

const invoiceWord = (count: number) => countPl(count, "faktura", "faktury", "faktur");

const numberLabel = (buyer: UnknownBuyer) =>
  buyer.number
    ? `${BUYER_NUMBER_LABELS[buyer.kind ?? "nip"]} ${buyer.number}`
    : "bez numeru";

const assignedMessage = (retried: number, matched: number, extra = false) =>
  `${extra ? "Dodatkowy numer" : "Numer"} dopisany do klienta. Faktury tego nabywcy (${retried}) są już u tego klienta, z zamówieniem: ${matched}.`;

/** Finanse → „Nieznani nabywcy”: faktury bez klienta po numerze nabywcy, ze wszystkich miesięcy. */
export function UnknownBuyersPanel() {
  const { showToast } = useToast();
  const query = useUnknownBuyers();
  const assign = useAssignUnknownBuyer();
  const [picking, setPicking] = useState<UnknownBuyer | null>(null);
  const [skipping, setSkipping] = useState<UnknownBuyer | null>(null);
  const { askConfirm, confirmDialog } = useConfirmV2();

  const assignTo = (buyer: UnknownBuyer, clientId: number, onDone?: () => void, extra = false) => {
    if (!buyer.number) return;
    assign.mutate(
      { number: buyer.number, clientId, extra },
      {
        onSuccess: ({ buyer_number: saved }) => {
          showToast(assignedMessage(saved.retried, saved.matched, saved.extra), "success");
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

  // Spółka grupy klienta (oddział, spółka leasingowa): klient ma już inny numer.
  const confirmExtra = async (buyer: UnknownBuyer) => {
    if (!buyer.suggestion) return;
    const ok = await askConfirm({
      title: `Dopisać jako dodatkowy numer klienta ${buyer.suggestion.client_name}?`,
      description: `Klient ma już inny numer. ${numberLabel(buyer)} zostanie dopisany obok niego jako numer spółki z grupy klienta, a ${invoiceWord(buyer.invoices)} tego nabywcy dopasują się od razu. Numer można usunąć z listy „Dodatkowe numery klientów”.`,
      confirmLabel: "Dopisz jako dodatkowy",
    });
    if (ok) assignTo(buyer, buyer.suggestion.client_id, undefined, true);
  };

  if (query.isLoading) {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie nabywców…</p>;
  }
  if (query.isError) {
    return <QueryStateNotice state="error" onRetry={() => query.refetch()} />;
  }
  if (query.isSuccess && query.data.buyers.length === 0) {
    return (
      <div className="space-y-3">
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          Wszyscy nabywcy z KSeF są przypisani do klientów.
        </div>
        <ExtraBuyerNumbersSection />
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
                    <div className="flex flex-wrap justify-end gap-1">
                      {buyer.suggestion?.state === "add" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={assign.isPending}
                          onClick={() => void confirmSuggestion(buyer)}
                        >
                          Przypisz
                        </Button>
                      ) : buyer.suggestion?.state === "differs" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={assign.isPending}
                          title={`Dopisz jako dodatkowy numer klienta ${buyer.suggestion.client_name}`}
                          onClick={() => void confirmExtra(buyer)}
                        >
                          Jako dodatkowy
                        </Button>
                      ) : null}
                      <Button
                        size="sm"
                        variant={buyer.suggestion ? "ghost" : "outline"}
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
          onAssign={(clientId, extra) => assignTo(picking, clientId, () => setPicking(null), extra)}
          onClose={() => setPicking(null)}
        />
      ) : null}
      {skipping ? (
        <SkipBuyerDialog key={skipping.number} buyer={skipping} onClose={() => setSkipping(null)} />
      ) : null}
      <ExtraBuyerNumbersSection />
      {confirmDialog}
    </div>
  );
}

const SOURCE_LABELS: Record<ExtraBuyerNumber["source"], string> = {
  manual: "dopisany przez Finanse",
  auto: "dopisany przez automat",
};

/** Dodatkowe numery klientów (spółki grupy): przegląd i usunięcie, także tych od automatu. */
function ExtraBuyerNumbersSection() {
  const { showToast } = useToast();
  const query = useExtraBuyerNumbers();
  const remove = useRemoveExtraBuyerNumber();
  const { askConfirm, confirmDialog } = useConfirmV2();

  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać dodatkowych numerów klientów.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  const numbers = query.isSuccess ? (query.data?.numbers ?? []) : [];
  if (numbers.length === 0) return null;

  const confirmRemove = async (row: ExtraBuyerNumber) => {
    const label = `${BUYER_NUMBER_LABELS[row.kind]} ${row.number}`;
    const ok = await askConfirm({
      title: `Usunąć ${label} u klienta ${row.client_name ?? ""}?`,
      description:
        "Faktury już przypisane zostają u klienta. Kolejne faktury z tym numerem trafią do „Nieznani nabywcy”.",
      confirmLabel: "Usuń numer",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(row.id, {
      onSuccess: () => showToast("Dodatkowy numer usunięty.", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się usunąć numeru."), "error"),
    });
  };

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium">Dodatkowe numery klientów ({numbers.length})</h3>
      <p className="text-xs text-muted-foreground">
        Spółki z grupy klienta (oddział, spółka leasingowa, fundusz), których faktury trafiają do tego klienta.
      </p>
      <ul className="divide-y divide-border rounded-lg border border-border bg-card text-sm">
        {numbers.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
            <span className="min-w-0 flex-1 truncate font-medium">{row.client_name ?? `Klient ${row.client_id}`}</span>
            <span className="tabular-nums">
              {BUYER_NUMBER_LABELS[row.kind]} {row.number}
            </span>
            <span className="text-xs text-muted-foreground">
              {SOURCE_LABELS[row.source]}
              {row.created_at ? ` ${formatIsoDatePl(row.created_at.slice(0, 10))}` : ""} ·{" "}
              {invoiceWord(row.invoices)}
            </span>
            <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => void confirmRemove(row)}>
              Usuń
            </Button>
          </li>
        ))}
      </ul>
      {confirmDialog}
    </section>
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
  onAssign: (clientId: number, extra: boolean) => void;
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
          <Button
            variant="outline"
            disabled={!client || pending}
            onClick={() => client && onAssign(client.id, true)}
          >
            Jako dodatkowy numer
          </Button>
          <Button disabled={!client || pending} onClick={() => client && onAssign(client.id, false)}>
            {pending ? "Zapisywanie…" : "Przypisz"}
          </Button>
        </>
      }
    >
      <ClientSinglePicker value={client} onChange={setClient} queryKey="unknown-buyer-assign-clients" />
      <p className="mt-2 text-xs text-muted-foreground">
        Klient ma już inny numer, a to spółka z jego grupy? Wybierz „Jako dodatkowy numer”: oba numery będą
        prowadzić do tego klienta.
      </p>
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
