"use client";

// Finanse → Rozliczenia → lista miesiąca: zbiorczy protokół odbioru i paczka
// do klienta (roadmapa E6.1, PKO; reguła `cl.client_document` na „cały miesiąc”).
// Protokół i paczka (protokół, Time Sheety, akceptacje w HTML) są gotowe dopiero
// przy komplecie osób. Faktura do klienta po podpisanym protokole.
import { Copy, Download } from "lucide-react";

import { StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import { copyTextToClipboard } from "@/lib/clipboard";
import {
  fetchClientDocumentFile,
  type ClientDocumentFileKind,
  type ClientDocumentsMonth,
} from "@/lib/api/client-settlements";

import { STATUS, mdText, monthLabel, pln } from "./format";
import { SignedDocumentUpload } from "./SignedDocumentUpload";

const SHOWN = 6;

function names(list: string[]): string {
  if (list.length <= SHOWN) return list.join(", ");
  return `${list.slice(0, SHOWN).join(", ")} i ${list.length - SHOWN} innych`;
}

export function ProtocolPanel({ data, clientId }: { data: ClientDocumentsMonth; clientId: number }) {
  const { showError, showSuccess } = useToast();
  const p = data.protocol;
  if (!p) return null;
  const month = data.month;
  const waitingText = names(p.waiting.map((w) => `${w.person} (${STATUS[w.status].label.toLowerCase()})`));

  async function onDownload(kind: ClientDocumentFileKind, name: string) {
    try {
      downloadBlob(await fetchClientDocumentFile(clientId, month, kind), name);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać dokumentu."));
    }
  }

  async function onCopyAddress() {
    if (!p?.send_to) return;
    if (await copyTextToClipboard(p.send_to)) showSuccess("Skopiowano adres paczki.");
    else showError("Nie udało się skopiować adresu.");
  }

  const notReady = `Czeka na komplet: przyjęte ${p.accepted} z ${p.people} osób`;

  return (
    <section aria-label={data.kind} className="rounded-xl border border-primary/25 bg-primary/[0.04] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-[78ch]">
          <h2 className="text-sm font-semibold">
            {data.kind} i paczka za {monthLabel(month)}: przyjęte {p.accepted} z {p.people} osób
          </h2>
          <p className="text-xs text-muted-foreground">
            Jeden zbiorczy protokół na wszystkie osoby. Podpisujemy my, potem klient. Paczka (protokół, Time Sheety i akceptacje
            w HTML) idzie {p.send_to ? <>na {p.send_to}</> : "na adres z reguły klienta"}, gdy komplet jest u wszystkich. Fakturę do
            klienta wystawiamy po podpisanym protokole.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {data.can_see_amounts ? (
            <>
              <Button
                size="sm"
                disabled={!p.ready}
                title={p.ready ? undefined : notReady}
                onClick={() => onDownload("protocol", `Protokol_odbioru_${month}.pdf`)}
              >
                <Download aria-hidden className="size-3.5" /> Pobierz protokół do podpisu
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!p.ready}
                title={p.ready ? undefined : notReady}
                onClick={() => onDownload("package", `Paczka_${month}.zip`)}
              >
                <Download aria-hidden className="size-3.5" /> Pobierz paczkę
              </Button>
            </>
          ) : null}
          {p.send_to ? (
            <Button size="sm" variant="outline" onClick={onCopyAddress} aria-label="Kopiuj adres paczki">
              <Copy aria-hidden className="size-3.5" /> Adres
            </Button>
          ) : null}
          <SignedDocumentUpload month={month} label="Wgraj podpisany" />
        </div>
      </div>
      <ul className="mt-2 grid gap-0.5 text-xs">
        <li>
          {p.signed ? (
            <StatusDot tone="success">Protokół podpisany przez klienta{p.signed_by ? `: ${p.signed_by}` : ""}</StatusDot>
          ) : p.ready ? (
            <StatusDot tone="info">Komplet: protokół gotowy do podpisu</StatusDot>
          ) : (
            <StatusDot tone="neutral">{notReady}</StatusDot>
          )}
        </li>
        <li className="tabular-nums text-muted-foreground">
          W protokole: {p.files.length} osób, {mdText(p.hours)} h
          {data.can_see_amounts && p.net ? <>, {pln(p.net)} netto</> : null}
          {!data.can_see_amounts ? ". Protokół ma stawki i kwoty: pobierają go osoby z dostępem do kwot." : null}
        </li>
        {p.waiting.length > 0 ? <li className="text-muted-foreground">Czekamy na: {waitingText}.</li> : null}
        {p.missing_roles.length > 0 ? (
          <li className="text-warning-muted-foreground">
            Bez roli w protokole (brak rekrutacji przy kontrakcie): {names(p.missing_roles)}.
          </li>
        ) : null}
        {p.missing_orders.length > 0 ? (
          <li className="text-warning-muted-foreground">Bez numeru zamówienia: {names(p.missing_orders)}.</li>
        ) : null}
      </ul>
    </section>
  );
}
