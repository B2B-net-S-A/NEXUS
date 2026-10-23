"use client";

import { useRef, useState, type DragEvent } from "react";
import { Download, FileUp, Pencil } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadApprovalDocument,
  useAnswerRenewal,
  useRemoveApprovalDocument,
  useRequestTopup,
  useUpdateApprovalDocument,
  useUploadApprovalDocument,
  type ApprovalDocument,
  type ApprovalDocumentInput,
  type ApprovalRequestRow,
  type ApprovalSettlement,
} from "@/lib/api/hr-approvals";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { ComparisonPill, expiryHint, settlementLine } from "./settlement-format";
import { moneyPl } from "./approvals-format";

const ACCEPT = "application/pdf,image/jpeg,image/png";
const MAX_BYTES = 10 * 1024 * 1024;
const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

function DocumentEditor({
  row,
  doc,
  onClose,
}: {
  row: ApprovalRequestRow;
  doc: ApprovalDocument;
  onClose: () => void;
}) {
  const update = useUpdateApprovalDocument();
  const { showToast } = useToast();
  const fromKsef = doc.source === "ksef";
  const [form, setForm] = useState({
    gross_amount: doc.gross_amount ?? "",
    net_amount: doc.net_amount ?? "",
    currency: doc.currency,
    seller_name: doc.seller_name ?? "",
    seller_nip: doc.seller_nip ?? "",
    invoice_number: doc.invoice_number ?? "",
    issue_date: doc.issue_date ?? "",
  });
  const set = (key: keyof typeof form, value: string) => setForm((prev) => ({ ...prev, [key]: value }));
  const save = () => {
    const input: ApprovalDocumentInput = {
      seller_name: form.seller_name || null,
      invoice_number: form.invoice_number || null,
      issue_date: form.issue_date || null,
    };
    if (!fromKsef) {
      input.seller_nip = form.seller_nip || null;
      input.gross_amount = form.gross_amount.replace(",", ".") || null;
      input.net_amount = form.net_amount.replace(",", ".") || null;
      input.currency = form.currency.toUpperCase();
    }
    update.mutate(
      { id: row.id, documentId: doc.id, input },
      {
        onSuccess: () => {
          showToast("Dane dokumentu zapisane.", "success");
          onClose();
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać dokumentu."), "error"),
      },
    );
  };
  const field = (key: keyof typeof form, label: string, props: { disabled?: boolean; type?: string } = {}) => (
    <label className="block space-y-1 text-xs font-medium text-foreground">
      <span>{label}</span>
      <Input
        value={form[key]}
        onChange={(event) => set(key, event.target.value)}
        disabled={props.disabled}
        type={props.type ?? "text"}
      />
    </label>
  );
  return (
    <div className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
      <div className="grid gap-3 sm:grid-cols-3">
        {field("gross_amount", "Kwota brutto", { disabled: fromKsef })}
        {field("net_amount", "Netto (jeśli jest)", { disabled: fromKsef })}
        {field("currency", "Waluta", { disabled: fromKsef })}
        {field("seller_name", "Sprzedawca")}
        {field("seller_nip", "NIP sprzedawcy", { disabled: fromKsef })}
        {field("invoice_number", "Numer dokumentu")}
        {field("issue_date", "Data wystawienia", { type: "date" })}
      </div>
      {fromKsef ? (
        <p className="text-xs text-muted-foreground">
          Kwoty i NIP sprzedawcy z faktury KSeF są wiążące — nie zmieniasz ich.
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={save} loading={update.isPending}>
          Zapisz
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Anuluj
        </Button>
      </div>
    </div>
  );
}

function DocumentRow({ row, doc }: { row: ApprovalRequestRow; doc: ApprovalDocument }) {
  const [editing, setEditing] = useState(false);
  const remove = useRemoveApprovalDocument();
  const topup = useRequestTopup();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();

  const askRemove = async () => {
    const ok = await askConfirm({
      title: doc.source === "ksef" ? "Odpiąć fakturę z KSeF?" : "Usunąć dokument?",
      description:
        doc.source === "ksef"
          ? "Faktura wróci do kolejki Finansów „Faktury bez zgody”."
          : "Plik zniknie z tej zgody. Możesz dołączyć właściwy.",
      confirmLabel: doc.source === "ksef" ? "Odepnij" : "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(
      { id: row.id, documentId: doc.id },
      { onError: (err) => showToast(apiErrorMessage(err, "Nie udało się usunąć dokumentu."), "error") },
    );
  };
  const askTopup = () =>
    topup.mutate(
      { id: row.id, documentId: doc.id },
      {
        onSuccess: () => showToast("Prośba o dopłatę poszła do zatwierdzającego.", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się poprosić o dopłatę."), "error"),
      },
    );
  const download = () =>
    downloadApprovalDocument(row.id, doc).catch((err) =>
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error"),
    );

  return (
    <li className="space-y-2 border-t border-border/60 py-3 first:border-t-0">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">
            {doc.doc_type === "receipt" ? "Paragon" : "Faktura"}
            {doc.invoice_number ? ` ${doc.invoice_number}` : ""}
            {doc.source === "ksef" ? (
              <span className="ml-2 rounded-full bg-muted px-2 py-px text-[11px] font-medium text-muted-foreground">
                KSeF
              </span>
            ) : null}
          </p>
          <p className="text-xs text-muted-foreground">
            {[doc.seller_name, doc.seller_nip ? `NIP ${doc.seller_nip}` : null, doc.issue_date ? formatIsoDatePl(doc.issue_date) : null]
              .filter(Boolean)
              .join(" · ") || "Sprzedawca nieodczytany"}
          </p>
          {doc.read_status === "failed" || doc.read_status === "skipped" ? (
            <p className="text-xs text-warning-muted-foreground">
              NEXUS nie odczytał kwoty z pliku — wpisz ją w „Popraw”.
            </p>
          ) : null}
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold tabular-nums text-foreground">
            {doc.gross_amount ? moneyPl(doc.gross_amount, doc.currency) : "—"}
          </p>
          {row.recurrence !== "once" && doc.comparison ? <ComparisonPill comparison={doc.comparison} /> : null}
          {doc.status === "settled" ? (
            <p className="text-xs text-success-muted-foreground">rozliczona</p>
          ) : null}
        </div>
      </div>
      {doc.topup ? (
        <p
          className={cn(
            "rounded-md px-2.5 py-1.5 text-xs",
            doc.topup.status === "pending" && "bg-muted text-foreground",
            doc.topup.status === "approved" && "bg-success-muted text-success-muted-foreground",
            doc.topup.status === "rejected" && "bg-destructive/10 text-destructive",
          )}
        >
          Dopłata {moneyPl(doc.topup.amount, doc.currency)}:{" "}
          {doc.topup.status === "pending"
            ? "czeka na zatwierdzającego"
            : doc.topup.status === "approved"
              ? `zatwierdzona${doc.topup.decided_by_name ? ` — ${doc.topup.decided_by_name}` : ""}`
              : `odrzucona${doc.topup.note ? ` — „${doc.topup.note}”` : ""}`}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {doc.can_request_topup ? (
          <Button size="sm" onClick={askTopup} loading={topup.isPending}>
            Poproś o dopłatę
          </Button>
        ) : null}
        {doc.has_file ? (
          <Button size="sm" variant="outline" onClick={download}>
            <Download className="h-3.5 w-3.5" aria-hidden />
            Pobierz
          </Button>
        ) : null}
        {doc.can_edit && !editing ? (
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            <Pencil className="h-3.5 w-3.5" aria-hidden />
            Popraw
          </Button>
        ) : null}
        {doc.can_remove ? (
          <Button size="sm" variant="quiet" onClick={askRemove} disabled={remove.isPending}>
            {doc.source === "ksef" ? "Odepnij" : "Usuń"}
          </Button>
        ) : null}
      </div>
      {editing ? <DocumentEditor row={row} doc={doc} onClose={() => setEditing(false)} /> : null}
      {confirmDialog}
    </li>
  );
}

function DropZone({ row }: { row: ApprovalRequestRow }) {
  const upload = useUploadApprovalDocument();
  const { showToast } = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const send = (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      showToast("Faktura albo paragon może mieć najwyżej 10 MB.", "error");
      return;
    }
    upload.mutate(
      { id: row.id, file },
      {
        onSuccess: () => showToast("Dokument dołączony. Sprawdź odczytaną kwotę.", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się dołączyć dokumentu."), "error"),
      },
    );
  };
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setOver(false);
    send(event.dataTransfer.files?.[0]);
  };
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cn(
        "relative flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border p-4",
        over && "border-primary bg-primary/5",
      )}
    >
      <FileUp className="h-5 w-5 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">Przeciągnij fakturę albo paragon</p>
        <p className="text-xs text-muted-foreground">PDF lub zdjęcie do 10 MB · NEXUS odczyta kwotę i sprzedawcę</p>
      </div>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        aria-label="Wybierz fakturę albo paragon"
        onChange={(event) => {
          send(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      <Button variant="outline" onClick={() => input.current?.click()} loading={upload.isPending}>
        Wybierz plik
      </Button>
    </div>
  );
}

function RenewalBox({ row, settlement }: { row: ApprovalRequestRow; settlement: ApprovalSettlement }) {
  const answer = useAnswerRenewal();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  const asked = settlement.renews_on !== null && settlement.renewal_asked_for === settlement.renews_on;
  const confirmed = settlement.renews_on !== null && settlement.renewal_confirmed_for === settlement.renews_on;

  const send = (keep: boolean) =>
    answer.mutate(
      { id: row.id, keep },
      {
        onSuccess: () => showToast(keep ? "Zapisane: subskrypcja dalej potrzebna." : "Subskrypcja zakończona.", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać odpowiedzi."), "error"),
      },
    );
  const askEnd = async () => {
    const ok = await askConfirm({
      title: "Zakończyć subskrypcję?",
      description: "Zniknie z rejestru Finansów. Pamiętaj, żeby wyłączyć ją też u dostawcy.",
      confirmLabel: "Zakończ",
      variant: "destructive",
    });
    if (ok) send(false);
  };
  return (
    <div className="space-y-2 rounded-lg bg-muted/50 px-3.5 py-3 text-sm">
      {settlement.renews_on ? (
        <p>
          <span className="font-semibold">Odnowienie roczne: {formatIsoDatePl(settlement.renews_on)}</span>
          {confirmed ? " · potwierdzone, że dalej potrzebna" : ""}
        </p>
      ) : (
        <p className="font-semibold">Odnawia się co miesiąc</p>
      )}
      {asked && !confirmed && settlement.can_answer_renewal ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">Czy jest dalej potrzebna?</span>
          <Button size="sm" onClick={() => send(true)} loading={answer.isPending}>
            Dalej potrzebna
          </Button>
          <Button size="sm" variant="outline" onClick={askEnd}>
            Wyłącz
          </Button>
        </div>
      ) : settlement.can_end ? (
        <Button size="sm" variant="quiet" onClick={askEnd}>
          Zakończ subskrypcję
        </Button>
      ) : null}
      {confirmDialog}
    </div>
  );
}

/**
 * Rozliczenie zatwierdzonego wydatku (makieta 4, etap 3 — 0486): dokument
 * z odczytaną kwotą, porównanie ze zgodą (+10%), dopłata, odnowienie.
 */
export function SettlementSection({ row }: { row: ApprovalRequestRow }) {
  const settlement = row.settlement;
  if (!settlement) return null;
  const docs = settlement.documents;
  const recurring = row.recurrence !== "once";
  return (
    <section aria-label="Rozliczenie" className="space-y-3 border-t border-border/60 pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className={LABEL}>Rozliczenie</h3>
        <span className="rounded-full bg-muted px-2 py-px text-xs font-medium text-foreground">
          {settlement.status_label}
        </span>
      </div>
      <p className="text-sm text-foreground">{settlementLine(row, settlement)}</p>

      {!recurring && settlement.comparison ? (
        <div className="flex flex-wrap gap-6 rounded-lg bg-muted/50 px-3.5 py-3">
          <div>
            <p className="text-xs text-muted-foreground">Zgoda</p>
            <p className="text-lg font-semibold tabular-nums">{moneyPl(settlement.comparison.approved, row.currency)}</p>
          </div>
          {settlement.comparison.documented ? (
            <div>
              <p className="text-xs text-muted-foreground">Z dokumentów</p>
              <p className="text-lg font-semibold tabular-nums">
                {moneyPl(settlement.comparison.documented, row.currency)}{" "}
                <ComparisonPill comparison={settlement.comparison} />
              </p>
            </div>
          ) : null}
        </div>
      ) : null}

      {recurring ? <RenewalBox row={row} settlement={settlement} /> : null}

      {docs.length > 0 ? (
        <ul aria-label="Dokumenty" className="rounded-lg border border-border px-3.5">
          {docs.map((doc) => (
            <DocumentRow key={doc.id} row={row} doc={doc} />
          ))}
        </ul>
      ) : null}

      {settlement.can_add_document ? <DropZone row={row} /> : null}

      {settlement.status === "open" || settlement.status === "documented" || settlement.status === "active" ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <p className="rounded-lg bg-warning-muted px-3 py-2.5 text-xs leading-relaxed text-warning-muted-foreground">
            <b>Gdy wyjdzie drożej o więcej niż {settlement.tolerance_percent}%</b> — poprosisz zatwierdzającego
            o dopłatę jednym przyciskiem, bez nowej zgody.
          </p>
          <p className="rounded-lg bg-muted/50 px-3 py-2.5 text-xs leading-relaxed text-foreground">
            <b>{expiryHint(row)[0]}</b>
            {expiryHint(row)[1]}
            {row.kind === "trip" ? " Wyjazd jest już w kalendarzu zespołu." : ""}
            {row.kind === "gift" && settlement.client_name ? ` Prezent jest w Historii klienta ${settlement.client_name}.` : ""}
          </p>
        </div>
      ) : null}
    </section>
  );
}
