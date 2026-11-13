"use client";

// Dodatki do rozliczenia kontraktora na karcie osoby (potrzeba Finansów 13.11.2026):
// premia za polecenie, weryfikacja techniczna, szkolenie, delegacja. Zgłoszenia
// z back office'u i z panelu konsultanta czekają tu na zatwierdzenie; Finanse
// mogą też wpisać dodatek same (od razu zatwierdzony). Zatwierdzony dodatek
// zwiększa oczekiwaną kwotę faktury kontraktora.
import { useRef, useState } from "react";
import { FileText, Paperclip } from "lucide-react";

import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import {
  fetchExtraDocument,
  useAddSettlementExtra,
  useDecideSettlementExtra,
  useUploadExtraDocument,
  type SettlementExtra,
  type SettlementExtraKind,
  type SettlementExtraStatus,
  type SettlementExtrasBlock,
} from "@/lib/api/client-settlements";

import { pln } from "./format";

const STATUS_TONE: Record<SettlementExtraStatus, StatusDotTone> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
};

interface ExtrasSectionProps {
  contractId: number;
  month: string;
  block: SettlementExtrasBlock;
  canWrite: boolean;
}

export function ExtrasSection({ contractId, month, block, canWrite }: ExtrasSectionProps) {
  const [adding, setAdding] = useState(false);
  const visible = block.items.filter((e) => e.counts_on_invoice);
  return (
    <section className="rounded-xl border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Dodatki do faktury</h3>
        {canWrite && !adding ? (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            Dodaj dodatek
          </Button>
        ) : null}
      </div>
      {visible.length === 0 && !adding ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Bez dodatków: premię za polecenie, weryfikację techniczną, szkolenie albo delegację zgłasza back office, konsultant w
          panelu albo Finanse tutaj.
        </p>
      ) : null}
      {visible.length > 0 ? (
        <ul className="mt-1 divide-y text-[13px]">
          {visible.map((extra) => (
            <ExtraRow key={extra.id} extra={extra} contractId={contractId} month={month} canWrite={canWrite} />
          ))}
        </ul>
      ) : null}
      {visible.length > 0 && block.approved_total != null ? (
        <p className="mt-1.5 border-t pt-1.5 text-xs text-muted-foreground">
          Zatwierdzone: <span className="font-medium text-foreground tabular-nums">{pln(block.approved_total)}</span> — liczą się
          do kwoty faktury kontraktora
          {block.pending_count > 0 ? `; czeka ${block.pending_count} na ${pln(block.pending_total)}` : ""}.
        </p>
      ) : null}
      {adding ? <AddExtraForm contractId={contractId} month={month} block={block} onDone={() => setAdding(false)} /> : null}
    </section>
  );
}

function ExtraRow({
  extra,
  contractId,
  month,
  canWrite,
}: {
  extra: SettlementExtra;
  contractId: number;
  month: string;
  canWrite: boolean;
}) {
  const decide = useDecideSettlementExtra(month);
  const upload = useUploadExtraDocument(month);
  const { askReason, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);

  async function run(decision: Parameters<typeof decide.mutateAsync>[0]["decision"], done: string) {
    try {
      await decide.mutateAsync({ contractId, extraId: extra.id, decision });
      showSuccess(done);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać decyzji o dodatku."));
    }
  }

  async function onReject() {
    // Koszt dodatkowy odrzuca rozliczający, zawsze z powodem (reguła „Koszty dodatkowe potwierdza osoba rozliczająca”).
    const reason = await askReason({
      title: `Odrzucić dodatek „${extra.kind_label}”?`,
      description: "Zgłaszający zobaczy powód. Faktura z tym dodatkiem będzie miała inną kwotę niż rozliczenie.",
      confirmLabel: "Odrzuć dodatek",
      field: { label: "Dlaczego", minLength: 5, maxLength: 500 },
    });
    if (reason) await run({ action: "reject", reason }, "Dodatek odrzucony.");
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    try {
      await upload.mutateAsync({ contractId, extraId: extra.id, file });
      showSuccess("Plik dołączony do dodatku.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się dołączyć pliku."));
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function open(docId: number, name: string | null) {
    try {
      downloadBlob(await fetchExtraDocument(contractId, extra.id, docId), name ?? `dokument-${docId}`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać pliku."));
    }
  }

  const busy = decide.isPending || upload.isPending;
  return (
    <li className="py-2">
      {confirmDialog}
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="min-w-0 font-medium">
          {extra.kind_label}
          {extra.description !== extra.kind_label ? (
            <span className="font-normal text-muted-foreground"> · {extra.description}</span>
          ) : null}
        </span>
        <span className="tabular-nums">{pln(extra.amount)} netto</span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <StatusDot tone={STATUS_TONE[extra.status]}>{extra.status_label}</StatusDot>
        <span>
          {[extra.source_label, extra.reported_by].filter(Boolean).join(": ")}
          {extra.created_at ? ` · ${new Date(extra.created_at).toLocaleDateString("pl-PL")}` : ""}
        </span>
      </div>
      {extra.status === "rejected" && extra.decision_note ? (
        <p className="mt-1 text-xs text-destructive-muted-foreground">Powód: {extra.decision_note}</p>
      ) : null}
      {extra.documents.length > 0 ? (
        <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
          {extra.documents.map((doc) => (
            <li key={doc.id} className="flex min-w-0 items-center gap-1">
              <FileText aria-hidden className="size-3 shrink-0 text-muted-foreground" />
              <button
                type="button"
                onClick={() => open(doc.id, doc.file_name)}
                className="max-w-56 truncate text-primary hover:underline"
                title="Pobierz plik"
              >
                {doc.file_name ?? "Plik bez nazwy"}
              </button>
            </li>
          ))}
        </ul>
      ) : extra.kind === "travel" ? (
        <p className="mt-1 text-xs text-warning-muted-foreground">Delegacja bez dokumentów — dopytaj o fakturę, paragon albo bilety.</p>
      ) : null}
      {canWrite ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <label className="flex items-center gap-1.5 text-xs">
            <Checkbox
              checked={extra.bill_to_client}
              disabled={busy}
              onCheckedChange={(value) =>
                run(
                  { action: "billing", billToClient: value === true },
                  value === true ? "Dodatek pójdzie na fakturę dla klienta." : "Dodatek tylko po naszej stronie.",
                )
              }
            />
            Na fakturę dla klienta
          </label>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.docx"
            className="hidden"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => fileRef.current?.click()}>
            <Paperclip aria-hidden className="size-3.5" />
            Dołącz plik
          </Button>
          {extra.status !== "approved" ? (
            <Button size="sm" disabled={busy} onClick={() => run({ action: "approve" }, "Dodatek zatwierdzony.")}>
              Zatwierdź
            </Button>
          ) : null}
          {extra.status !== "rejected" ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={onReject}>
              Odrzuć
            </Button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function AddExtraForm({
  contractId,
  month,
  block,
  onDone,
}: {
  contractId: number;
  month: string;
  block: SettlementExtrasBlock;
  onDone: () => void;
}) {
  const add = useAddSettlementExtra(month);
  const { showSuccess, showError } = useToast();
  const [kind, setKind] = useState<SettlementExtraKind>(block.kinds[0]?.key ?? "referral");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [bill, setBill] = useState(false);
  const value = amount.trim().replace(/\s/g, "").replace(",", ".");
  const valid = value !== "" && Number(value) > 0 && (kind !== "other" || description.trim().length >= 3);

  async function onSave() {
    try {
      await add.mutateAsync({ contractId, kind, amount: value, description: description.trim(), billToClient: bill });
      showSuccess("Dodatek zapisany i zatwierdzony.");
      onDone();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać dodatku."));
    }
  }

  return (
    <div className="mt-2 grid gap-2 rounded-lg bg-muted/40 p-2 text-xs">
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-0.5">
          <span className="text-muted-foreground">Rodzaj</span>
          <select
            aria-label="Rodzaj dodatku"
            value={kind}
            onChange={(e) => setKind(e.target.value as SettlementExtraKind)}
            className="h-8 rounded-md border border-border bg-background px-2 text-sm pointer-coarse:h-10"
          >
            {block.kinds.map((k) => (
              <option key={k.key} value={k.key}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-0.5">
          <span className="text-muted-foreground">Kwota netto (zł)</span>
          <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="h-8 w-28 text-sm tabular-nums" />
        </label>
        <label className="grid min-w-48 flex-1 gap-0.5">
          <span className="text-muted-foreground">Opis {kind === "other" ? "" : "(opcjonalnie)"}</span>
          <Input value={description} maxLength={300} onChange={(e) => setDescription(e.target.value)} className="h-8 text-sm" />
        </label>
      </div>
      <label className="flex items-center gap-1.5">
        <Checkbox checked={bill} onCheckedChange={(v) => setBill(v === true)} />
        Na fakturę dla klienta
      </label>
      <div className="flex gap-1.5">
        <Button size="sm" disabled={!valid || add.isPending} onClick={onSave}>
          Zapisz i zatwierdź
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
      </div>
    </div>
  );
}
