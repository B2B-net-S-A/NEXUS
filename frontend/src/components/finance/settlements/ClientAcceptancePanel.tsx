"use client";

// Finanse → Rozliczenia → lista miesiąca: KCP do akceptacji klienta (roadmapa E6.5,
// Bank Pocztowy; reguła `cl.client_acceptance`). KCP zbieramy i wysyłamy paczką,
// kontraktora rozliczamy bez czekania, fakturę do klienta po jego akceptacji.
// Decyzja Artura z 18.11.2026: paczkę szykuje NEXUS (zip i treść maila), wysyła
// człowiek z Outlooka i klika „Oznacz jako wysłane”; odpowiedź banku NEXUS czyta
// sam (rozliczenia@ albo „Wgraj odpowiedź klienta”), a gdy nie umie — przycisk.
import { useRef, useState } from "react";
import { Copy, Download, Mail, Upload } from "lucide-react";

import { StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import { copyTextToClipboard } from "@/lib/clipboard";
import {
  fetchAcceptancePackage,
  useAcceptByClient,
  useClientAcceptance,
  useMarkAcceptanceSent,
  useUploadAcceptanceReply,
  type ClientAcceptanceBatch,
  type ClientAcceptancePerson,
} from "@/lib/api/client-settlements";

import { dayTime, monthLabel, shortDay } from "./format";

interface ClientAcceptancePanelProps {
  clientId: number;
  month: string;
  canWrite: boolean;
}

/** „J. Kowalski.pdf” — nazwa KCP w paczce, jak w instrukcji rozliczeń. */
export function kcpFileName(person: string): string {
  const [first, ...rest] = person.split(/\s+/).filter(Boolean);
  if (!first || rest.length === 0) return `${person || "KCP"}.pdf`;
  return `${first[0]}. ${rest.join(" ")}.pdf`;
}

function names(people: ClientAcceptancePerson[]): string {
  return people.map((p) => p.person).join(", ");
}

export function ClientAcceptancePanel({ clientId, month, canWrite }: ClientAcceptancePanelProps) {
  const query = useClientAcceptance(clientId, month);
  const markSent = useMarkAcceptanceSent();
  const accept = useAcceptByClient();
  const upload = useUploadAcceptanceReply(month);
  const input = useRef<HTMLInputElement>(null);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const [draftOpen, setDraftOpen] = useState(false);

  const data = query.data;
  if (query.isError) {
    return (
      <p className="rounded-xl border bg-card px-3 py-2 text-xs text-destructive-muted-foreground">
        {apiErrorMessage(query.error, "Nie udało się pobrać stanu akceptacji klienta.")}
      </p>
    );
  }
  if (!query.isSuccess || !data?.enabled) return null;

  const people = data.people ?? [];
  const toSend = people.filter((p) => p.state === "to_send");
  const sent = people.filter((p) => p.state === "sent");
  const accepted = people.filter((p) => p.state === "accepted");
  const missing = people.filter((p) => p.state === "none");
  const withKcp = toSend.length + sent.length + accepted.length;

  async function copy(text: string, what: string) {
    if (await copyTextToClipboard(text)) showSuccess(`Skopiowano ${what}.`);
    else showError(`Nie udało się skopiować: ${what}.`);
  }

  async function onPackage() {
    try {
      downloadBlob(await fetchAcceptancePackage(clientId, month), `KCP_${month}.zip`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać paczki KCP."));
    }
  }

  async function onMarkSent() {
    const ok = await askConfirm({
      title: `Oznaczyć ${toSend.length} KCP jako wysłane?`,
      description: `Do klienta poszły: ${names(toSend)}. Ich faktury do klienta poczekają na akceptację.`,
      confirmLabel: "Oznacz jako wysłane",
    });
    if (!ok) return;
    try {
      const res = await markSent.mutateAsync({ clientId, month, contractIds: toSend.map((p) => p.contract_id) });
      showSuccess(`Wysłane do klienta: ${res.sent}.`);
      setDraftOpen(false);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać wysyłki."));
    }
  }

  async function onAccept(batch: ClientAcceptanceBatch) {
    const waiting = sent.filter((p) => p.sent_at === batch.sent_at);
    const ok = await askConfirm({
      title: "Klient zaakceptował te KCP?",
      description: `${names(waiting)}. Ich faktury do klienta będą do wystawienia.`,
      confirmLabel: "Klient zaakceptował",
    });
    if (!ok) return;
    try {
      const res = await accept.mutateAsync({ clientId, month, contractIds: waiting.map((p) => p.contract_id) });
      showSuccess(`Zaakceptowane przez klienta: ${res.accepted}.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać akceptacji."));
    }
  }

  async function onReply(file: File | undefined) {
    if (!file) return;
    try {
      await upload.mutateAsync(file);
      showSuccess("Odpowiedź klienta odczytana, akceptacja zapisana przy osobach.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się odczytać odpowiedzi klienta."));
    } finally {
      if (input.current) input.current.value = "";
    }
  }

  return (
    <section aria-label="KCP do akceptacji klienta" className="rounded-xl border border-primary/25 bg-primary/[0.04] p-3">
      {confirmDialog}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-[78ch]">
          <h2 className="text-sm font-semibold">
            KCP do akceptacji klienta za {monthLabel(month)}: zaakceptowane {accepted.length} z {withKcp}
          </h2>
          <p className="text-xs text-muted-foreground">
            KCP zbieramy i wysyłamy paczką{data.email ? <> na {data.email}</> : null}. Kontraktora rozliczamy bez czekania na
            klienta, fakturę do klienta wystawiamy po akceptacji. Odpowiedź klienta na rozliczenia@ NEXUS odczytuje sam.
          </p>
        </div>
        {canWrite ? (
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" disabled={toSend.length === 0} onClick={() => setDraftOpen((v) => !v)}>
              <Mail aria-hidden className="size-3.5" /> Wyślij do akceptacji ({toSend.length} KCP)
            </Button>
            <input
              ref={input}
              type="file"
              accept=".msg,.eml"
              className="hidden"
              aria-hidden
              tabIndex={-1}
              onChange={(event) => onReply(event.target.files?.[0])}
            />
            <Button size="sm" variant="outline" disabled={upload.isPending} onClick={() => input.current?.click()}>
              <Upload aria-hidden className="size-3.5" /> {upload.isPending ? "Sprawdzam…" : "Wgraj odpowiedź klienta"}
            </Button>
            {data.email ? (
              <Button size="sm" variant="outline" aria-label="Kopiuj adres klienta" onClick={() => copy(data.email ?? "", "adres")}>
                <Copy aria-hidden className="size-3.5" /> Adres
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      <ul className="mt-2 grid gap-1 text-xs">
        {(data.batches ?? []).map((b) => (
          <li key={b.sent_at} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            {b.accepted === b.people ? (
              <StatusDot tone="success">
                Paczka {dayTime(b.sent_at)} · {b.people} KCP · zaakceptowana {shortDay(b.accepted_at)}
              </StatusDot>
            ) : (
              <StatusDot tone="warning">
                Paczka {dayTime(b.sent_at)} · {b.people} KCP · zaakceptowane {b.accepted} z {b.people}
              </StatusDot>
            )}
            {b.reply ? <span className="text-muted-foreground">„{b.reply}”</span> : null}
            {canWrite && b.accepted < b.people ? (
              <button
                type="button"
                onClick={() => onAccept(b)}
                disabled={accept.isPending}
                className="font-medium text-primary hover:underline disabled:opacity-50"
              >
                Klient zaakceptował
              </button>
            ) : null}
          </li>
        ))}
        {toSend.length > 0 ? (
          <li>
            <StatusDot tone="info">Do wysłania: {names(toSend)}</StatusDot>
          </li>
        ) : null}
        {missing.length > 0 ? <li className="text-muted-foreground">Brak KCP: {names(missing)}.</li> : null}
      </ul>

      {draftOpen && toSend.length > 0 ? (
        <div className="mt-2.5 rounded-lg border bg-card p-3 text-[13px]">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <dl className="grid min-w-0 grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
              <dt className="text-muted-foreground">Do</dt>
              <dd className="min-w-0 break-words">{data.email || "adres z reguły klienta"}</dd>
              <dt className="text-muted-foreground">Temat</dt>
              <dd className="min-w-0 break-words">{data.subject}</dd>
              <dt className="text-muted-foreground">Załączniki</dt>
              <dd className="min-w-0 break-words">{toSend.map((p) => kcpFileName(p.person)).join(", ")}</dd>
            </dl>
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" variant="outline" onClick={onPackage}>
                <Download aria-hidden className="size-3.5" /> KCP (zip)
              </Button>
              <Button size="sm" variant="outline" onClick={() => copy(data.body ?? "", "treść maila")}>
                <Copy aria-hidden className="size-3.5" /> Kopiuj treść
              </Button>
              <Button size="sm" disabled={markSent.isPending} onClick={onMarkSent}>
                Oznacz jako wysłane
              </Button>
            </div>
          </div>
          <p className="mt-2 whitespace-pre-line border-t pt-2 text-xs leading-5">{data.body}</p>
        </div>
      ) : null}
    </section>
  );
}
